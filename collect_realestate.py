"""
국내 부동산 뉴스 수집기
- Google News RSS 한국어 검색
- 카테고리: 정책/규제, 시장/시세, 분양/청약, 금리/대출, 재건축/재개발
- 출력: interactive HTML 보고서
"""

import json
import sys
import io
import time
import hashlib
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import feedparser
import re
from urllib.parse import quote_plus, urlparse

# ── 설정 ──────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent
ARTICLES_JSON = OUTPUT_DIR / "articles_realestate.json"
REPORT_HTML = OUTPUT_DIR / "report_realestate.html"

START_DATE = datetime(2025, 1, 1)
END_DATE = datetime(2026, 6, 30)

# ── 검색 쿼리: (쿼리, 언어, 카테고리) ──
SEARCH_QUERIES = [
    # ── 정책/규제 ──
    ('부동산 정책', 'ko', 'policy'),
    ('부동산 규제', 'ko', 'policy'),
    ('부동산 대책', 'ko', 'policy'),
    ('주택 정책', 'ko', 'policy'),
    ('부동산 세금', 'ko', 'policy'),
    ('종부세', 'ko', 'policy'),
    ('양도세 부동산', 'ko', 'policy'),
    ('취득세 부동산', 'ko', 'policy'),
    ('다주택자 규제', 'ko', 'policy'),
    ('투기과열지구', 'ko', 'policy'),
    ('조정대상지역', 'ko', 'policy'),
    # ── 시장/시세 ──
    ('아파트 매매가', 'ko', 'market'),
    ('아파트 시세', 'ko', 'market'),
    ('부동산 시장 전망', 'ko', 'market'),
    ('아파트 가격 상승', 'ko', 'market'),
    ('아파트 가격 하락', 'ko', 'market'),
    ('서울 아파트', 'ko', 'market'),
    ('수도권 부동산', 'ko', 'market'),
    ('부동산 거래량', 'ko', 'market'),
    ('전세 시세', 'ko', 'market'),
    ('전세가율', 'ko', 'market'),
    ('매매 거래', 'ko', 'market'),
    # ── 분양/청약 ──
    ('아파트 분양', 'ko', 'subscription'),
    ('청약 경쟁률', 'ko', 'subscription'),
    ('분양가 상한제', 'ko', 'subscription'),
    ('무순위 청약', 'ko', 'subscription'),
    ('특별공급', 'ko', 'subscription'),
    ('사전청약', 'ko', 'subscription'),
    ('분양권', 'ko', 'subscription'),
    ('모델하우스', 'ko', 'subscription'),
    # ── 금리/대출 ──
    ('주택담보대출 금리', 'ko', 'finance'),
    ('주담대 금리', 'ko', 'finance'),
    ('부동산 대출 규제', 'ko', 'finance'),
    ('DSR 규제', 'ko', 'finance'),
    ('LTV DTI', 'ko', 'finance'),
    ('전세대출', 'ko', 'finance'),
    ('주택담보대출', 'ko', 'finance'),
    ('스트레스 DSR', 'ko', 'finance'),
    # ── 재건축/재개발 ──
    ('재건축', 'ko', 'redevelop'),
    ('재개발', 'ko', 'redevelop'),
    ('정비사업', 'ko', 'redevelop'),
    ('재건축 초과이익', 'ko', 'redevelop'),
    ('안전진단', 'ko', 'redevelop'),
    ('도시정비', 'ko', 'redevelop'),
    ('리모델링 아파트', 'ko', 'redevelop'),
]

# ── 카테고리 설정 ──
CATEGORY_CONFIG = {
    'policy':       {'label': '정책/규제',     'color': '#ef5350', 'filter_fn': 'contains_policy'},
    'market':       {'label': '시장/시세',     'color': '#42a5f5', 'filter_fn': 'contains_market'},
    'subscription': {'label': '분양/청약',     'color': '#66bb6a', 'filter_fn': 'contains_subscription'},
    'finance':      {'label': '금리/대출',     'color': '#ffa726', 'filter_fn': 'contains_finance'},
    'redevelop':    {'label': '재건축/재개발', 'color': '#ab47bc', 'filter_fn': 'contains_redevelop'},
}

# ── 매체 신뢰도 ──
TRUSTED_SOURCES = {
    # Tier 1: 주요 경제지/통신사
    'mk.co.kr': 1, 'hankyung.com': 1, 'sedaily.com': 1,
    'edaily.co.kr': 1, 'mt.co.kr': 1, 'fnnews.com': 1,
    'yonhapnews.co.kr': 1, 'yna.co.kr': 1,
    'reuters.com': 1, 'bloomberg.com': 1,
    # Tier 2: 종합일간지/부동산 전문
    'chosun.com': 2, 'chosunbiz.com': 2,
    'joongang.co.kr': 2, 'joins.com': 2,
    'donga.com': 2, 'hani.co.kr': 2, 'khan.co.kr': 2,
    'kmib.co.kr': 2, 'segye.com': 2, 'munhwa.com': 2,
    'hankookilbo.com': 2, 'heraldcorp.com': 2,
    'asiae.co.kr': 2, 'ajunews.com': 2,
    'newsis.com': 2, 'news1.kr': 2,
    'nocutnews.co.kr': 2,
    'dt.co.kr': 2, 'inews24.com': 2,
    # Tier 3: 부동산/경제 전문 매체
    'realtyprime.co.kr': 3, 'serve.co.kr': 3,
    'housingherald.co.kr': 3, 'apt2you.com': 3,
    'land.naver.com': 3, 'newspim.com': 3,
    'businesspost.co.kr': 3, 'ddaily.co.kr': 3,
    'theguru.co.kr': 3, 'sisajournal.com': 3,
    'naver.com': 3, 'news.naver.com': 3,
    'daum.net': 3, 'v.daum.net': 3,
}

SOURCE_NAME_MAP = {
    'mk.co.kr': '매일경제', 'hankyung.com': '한국경제', 'sedaily.com': '서울경제',
    'edaily.co.kr': '이데일리', 'mt.co.kr': '머니투데이', 'fnnews.com': '파이낸셜뉴스',
    'yonhapnews.co.kr': '연합뉴스', 'yna.co.kr': '연합뉴스',
    'chosun.com': '조선일보', 'chosunbiz.com': '조선비즈',
    'joongang.co.kr': '중앙일보', 'joins.com': '중앙일보',
    'donga.com': '동아일보', 'hani.co.kr': '한겨레', 'khan.co.kr': '경향신문',
    'kmib.co.kr': '국민일보', 'segye.com': '세계일보', 'munhwa.com': '문화일보',
    'hankookilbo.com': '한국일보', 'heraldcorp.com': '헤럴드경제',
    'asiae.co.kr': '아시아경제', 'ajunews.com': '아주경제',
    'newsis.com': '뉴시스', 'news1.kr': '뉴스1',
    'nocutnews.co.kr': 'CBS노컷뉴스',
    'dt.co.kr': '디지털타임스', 'inews24.com': '아이뉴스24',
    'newspim.com': '뉴스핌', 'businesspost.co.kr': '비즈니스포스트',
    'ddaily.co.kr': '디지털데일리', 'theguru.co.kr': '더구루',
    'sisajournal.com': '시사저널',
    'naver.com': '네이버뉴스', 'news.naver.com': '네이버뉴스',
    'daum.net': '다음뉴스', 'v.daum.net': '다음뉴스',
    'reuters.com': 'Reuters', 'bloomberg.com': 'Bloomberg',
}


def get_source_tier(url):
    domain = url.lower().replace('www.', '')
    if '://' in domain:
        try:
            domain = urlparse(domain).netloc.lower().replace('www.', '')
        except Exception:
            pass
    for d, tier in TRUSTED_SOURCES.items():
        if d in domain:
            return tier
    return 4


def get_source_name(url):
    domain = url.lower().replace('www.', '')
    if '://' in domain:
        try:
            domain = urlparse(domain).netloc.lower().replace('www.', '')
        except Exception:
            pass
    for d, name in SOURCE_NAME_MAP.items():
        if d in domain:
            return name
    return domain.split('.')[0] if domain else 'Unknown'


# ── 노이즈 필터 ──
NOISE_PATTERNS = re.compile(
    r'광고|제보|포토|영상|움짤|'
    r'오늘의 운세|별자리|날씨|'
    r'사진으로 보는|갤러리|'
    r'쇼핑|할인|쿠폰',
    re.IGNORECASE
)


def is_noise_article(title):
    return bool(NOISE_PATTERNS.search(title))


# ── 카테고리 필터 함수 ──
def contains_policy(text):
    keywords = ['정책', '규제', '대책', '세금', '종부세', '양도세', '취득세',
                '다주택', '투기', '조정대상', '토지거래허가', '부동산법',
                '임대차', '전월세', '국토부', '국토교통부']
    return any(k in text for k in keywords)

def contains_market(text):
    keywords = ['매매가', '시세', '시장', '가격', '상승', '하락', '거래량',
                '전세', '전셋값', '매매', '호가', '실거래', '아파트값',
                '집값', '부동산 전망', '매물']
    return any(k in text for k in keywords)

def contains_subscription(text):
    keywords = ['분양', '청약', '경쟁률', '분양가', '상한제', '무순위',
                '특별공급', '사전청약', '분양권', '모델하우스', '입주',
                '당첨', '공급', '미분양']
    return any(k in text for k in keywords)

def contains_finance(text):
    keywords = ['금리', '대출', '주담대', 'DSR', 'LTV', 'DTI',
                '담보대출', '전세대출', '이자', '모기지', '스트레스',
                '가계부채', '신용대출']
    return any(k in text for k in keywords)

def contains_redevelop(text):
    keywords = ['재건축', '재개발', '정비사업', '초과이익', '안전진단',
                '도시정비', '리모델링', '조합', '관리처분', '사업시행',
                '철거', '이주', '착공']
    return any(k in text for k in keywords)

FILTER_FNS = {
    'contains_policy': contains_policy,
    'contains_market': contains_market,
    'contains_subscription': contains_subscription,
    'contains_finance': contains_finance,
    'contains_redevelop': contains_redevelop,
}


def fetch_google_news_rss(query, lang='ko', category='market'):
    articles = []
    encoded_q = quote_plus(query)
    url = f"https://news.google.com/rss/search?q={encoded_q}&hl=ko&gl=KR&ceid=KR:ko"

    filter_fn = FILTER_FNS.get(CATEGORY_CONFIG[category]['filter_fn'])

    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            try:
                pub_date = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6])
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_date = datetime(*entry.updated_parsed[:6])

                if pub_date and (pub_date < START_DATE or pub_date > END_DATE):
                    continue

                title = entry.get('title', '')
                link = entry.get('link', '')
                summary = entry.get('summary', '')
                combined = f"{title} {summary}"

                if filter_fn and not filter_fn(combined):
                    continue

                if is_noise_article(title):
                    continue

                source_name = ''
                source_href = ''
                if hasattr(entry, 'source'):
                    if hasattr(entry.source, 'title'):
                        source_name = entry.source.title
                    if hasattr(entry.source, 'href'):
                        source_href = entry.source.href
                if not source_name and ' - ' in title:
                    source_name = title.rsplit(' - ', 1)[-1].strip()
                    title = title.rsplit(' - ', 1)[0].strip()

                articles.append({
                    'title': title,
                    'link': link,
                    'date': pub_date.strftime('%Y-%m-%d') if pub_date else '',
                    'source_name': source_name,
                    'source_href': source_href,
                    'query': query,
                    'lang': lang,
                    'category': category,
                })
            except Exception:
                continue
    except Exception as e:
        print(f"  [!] RSS fail ({query}): {e}")

    return articles


def main():
    print("=" * 60)
    print("  부동산 뉴스 수집기")
    print("  정책/규제 | 시장/시세 | 분양/청약 | 금리/대출 | 재건축/재개발")
    print(f"  {START_DATE.strftime('%Y-%m-%d')} ~ {END_DATE.strftime('%Y-%m-%d')}")
    print("=" * 60)

    all_articles = []
    for query, lang, category in SEARCH_QUERIES:
        label = CATEGORY_CONFIG[category]['label']
        print(f"\n[{label}] \"{query}\" ({lang})")
        articles = fetch_google_news_rss(query, lang=lang, category=category)
        print(f"   -> {len(articles)}건")
        all_articles.extend(articles)
        time.sleep(0.5)

    print(f"\n총 수집: {len(all_articles)}건 (중복 포함)")

    # 중복 제거
    seen = set()
    unique = []
    for art in all_articles:
        h = hashlib.md5(art['title'].strip().lower().encode()).hexdigest()[:16]
        if h not in seen:
            seen.add(h)
            unique.append(art)
    print(f"중복 제거: {len(unique)}건")

    # source_href 기반 Tier 매핑
    enriched = []
    for art in unique:
        source_href = art.get('source_href', '')
        art['real_url'] = art['link']
        art['tier'] = get_source_tier(source_href) if source_href else 4
        if not art['source_name'] and source_href:
            art['source_name'] = get_source_name(source_href)
        enriched.append(art)

    enriched.sort(key=lambda x: (
        x.get('tier', 4),
        -(datetime.strptime(x['date'], '%Y-%m-%d').timestamp() if x.get('date') else 0)
    ))

    print(f"최종: {len(enriched)}건")

    # 카테고리별 카운트
    cat_counts = {}
    for a in enriched:
        c = a.get('category', 'market')
        cat_counts[c] = cat_counts.get(c, 0) + 1
    for cat, cnt in cat_counts.items():
        print(f"  {CATEGORY_CONFIG[cat]['label']}: {cnt}건")

    # JSON 저장
    with open(ARTICLES_JSON, 'w', encoding='utf-8') as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    # HTML 생성
    html = generate_html(enriched)
    with open(REPORT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"\n저장: {REPORT_HTML}")
    print(f"완료! {len(enriched)}건 수집")


def generate_html(articles):
    total = len(articles)
    tier_counts = {}
    cat_counts = {}
    for a in articles:
        t = a.get('tier', 4)
        tier_counts[t] = tier_counts.get(t, 0) + 1
        c = a.get('category', 'market')
        cat_counts[c] = cat_counts.get(c, 0) + 1

    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    rows_html = ""
    for art in articles:
        tier = art.get('tier', 4)
        tier_labels = {1: 'Tier 1', 2: 'Tier 2', 3: 'Tier 3', 4: 'Other'}
        tier_label = tier_labels.get(tier, 'Other')
        tier_class = f"tier-{tier}"
        cat = art.get('category', 'market')
        cat_class = f"cat-{cat}"
        cat_color = CATEGORY_CONFIG.get(cat, {}).get('color', '#888')
        cat_label = CATEGORY_CONFIG.get(cat, {}).get('label', cat)

        date_str = art.get('date', '-')
        source = (art.get('source_name', '-') or '-').replace('&', '&amp;').replace('<', '&lt;')
        title = art.get('title', '-').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        url = art.get('real_url', art.get('link', '#'))

        rows_html += f"""
        <tr class="{tier_class} {cat_class}">
            <td>{date_str}</td>
            <td><span class="tier-badge {tier_class}">{tier_label}</span></td>
            <td><span class="cat-badge" style="background:{cat_color}22;color:{cat_color};border:1px solid {cat_color}44">{cat_label}</span></td>
            <td>{source}</td>
            <td><a href="{url}" target="_blank" rel="noopener">{title}</a></td>
        </tr>"""

    cat_buttons = ""
    for cat_id, cfg in CATEGORY_CONFIG.items():
        cnt = cat_counts.get(cat_id, 0)
        cat_buttons += f'  <button class="filter-btn" onclick="setCatFilter(\'cat-{cat_id}\', this)" style="border-color:{cfg["color"]}44">{cfg["label"]} ({cnt})</button>\n'

    cat_stats = ""
    for cat_id, cfg in CATEGORY_CONFIG.items():
        cnt = cat_counts.get(cat_id, 0)
        cat_stats += f'  <div class="stat-card" style="border-color:{cfg["color"]}44"><div class="num" style="color:{cfg["color"]}">{cnt}</div><div class="label">{cfg["label"]}</div></div>\n'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>부동산 뉴스 수집기</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans KR', sans-serif;
    background: #0f1117; color: #e0e0e0; padding: 20px;
  }}
  .header {{ text-align: center; padding: 30px 0; border-bottom: 1px solid #2a2d35; margin-bottom: 20px; }}
  .header h1 {{ font-size: 26px; color: #fff; margin-bottom: 8px; }}
  .header .meta {{ color: #888; font-size: 13px; }}
  .stats {{ display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; margin: 20px 0; }}
  .stat-card {{
    background: #1a1d27; border: 1px solid #2a2d35; border-radius: 10px;
    padding: 14px 22px; text-align: center; min-width: 100px;
  }}
  .stat-card .num {{ font-size: 26px; font-weight: bold; color: #ef5350; }}
  .stat-card .label {{ font-size: 11px; color: #888; margin-top: 4px; }}
  .controls {{ display: flex; gap: 8px; margin: 20px 0; flex-wrap: wrap; align-items: center; }}
  .controls input {{
    flex: 1; min-width: 200px; padding: 10px 15px; border-radius: 8px;
    border: 1px solid #2a2d35; background: #1a1d27; color: #fff; font-size: 14px; outline: none;
  }}
  .controls input:focus {{ border-color: #ef5350; }}
  .filter-btn {{
    padding: 7px 14px; border-radius: 8px; border: 1px solid #2a2d35;
    background: #1a1d27; color: #ccc; cursor: pointer; font-size: 12px; transition: all 0.2s;
  }}
  .filter-btn:hover, .filter-btn.active {{ background: #ef5350; color: #fff; border-color: #ef5350; }}
  .sep {{ color: #333; margin: 0 2px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; background: #1a1d27; border-radius: 10px; overflow: hidden; }}
  thead th {{
    background: #252830; padding: 11px 14px; text-align: left;
    font-size: 12px; color: #aaa; cursor: pointer; user-select: none;
    border-bottom: 2px solid #2a2d35; white-space: nowrap;
  }}
  thead th:hover {{ color: #ef5350; }}
  tbody td {{ padding: 9px 14px; border-bottom: 1px solid #22252d; font-size: 13px; }}
  tbody tr:hover {{ background: #22252d; }}
  a {{ color: #ef5350; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .tier-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 10px; font-weight: 600; white-space: nowrap;
  }}
  .tier-1 .tier-badge {{ background: #ffd70022; color: #ffd700; border: 1px solid #ffd70044; }}
  .tier-2 .tier-badge {{ background: #ef535022; color: #ef5350; border: 1px solid #ef535044; }}
  .tier-3 .tier-badge {{ background: #42a5f522; color: #42a5f5; border: 1px solid #42a5f544; }}
  .tier-4 .tier-badge {{ background: #88888822; color: #888; border: 1px solid #88888844; }}
  .cat-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 10px; font-weight: 700; white-space: nowrap;
  }}
  .no-results {{ text-align: center; padding: 40px; color: #666; font-size: 16px; }}
  .footer {{ text-align: center; padding: 20px; color: #555; font-size: 11px; margin-top: 20px; }}
  @media (max-width: 768px) {{
    body {{ padding: 10px; }}
    .stat-card {{ padding: 10px 12px; min-width: 70px; }}
    .stat-card .num {{ font-size: 18px; }}
    thead th, tbody td {{ padding: 7px 8px; font-size: 12px; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>부동산 뉴스 수집기</h1>
  <div class="meta">
    정책/규제 | 시장/시세 | 분양/청약 | 금리/대출 | 재건축/재개발 | 업데이트: {now}
  </div>
</div>

<div class="stats">
  <div class="stat-card"><div class="num">{total}</div><div class="label">전체</div></div>
{cat_stats}
</div>

<div class="controls">
  <input type="text" id="searchBox" placeholder="기사 검색..." oninput="filterTable()">
  <button class="filter-btn active" onclick="resetFilter(this)">전체</button>
  <span class="sep">|</span>
  <button class="filter-btn" onclick="setTierFilter('tier-1', this)">Tier 1</button>
  <button class="filter-btn" onclick="setTierFilter('tier-2', this)">Tier 2</button>
  <button class="filter-btn" onclick="setTierFilter('tier-3', this)">Tier 3</button>
  <span class="sep">|</span>
{cat_buttons}
</div>

<table id="newsTable">
  <thead>
    <tr>
      <th onclick="sortTable(0)" style="width:100px">날짜</th>
      <th onclick="sortTable(1)" style="width:80px">등급</th>
      <th onclick="sortTable(2)" style="width:110px">분류</th>
      <th onclick="sortTable(3)" style="width:140px">매체</th>
      <th onclick="sortTable(4)">제목</th>
    </tr>
  </thead>
  <tbody>
    {rows_html if rows_html else '<tr><td colspan="5" class="no-results">수집된 기사가 없습니다.</td></tr>'}
  </tbody>
</table>

<div class="footer">
  부동산 뉴스 수집기 | 새로고침: python collect_realestate.py
</div>

<script>
let currentFilter = 'all';
let sortCol = -1, sortAsc = true;

function resetFilter(btn) {{
  currentFilter = 'all';
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  filterTable();
}}
function setTierFilter(tier, btn) {{
  currentFilter = tier;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  filterTable();
}}
function setCatFilter(cat, btn) {{
  currentFilter = cat;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  filterTable();
}}
function filterTable() {{
  const q = document.getElementById('searchBox').value.toLowerCase();
  document.querySelectorAll('#newsTable tbody tr').forEach(row => {{
    const text = row.textContent.toLowerCase();
    const matchSearch = !q || text.includes(q);
    const matchFilter = currentFilter === 'all' || row.classList.contains(currentFilter);
    row.style.display = (matchSearch && matchFilter) ? '' : 'none';
  }});
}}
function sortTable(col) {{
  const tbody = document.querySelector('#newsTable tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  if (sortCol === col) sortAsc = !sortAsc;
  else {{ sortCol = col; sortAsc = true; }}
  rows.sort((a, b) => {{
    const aV = a.cells[col]?.textContent || '';
    const bV = b.cells[col]?.textContent || '';
    return sortAsc ? aV.localeCompare(bV) : bV.localeCompare(aV);
  }});
  rows.forEach(r => tbody.appendChild(r));
}}
</script>
</body>
</html>"""
    return html


if __name__ == '__main__':
    main()
