"""
부동산 일별 Top 20 보고서 생성기
- articles_realestate.json에서 읽어서 부동산 유사도 + 신뢰도 점수 산출
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
ARTICLES_JSON = OUTPUT_DIR / "articles_realestate.json"
REPORT_HTML = OUTPUT_DIR / "report_realestate_daily.html"

# ── 부동산 키워드 (가중치) ──
REALESTATE_KEYWORDS = {
    # 정책/규제 (5점)
    '부동산 대책': 5, '규제 완화': 5, '규제 강화': 5,
    '종부세': 4, '양도세': 4, '취득세': 4, '재산세': 3,
    '다주택자': 4, '투기과열': 5, '조정대상': 5,
    '토지거래허가': 5, '임대차': 4, '전월세상한': 5,
    '국토교통부': 3, '국토부': 3,
    # 시장/시세 (4점)
    '매매가': 4, '시세': 3, '실거래가': 4,
    '상승': 3, '하락': 3, '급등': 5, '급락': 5,
    '거래량': 4, '신고가': 5, '신저가': 5,
    '전세가': 4, '전셋값': 4, '집값': 3, '아파트값': 3,
    '호가': 3, '매물': 3,
    # 분양/청약 (4점)
    '분양': 3, '청약': 4, '경쟁률': 5,
    '분양가': 4, '상한제': 5, '무순위': 5,
    '특별공급': 4, '사전청약': 4, '미분양': 5,
    '입주': 3, '당첨': 4, '모델하우스': 3,
    # 금리/대출 (4점)
    '금리': 4, '대출': 3, '주담대': 5,
    'DSR': 5, 'LTV': 4, 'DTI': 4,
    '가계부채': 4, '모기지': 3,
    '스트레스 DSR': 5,
    # 재건축/재개발 (4점)
    '재건축': 4, '재개발': 4, '정비사업': 4,
    '초과이익': 5, '안전진단': 5, '도시정비': 4,
    '리모델링': 3, '관리처분': 5, '사업시행': 4,
    # 보너스
    '서울': 2, '강남': 3, '수도권': 2,
    '신도시': 3, 'GTX': 4, '3기 신도시': 5,
    '전망': 2, '예측': 2,
}

CATEGORY_CONFIG = {
    'policy':       {'label': '정책/규제',     'color': '#ef5350'},
    'market':       {'label': '시장/시세',     'color': '#42a5f5'},
    'subscription': {'label': '분양/청약',     'color': '#66bb6a'},
    'finance':      {'label': '금리/대출',     'color': '#ffa726'},
    'redevelop':    {'label': '재건축/재개발', 'color': '#ab47bc'},
}


def calc_relevance_score(title):
    score = 0
    for kw, weight in REALESTATE_KEYWORDS.items():
        if kw in title:
            score += weight
    return score


def calc_tier_score(tier):
    return {1: 10, 2: 7, 3: 4, 4: 1}.get(tier, 1)


def main():
    with open(ARTICLES_JSON, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    print(f"원본: {len(articles)}건")

    # Tier 1~3만
    articles = [a for a in articles if a.get('tier', 4) <= 3]
    print(f"Tier 1~3만 필터: {len(articles)}건")

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
            weekdays = ['월', '화', '수', '목', '금', '토', '일']
            weekday = weekdays[dt.weekday()]
        except Exception:
            weekday = ''

        rows = ""
        for i, art in enumerate(arts):
            cat = art.get('category', 'market')
            cat_label = CATEGORY_CONFIG.get(cat, {}).get('label', cat)
            cat_color = CATEGORY_CONFIG.get(cat, {}).get('color', '#888')

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
            <span class="day-weekday">{weekday}요일</span>
            <span class="day-count">{len(arts)}건</span>
          </div>
          <div class="day-articles">
            {rows}
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>부동산 Daily Top 20</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans KR', sans-serif;
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
  .header .stat .n {{ font-size: 22px; font-weight: 700; color: #ef5350; }}
  .header .stat .l {{ font-size: 11px; color: #666; }}

  .search-box {{
    width: 100%; padding: 10px 16px; border-radius: 10px;
    border: 1px solid #1e2130; background: #12141c; color: #fff;
    font-size: 14px; outline: none; margin-bottom: 20px;
  }}
  .search-box:focus {{ border-color: #ef5350; }}

  .day-section {{ margin-bottom: 28px; }}
  .day-header {{
    display: flex; align-items: center; gap: 10px;
    padding: 10px 0; border-bottom: 2px solid #1a1d28; margin-bottom: 8px;
  }}
  .day-date {{ font-size: 18px; font-weight: 700; color: #fff; }}
  .day-weekday {{ font-size: 13px; color: #ef5350; font-weight: 600; }}
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
    height: 4px; background: linear-gradient(90deg, #ef5350, #ffa726);
    border-radius: 2px; display: inline-block;
  }}
  .score-num {{ font-size: 10px; color: #ef5350; font-weight: 600; }}

  .title {{
    color: #ccc; text-decoration: none; font-size: 14px; line-height: 1.4;
    display: block;
  }}
  .title:hover {{ color: #ef5350; }}

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
  <h1>부동산 Daily Top 20</h1>
  <div class="sub">정책/규제 | 시장/시세 | 분양/청약 | 금리/대출 | 재건축/재개발 | {now}</div>
  <div class="stats">
    <div class="stat"><div class="n">{total_selected}</div><div class="l">선별</div></div>
    <div class="stat"><div class="n">{num_days}</div><div class="l">일수</div></div>
  </div>
</div>

<input type="text" class="search-box" placeholder="기사 검색..." oninput="search(this.value)">

{days_html}

<div class="footer">
  부동산 유사도(70%) + 매체 신뢰도(30%) 기준 | 새로고침: python daily_realestate.py
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
