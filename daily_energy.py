"""
에너지 일별 Top 20 보고서 생성기
- articles_energy.json에서 읽어서 에너지 유사도 + 신뢰도 점수 산출
- 날짜별 Top 20 기사만 추출
- 깔끔한 일별 타임라인 HTML 생성
"""

import json
import sys
import io
from datetime import datetime
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

OUTPUT_DIR = Path(__file__).parent
ARTICLES_JSON = OUTPUT_DIR / "articles_energy.json"
REPORT_HTML = OUTPUT_DIR / "report_energy_daily.html"

# ── 에너지 키워드 (가중치) ──
ENERGY_KEYWORDS = {
    # 재생에너지 (5점)
    'SOLAR': 3, 'PHOTOVOLTAIC': 4, 'PV': 2,
    'WIND FARM': 4, 'WIND ENERGY': 4, 'WIND POWER': 4,
    'OFFSHORE WIND': 5, 'ONSHORE WIND': 4,
    'RENEWABLE': 3, 'CLEAN ENERGY': 3,
    # 수소 (5점)
    'HYDROGEN': 4, 'GREEN HYDROGEN': 5, 'BLUE HYDROGEN': 5,
    'FUEL CELL': 4, 'ELECTROLYZER': 5, 'ELECTROLYSIS': 5,
    'AMMONIA FUEL': 4,
    # 원자력 (5점)
    'NUCLEAR': 3, 'SMR': 5, 'SMALL MODULAR REACTOR': 5,
    'NUCLEAR FUSION': 5, 'FISSION': 4, 'URANIUM': 3,
    'NUCLEAR RENAISSANCE': 5,
    # 배터리 (5점)
    'BATTERY': 3, 'LITHIUM': 3, 'SOLID STATE BATTERY': 5,
    'SODIUM ION': 5, 'ESS': 4, 'ENERGY STORAGE': 4,
    'GIGAFACTORY': 4, 'CATL': 3, 'LG ENERGY': 3,
    # 제작/투자/정책 (보너스)
    'INVESTMENT': 3, 'BILLION': 2, 'FUNDING': 3,
    'CONSTRUCTION': 3, 'BUILD': 2, 'CAPACITY': 2,
    'GW': 3, 'MW': 2, 'GIGAWATT': 3, 'MEGAWATT': 2,
    'POLICY': 2, 'SUBSIDY': 3, 'TAX CREDIT': 3,
    'IRA': 3, 'INFLATION REDUCTION ACT': 4,
    'NET ZERO': 3, 'CARBON NEUTRAL': 3, 'DECARBONIZATION': 3,
    'GRID': 2, 'TRANSMISSION': 2, 'INTERCONNECTION': 3,
    'BREAKTHROUGH': 4, 'MILESTONE': 4, 'RECORD': 3,
    'MASS PRODUCTION': 4, 'COMMERCIALIZATION': 4,
}

KOREAN_INDICATORS = [
    '.co.kr', '.kr/', 'chosun', 'joongang', 'joins.com', 'donga',
    'hankyung', 'mk.co', 'sedaily', 'etnews', 'hani.co', 'khan.co',
    'yonhap', 'newsis', 'news1', 'edaily', 'bloter', 'theelec',
    'daum.net', 'naver.com', 'ajupress', 'aju.news', 'asiae',
    'heraldcorp', 'koreaherald', 'koreatimes', 'koreabiomed',
    'businesskorea', 'pulsenews', 'theinvestor', 'korea',
    'kmib', 'nocutnews', 'fnnews', 'newspim', 'sisajournal',
    'dt.co.kr', 'inews24', 'ddaily', 'businesspost', 'mt.co.kr',
    'zdnet.co.kr',
]


def is_korean(art):
    check = (
        art.get('real_url', '') + ' ' +
        art.get('source_name', '') + ' ' +
        art.get('link', '')
    ).lower()
    return any(k in check for k in KOREAN_INDICATORS)


def calc_relevance_score(title):
    upper = title.upper()
    score = 0
    for kw, weight in ENERGY_KEYWORDS.items():
        if kw in upper:
            score += weight
    return score


def calc_tier_score(tier):
    return {1: 10, 2: 7, 3: 4, 4: 1}.get(tier, 1)


def main():
    with open(ARTICLES_JSON, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    print(f"원본: {len(articles)}건")

    articles = [a for a in articles if not is_korean(a)]
    print(f"한국 매체 제외 후: {len(articles)}건")

    for art in articles:
        rel_score = calc_relevance_score(art['title'])
        tier_score = calc_tier_score(art.get('tier', 4))
        art['relevance'] = rel_score
        art['tier_score'] = tier_score
        art['total_score'] = round(rel_score * 0.7 + tier_score * 0.3, 1)

    by_date = defaultdict(list)
    for art in articles:
        d = art.get('date', '')
        if d:
            by_date[d].append(art)

    daily_top = {}
    total_selected = 0
    for date in sorted(by_date.keys(), reverse=True):
        day_arts = by_date[date]
        day_arts.sort(key=lambda x: x['total_score'], reverse=True)
        top20 = day_arts[:20]
        daily_top[date] = top20
        total_selected += len(top20)

    print(f"날짜 수: {len(daily_top)}일")
    print(f"Top 20 선별: {total_selected}건")

    for date in sorted(daily_top.keys(), reverse=True)[:5]:
        print(f"\n--- {date} ---")
        for i, a in enumerate(daily_top[date][:3]):
            print(f"  {i+1}. [{a['total_score']}점] {a['title'][:70]}")

    html = generate_daily_html(daily_top, total_selected)
    with open(REPORT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"\n저장: {REPORT_HTML}")
    print(f"완료!")


def generate_daily_html(daily_top, total_selected):
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    num_days = len(daily_top)

    days_html = ""
    for date in sorted(daily_top.keys(), reverse=True):
        arts = daily_top[date]
        if not arts:
            continue

        try:
            dt = datetime.strptime(date, '%Y-%m-%d')
            weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            weekday = weekdays[dt.weekday()]
        except Exception:
            weekday = ''

        rows = ""
        for i, art in enumerate(arts):
            cat = art.get('category', 'renewable')
            cat_labels = {'renewable': 'Renewable', 'hydrogen': 'Hydrogen',
                          'nuclear': 'Nuclear', 'battery': 'Battery'}
            cat_colors = {'renewable': '#66bb6a', 'hydrogen': '#29b6f6',
                          'nuclear': '#ffa726', 'battery': '#ab47bc'}
            cat_label = cat_labels.get(cat, cat)
            cat_color = cat_colors.get(cat, '#888')

            score = art.get('total_score', 0)
            source = (art.get('source_name', '') or '').replace('&', '&amp;').replace('<', '&lt;')
            title = art.get('title', '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            url = art.get('real_url', art.get('link', '#'))

            bar_pct = min(score / 30 * 100, 100)

            rows += f"""
            <div class="article">
              <div class="rank">#{i+1}</div>
              <div class="content">
                <div class="article-meta">
                  <span class="cat-tag" style="background:{cat_color}22;color:{cat_color};border-color:{cat_color}44">{cat_label}</span>
                  <span class="source">{source}</span>
                  <span class="score-wrap">
                    <span class="score-bar" style="width:{bar_pct}%"></span>
                    <span class="score-num">{score}</span>
                  </span>
                </div>
                <a href="{url}" target="_blank" rel="noopener" class="title">{title}</a>
              </div>
            </div>"""

        days_html += f"""
        <div class="day-section">
          <div class="day-header">
            <span class="day-date">{date}</span>
            <span class="day-weekday">{weekday}</span>
            <span class="day-count">{len(arts)} articles</span>
          </div>
          <div class="day-articles">
            {rows}
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Energy Daily Top 20</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0a0c10; color: #d0d0d0; padding: 20px;
    max-width: 960px; margin: 0 auto;
  }}
  .header {{
    text-align: center; padding: 30px 0 20px; border-bottom: 1px solid #1e2130;
    margin-bottom: 24px;
  }}
  .header h1 {{ font-size: 24px; color: #fff; margin-bottom: 6px; }}
  .header .sub {{ color: #666; font-size: 13px; }}
  .header .stats {{
    display: flex; gap: 20px; justify-content: center; margin-top: 14px;
  }}
  .header .stat {{ text-align: center; }}
  .header .stat .n {{ font-size: 22px; font-weight: 700; color: #66bb6a; }}
  .header .stat .l {{ font-size: 11px; color: #666; }}

  .search-box {{
    width: 100%; padding: 10px 16px; border-radius: 10px;
    border: 1px solid #1e2130; background: #12141c; color: #fff;
    font-size: 14px; outline: none; margin-bottom: 20px;
  }}
  .search-box:focus {{ border-color: #66bb6a; }}

  .day-section {{ margin-bottom: 28px; }}
  .day-header {{
    display: flex; align-items: center; gap: 10px;
    padding: 10px 0; border-bottom: 2px solid #1a1d28; margin-bottom: 8px;
  }}
  .day-date {{ font-size: 18px; font-weight: 700; color: #fff; }}
  .day-weekday {{ font-size: 13px; color: #66bb6a; font-weight: 600; }}
  .day-count {{ font-size: 12px; color: #555; margin-left: auto; }}

  .article {{
    display: flex; gap: 12px; padding: 10px 8px;
    border-bottom: 1px solid #14161e; transition: background 0.15s;
  }}
  .article:hover {{ background: #14171f; }}
  .rank {{
    font-size: 13px; font-weight: 700; color: #333; min-width: 28px;
    padding-top: 4px; text-align: center;
  }}
  .article:nth-child(1) .rank {{ color: #ffd700; }}
  .article:nth-child(2) .rank {{ color: #c0c0c0; }}
  .article:nth-child(3) .rank {{ color: #cd7f32; }}

  .content {{ flex: 1; min-width: 0; }}
  .article-meta {{
    display: flex; align-items: center; gap: 8px; margin-bottom: 4px;
    flex-wrap: wrap;
  }}
  .cat-tag {{
    display: inline-block; padding: 1px 7px; border-radius: 10px;
    font-size: 10px; font-weight: 700; border: 1px solid;
  }}
  .source {{ font-size: 11px; color: #777; }}
  .score-wrap {{
    display: inline-flex; align-items: center; gap: 4px; margin-left: auto;
    background: #12141c; border-radius: 8px; padding: 2px 6px; min-width: 60px;
  }}
  .score-bar {{
    height: 4px; background: linear-gradient(90deg, #66bb6a, #29b6f6);
    border-radius: 2px; display: inline-block;
  }}
  .score-num {{ font-size: 10px; color: #66bb6a; font-weight: 600; }}

  .title {{
    color: #ccc; text-decoration: none; font-size: 14px; line-height: 1.4;
    display: block;
  }}
  .title:hover {{ color: #66bb6a; }}

  .footer {{
    text-align: center; padding: 20px; color: #333; font-size: 11px;
    border-top: 1px solid #1a1d28; margin-top: 20px;
  }}

  @media (max-width: 640px) {{
    body {{ padding: 12px; }}
    .day-date {{ font-size: 15px; }}
    .title {{ font-size: 13px; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>Energy Daily Top 20</h1>
  <div class="sub">Renewable / Hydrogen / Nuclear / Battery | International media | {now}</div>
  <div class="stats">
    <div class="stat"><div class="n">{total_selected}</div><div class="l">Selected</div></div>
    <div class="stat"><div class="n">{num_days}</div><div class="l">Days</div></div>
  </div>
</div>

<input type="text" class="search-box" placeholder="Search articles..." oninput="search(this.value)">

{days_html}

<div class="footer">
  Scored by energy relevance (70%) + source credibility (30%) | Refresh: python daily_energy.py
</div>

<script>
function search(q) {{
  q = q.toLowerCase();
  document.querySelectorAll('.day-section').forEach(sec => {{
    let anyVisible = false;
    sec.querySelectorAll('.article').forEach(art => {{
      const match = !q || art.textContent.toLowerCase().includes(q);
      art.style.display = match ? '' : 'none';
      if (match) anyVisible = true;
    }});
    sec.style.display = anyVisible ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""
    return html


if __name__ == '__main__':
    main()
