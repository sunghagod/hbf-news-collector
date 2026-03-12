"""
HBF 일별 Top 10 보고서 생성기
- articles.json에서 읽어서 HBF 제작/진전 유사도 + 신뢰도 점수 산출
- 날짜별 Top 10 기사만 추출
- 깔끔한 일별 타임라인 HTML 생성
"""

import json
import sys
import io
import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

OUTPUT_DIR = Path(__file__).parent
ARTICLES_JSON = OUTPUT_DIR / "articles.json"
REPORT_HTML = OUTPUT_DIR / "report_daily.html"

# ── HBF 제작/진전 유사도 키워드 (가중치) ──
# 핵심: HBF 칩 제작, 개발 진전, 표준화, 양산, 성능 관련
HBF_KEYWORDS = {
    # 최고 가중치 (5점) — HBF 직접 언급 + 제작/진전
    'HBF':                  5,
    'High Bandwidth Flash': 5,
    # 제작/생산 (4점)
    'mass production':  4, 'fabrication':    4, 'manufacturing':  4,
    'production':       3, 'prototype':      4, 'sample':         4,
    'tape-out':         4, 'tape out':       4, 'yield':          4,
    'wafer':            3, 'fab':            3, 'pilot line':     4,
    # 개발 진전 (3점)
    'development':      3, 'progress':       3, 'breakthrough':   4,
    'milestone':        4, 'unveil':         3, 'announce':       2,
    'launch':           3, 'release':        2, 'demo':           3,
    'architecture':     3, 'design':         2, 'specification':  3,
    # 표준화/협력 (3점)
    'standardization':  4, 'standard':       3, 'consortium':     3,
    'alliance':         3, 'partnership':    3, 'collaboration':  3,
    'joint':            2, 'specification':  3, 'JEDEC':          4,
    # 기술 성능 (3점)
    'bandwidth':        3, 'performance':    2, 'latency':        2,
    'throughput':       3, 'GB/s':           3, 'TB/s':           3,
    'inference':        3, 'AI server':      2, 'data center':    2,
    # 관련 기술 (2점)
    'NAND':     2, 'flash':    2, 'SSD':     1, '3D NAND':  2,
    'stacking': 3, 'TSV':      3, 'HBM':     1, 'CXL':      2,
    'memory':   1, 'chip':     1, 'semiconductor': 1,
    # 회사 (1점)
    'SK hynix': 2, 'Samsung':  1, 'SanDisk':  2, 'Kioxia':   2,
    'Micron':   1, 'NVIDIA':   1, 'Western Digital': 1,
}

# Dario Amodei 키워드 (별도 점수)
DARIO_KEYWORDS = {
    'Dario Amodei':  5, 'Dario':  3, 'Anthropic': 2,
    'Claude':        2, 'AGI':    2, 'AI safety': 2,
}

# 한국 매체 차단 (URL/소스명 기반)
KOREAN_INDICATORS = [
    '.co.kr', '.kr/', 'chosun', 'joongang', 'joins.com', 'donga',
    'hankyung', 'mk.co', 'sedaily', 'etnews', 'hani.co', 'khan.co',
    'yonhap', 'newsis', 'news1', 'edaily', 'bloter', 'theelec',
    'daum.net', 'naver.com', 'ajupress', 'aju.news', 'asiae',
    'heraldcorp', 'koreaherald', 'koreatimes', 'koreabiomed',
    'businesskorea', 'pulsenews', 'theinvestor', 'korea',
    'kmib', 'nocutnews', 'fnnews', 'newspim', 'sisajournal',
    'dt.co.kr', 'inews24', 'ddaily', 'businesspost', 'mt.co.kr',
    '조선', '중앙', '동아', '한겨레', '경향', '매일경제', '한국경제',
    '연합', '전자신문', 'zdnet.co.kr',
]


def is_korean(art):
    """한국 매체 기사인지 확인"""
    check = (
        (art.get('real_url', '') + ' ' +
         art.get('source_name', '') + ' ' +
         art.get('link', '')).lower()
    )
    return any(k in check for k in KOREAN_INDICATORS)


def calc_relevance_score(title, category):
    """HBF 제작/진전 유사도 점수 계산"""
    upper = title.upper()
    score = 0

    if category == 'dario':
        # 다리오 기사는 별도 점수
        for kw, weight in DARIO_KEYWORDS.items():
            if kw.upper() in upper:
                score += weight
        return score

    # HBF 관련 점수
    for kw, weight in HBF_KEYWORDS.items():
        if kw.upper() in upper:
            score += weight

    # HBF가 제목에 직접 있으면 보너스
    if 'HBF' in upper or 'HIGH BANDWIDTH FLASH' in upper:
        score += 10

    # 제작/진전 관련 단어가 있으면 보너스
    progress_words = ['PRODUCTION', 'PROTOTYPE', 'SAMPLE', 'MASS PROD',
                      'FABRICAT', 'MANUFACTUR', 'BREAKTHROUGH', 'MILESTONE',
                      'STANDARD', 'UNVEIL', 'LAUNCH', 'TAPE-OUT', 'TAPE OUT']
    for w in progress_words:
        if w in upper:
            score += 3

    return score


def calc_tier_score(tier):
    """신뢰도 점수 (높을수록 좋음)"""
    return {1: 10, 2: 7, 3: 4, 4: 1}.get(tier, 1)


def main():
    with open(ARTICLES_JSON, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    print(f"원본: {len(articles)}건")

    # 1. 한국 매체 제외
    articles = [a for a in articles if not is_korean(a)]
    print(f"한국 매체 제외 후: {len(articles)}건")

    # 2. 점수 계산
    for art in articles:
        rel_score = calc_relevance_score(art['title'], art.get('category', 'hbf'))
        tier_score = calc_tier_score(art.get('tier', 4))
        # 총점 = 유사도(70%) + 신뢰도(30%)
        art['relevance'] = rel_score
        art['tier_score'] = tier_score
        art['total_score'] = round(rel_score * 0.7 + tier_score * 0.3, 1)

    # 3. 날짜별 그룹핑 → Top 10
    by_date = defaultdict(list)
    for art in articles:
        d = art.get('date', '')
        if d:
            by_date[d].append(art)

    # 각 날짜별 점수순 정렬 → Top 20
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

    # 상위 5일 미리보기
    for date in sorted(daily_top.keys(), reverse=True)[:5]:
        print(f"\n--- {date} ---")
        for i, a in enumerate(daily_top[date][:3]):
            print(f"  {i+1}. [{a['total_score']}점] {a['title'][:70]}")

    # 4. HTML 생성
    html = generate_daily_html(daily_top, total_selected)
    with open(REPORT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"\n저장: {REPORT_HTML}")
    print(f"완료!")


def generate_daily_html(daily_top, total_selected):
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    num_days = len(daily_top)

    # 날짜별 섹션 HTML
    days_html = ""
    for date in sorted(daily_top.keys(), reverse=True):
        arts = daily_top[date]
        if not arts:
            continue

        # 요일 계산
        try:
            dt = datetime.strptime(date, '%Y-%m-%d')
            weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            weekday = weekdays[dt.weekday()]
        except Exception:
            weekday = ''

        rows = ""
        for i, art in enumerate(arts):
            tier = art.get('tier', 4)
            tier_class = f"t{tier}"
            cat = art.get('category', 'hbf')
            cat_labels = {'hbf': 'HBF', 'samsung': 'Samsung', 'skhynix': 'SK hynix', 'dario': 'Dario'}
            cat_colors = {'hbf': '#4fc3f7', 'samsung': '#1a73e8', 'skhynix': '#ff6d00', 'dario': '#e040fb'}
            cat_label = cat_labels.get(cat, cat)
            cat_color = cat_colors.get(cat, '#888')

            score = art.get('total_score', 0)
            source = (art.get('source_name', '') or '').replace('&', '&amp;').replace('<', '&lt;')
            title = art.get('title', '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            url = art.get('real_url', art.get('link', '#'))

            # 스코어 바 (최대 30점 기준)
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
<title>HBF Daily Top 20</title>
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
  .header .stat .n {{ font-size: 22px; font-weight: 700; color: #4fc3f7; }}
  .header .stat .l {{ font-size: 11px; color: #666; }}

  .search-box {{
    width: 100%; padding: 10px 16px; border-radius: 10px;
    border: 1px solid #1e2130; background: #12141c; color: #fff;
    font-size: 14px; outline: none; margin-bottom: 20px;
  }}
  .search-box:focus {{ border-color: #4fc3f7; }}

  .day-section {{ margin-bottom: 28px; }}
  .day-header {{
    display: flex; align-items: center; gap: 10px;
    padding: 10px 0; border-bottom: 2px solid #1a1d28; margin-bottom: 8px;
  }}
  .day-date {{ font-size: 18px; font-weight: 700; color: #fff; }}
  .day-weekday {{ font-size: 13px; color: #4fc3f7; font-weight: 600; }}
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
    height: 4px; background: linear-gradient(90deg, #4fc3f7, #00e676);
    border-radius: 2px; display: inline-block;
  }}
  .score-num {{ font-size: 10px; color: #4fc3f7; font-weight: 600; }}

  .title {{
    color: #ccc; text-decoration: none; font-size: 14px; line-height: 1.4;
    display: block;
  }}
  .title:hover {{ color: #4fc3f7; }}

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
  <h1>HBF Daily Top 20</h1>
  <div class="sub">HBF chip development & progress | International tech media | {now}</div>
  <div class="stats">
    <div class="stat"><div class="n">{total_selected}</div><div class="l">Selected</div></div>
    <div class="stat"><div class="n">{num_days}</div><div class="l">Days</div></div>
  </div>
</div>

<input type="text" class="search-box" placeholder="Search articles..." oninput="search(this.value)">

{days_html}

<div class="footer">
  Scored by HBF relevance (70%) + source credibility (30%) | Refresh: python daily_top10.py
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
