"""
HBF / Samsung / SK hynix / Dario Amodei 뉴스 수집기
- 해외 기술 전문 매체 중심 (한국 언론사 제외)
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
import requests
from urllib.parse import quote_plus, urlparse

# ── 설정 ──────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent
ARTICLES_JSON = OUTPUT_DIR / "articles.json"
REPORT_HTML = OUTPUT_DIR / "report.html"

START_DATE = datetime(2025, 1, 1)
END_DATE = datetime(2026, 6, 30)

# ── 한국 언론사 도메인 (차단) ──
BLOCKED_KOREAN_DOMAINS = {
    'chosun.com', 'chosunbiz.com', 'donga.com', 'hani.co.kr',
    'khan.co.kr', 'joongang.co.kr', 'joins.com', 'mk.co.kr',
    'hankyung.com', 'sedaily.com', 'etnews.com', 'zdnet.co.kr',
    'bloter.net', 'theelec.kr', 'thelec.net', 'yonhapnews.co.kr',
    'news1.kr', 'newsis.com', 'edaily.co.kr', 'mt.co.kr',
    'inews24.com', 'ddaily.co.kr', 'businesspost.co.kr',
    'daum.net', 'v.daum.net', 'naver.com', 'news.naver.com',
    'n.news.naver.com', 'kmib.co.kr', 'segye.com', 'munhwa.com',
    'hankookilbo.com', 'nocutnews.co.kr', 'yna.co.kr',
    'asiae.co.kr', 'fnnews.com', 'heraldcorp.com', 'dt.co.kr',
    'ajunews.com', 'aju.news', 'ajupress.com',
    'biz.chosun.com', 'news.chosun.com', 'biz.heraldcorp.com',
    'koreaherald.com', 'koreajoongangdaily.joins.com',
    'koreatimes.co.kr', 'koreabiomed.com', 'kinews.net',
    'theguru.co.kr', 'newspim.com', 'sisajournal.com',
    'businesskorea.co.kr', 'pulsenews.co.kr', 'theinvestor.co.kr',
}

# ── 검색 쿼리: (쿼리, 언어, 카테고리) ──
SEARCH_QUERIES = [
    # ── HBF ──
    ('HBF chip', 'en', 'hbf'),
    ('HBF memory', 'en', 'hbf'),
    ('HBF semiconductor', 'en', 'hbf'),
    ('HBF flash', 'en', 'hbf'),
    ('"High Bandwidth Flash"', 'en', 'hbf'),
    ('HBF SK hynix', 'en', 'hbf'),
    ('HBF Samsung', 'en', 'hbf'),
    ('HBF SanDisk', 'en', 'hbf'),
    ('HBF NAND', 'en', 'hbf'),
    ('HBF AI server', 'en', 'hbf'),
    ('HBF standard memory', 'en', 'hbf'),
    ('HBF inference', 'en', 'hbf'),
    # ── Samsung 반도체 ──
    ('Samsung semiconductor', 'en', 'samsung'),
    ('Samsung HBM', 'en', 'samsung'),
    ('Samsung NAND', 'en', 'samsung'),
    ('Samsung memory chip', 'en', 'samsung'),
    ('Samsung foundry', 'en', 'samsung'),
    ('Samsung chip AI', 'en', 'samsung'),
    ('Samsung Electronics semiconductor', 'en', 'samsung'),
    ('Samsung GAA chip', 'en', 'samsung'),
    ('Samsung 2nm', 'en', 'samsung'),
    ('Samsung DRAM', 'en', 'samsung'),
    # ── SK hynix ──
    ('SK hynix', 'en', 'skhynix'),
    ('SK hynix HBM', 'en', 'skhynix'),
    ('SK hynix NAND', 'en', 'skhynix'),
    ('SK hynix memory', 'en', 'skhynix'),
    ('SK hynix AI chip', 'en', 'skhynix'),
    ('SK hynix DRAM', 'en', 'skhynix'),
    ('SK hynix semiconductor', 'en', 'skhynix'),
    # ── Dario Amodei ──
    ('Dario Amodei', 'en', 'dario'),
    ('Dario Amodei AI', 'en', 'dario'),
    ('Dario Amodei Anthropic', 'en', 'dario'),
    ('Dario Amodei interview', 'en', 'dario'),
]

# ── 매체 신뢰도 (해외 기술 매체만) ──
TRUSTED_SOURCES = {
    # Tier 1: 글로벌 주요 비즈니스/금융
    'reuters.com': 1, 'bloomberg.com': 1, 'wsj.com': 1,
    'ft.com': 1, 'nytimes.com': 1, 'economist.com': 1,
    # Tier 2: 기술/반도체 전문
    'semiwiki.com': 2, 'semianalysis.com': 2, 'techinsights.com': 2,
    'anandtech.com': 2, 'tomshardware.com': 2, 'eetimes.com': 2,
    'techcrunch.com': 2, 'theverge.com': 2, 'arstechnica.com': 2,
    'wired.com': 2, 'ieee.org': 2, 'trendforce.com': 2,
    'digitimes.com': 2, 'blocksandfiles.com': 2, 'techpowerup.com': 2,
    'skhynix.com': 2, 'news.samsung.com': 2, 'semiconductor-today.com': 2,
    'eenewseurope.com': 2, 'eejournal.com': 2, 'nextplatform.com': 2,
    'hpcwire.com': 2, 'servethehome.com': 2,
    # Tier 3: 비즈니스/금융/일반 기술
    'cnbc.com': 3, 'bbc.com': 3, 'apnews.com': 3,
    'yahoo.com': 3, 'finance.yahoo.com': 3,
    'seekingalpha.com': 3, 'simplywall.st': 3,
    'barrons.com': 3, 'investopedia.com': 3,
    'zdnet.com': 3, 'cnet.com': 3, 'engadget.com': 3,
    'pcworld.com': 3, 'windowscentral.com': 3,
}

SOURCE_NAME_MAP = {
    'reuters.com': 'Reuters', 'bloomberg.com': 'Bloomberg',
    'wsj.com': 'WSJ', 'ft.com': 'Financial Times',
    'nytimes.com': 'NY Times', 'cnbc.com': 'CNBC',
    'techcrunch.com': 'TechCrunch', 'theverge.com': 'The Verge',
    'arstechnica.com': 'Ars Technica', 'wired.com': 'Wired',
    'tomshardware.com': "Tom's Hardware", 'anandtech.com': 'AnandTech',
    'eetimes.com': 'EE Times', 'trendforce.com': 'TrendForce',
    'digitimes.com': 'Digitimes', 'blocksandfiles.com': 'Blocks and Files',
    'semianalysis.com': 'SemiAnalysis', 'semiwiki.com': 'SemiWiki',
    'techinsights.com': 'TechInsights', 'techpowerup.com': 'TechPowerUp',
    'skhynix.com': 'SK hynix Newsroom',
    'news.samsung.com': 'Samsung Newsroom',
    'seekingalpha.com': 'Seeking Alpha',
    'simplywall.st': 'Simply Wall St',
    'ieee.org': 'IEEE', 'bbc.com': 'BBC',
    'nextplatform.com': 'The Next Platform',
    'hpcwire.com': 'HPCwire', 'servethehome.com': 'ServeTheHome',
    'eenewseurope.com': 'eeNews Europe',
    'zdnet.com': 'ZDNet', 'cnet.com': 'CNET',
    'barrons.com': "Barron's",
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# ── 카테고리 설정 ──
CATEGORY_CONFIG = {
    'hbf':     {'label': 'HBF',        'color': '#4fc3f7', 'filter_fn': 'contains_hbf'},
    'samsung': {'label': 'Samsung',    'color': '#1a73e8', 'filter_fn': 'contains_samsung'},
    'skhynix': {'label': 'SK hynix',   'color': '#ff6d00', 'filter_fn': 'contains_skhynix'},
    'dario':   {'label': 'Dario',      'color': '#e040fb', 'filter_fn': 'contains_dario'},
}


def is_korean_source(url):
    """한국 언론사 도메인인지 확인"""
    try:
        domain = urlparse(url).netloc.lower().replace('www.', '')
    except Exception:
        domain = url.lower().replace('www.', '')
    for blocked in BLOCKED_KOREAN_DOMAINS:
        if blocked in domain:
            return True
    # .co.kr, .kr 도메인도 기본 차단 (skhynix.com 등은 .com이라 통과)
    if domain.endswith('.kr'):
        return True
    return False


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
    return domain.split('.')[0].capitalize() if domain else 'Unknown'


def contains_hbf(text):
    upper = text.upper()
    return 'HBF' in upper or 'HIGH BANDWIDTH FLASH' in upper

def contains_samsung(text):
    return 'SAMSUNG' in text.upper()

def contains_skhynix(text):
    upper = text.upper()
    return 'SK HYNIX' in upper or 'SKHYNIX' in upper or 'SK하이닉스' in text

def contains_dario(text):
    upper = text.upper()
    return 'DARIO AMODEI' in upper or 'DARIO' in upper

FILTER_FNS = {
    'contains_hbf': contains_hbf,
    'contains_samsung': contains_samsung,
    'contains_skhynix': contains_skhynix,
    'contains_dario': contains_dario,
}


def fetch_google_news_rss(query, lang='en', category='hbf'):
    articles = []
    encoded_q = quote_plus(query)

    if lang == 'ko':
        url = f"https://news.google.com/rss/search?q={encoded_q}&hl=ko&gl=KR&ceid=KR:ko"
    else:
        url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en&gl=US&ceid=US:en"

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

                source_name = ''
                if hasattr(entry, 'source') and hasattr(entry.source, 'title'):
                    source_name = entry.source.title
                elif ' - ' in title:
                    source_name = title.rsplit(' - ', 1)[-1].strip()
                    title = title.rsplit(' - ', 1)[0].strip()

                articles.append({
                    'title': title,
                    'link': link,
                    'date': pub_date.strftime('%Y-%m-%d') if pub_date else '',
                    'source_name': source_name,
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
    print("  Tech News Collector (HBF / Samsung / SK hynix / Dario)")
    print(f"  {START_DATE.strftime('%Y-%m-%d')} ~ {END_DATE.strftime('%Y-%m-%d')}")
    print("  Korean media: EXCLUDED")
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

    # URL 추출 + 한국 언론 필터
    print("URL 추출 중...")
    enriched = []
    blocked = 0
    for i, art in enumerate(unique):
        if (i + 1) % 20 == 0 or i == 0:
            print(f"  [{i+1}/{len(unique)}]...")

        real_url = art['link']
        try:
            resp = requests.head(art['link'], headers=HEADERS, timeout=8, allow_redirects=True)
            if resp.url:
                real_url = resp.url
        except Exception:
            try:
                resp = requests.get(art['link'], headers=HEADERS, timeout=10, allow_redirects=True, stream=True)
                real_url = resp.url
                resp.close()
            except Exception:
                pass

        # 한국 언론사 차단
        if is_korean_source(real_url):
            blocked += 1
            continue

        art['real_url'] = real_url
        art['tier'] = get_source_tier(real_url)
        if not art['source_name']:
            art['source_name'] = get_source_name(real_url)

        enriched.append(art)
        time.sleep(0.15)

    enriched.sort(key=lambda x: (
        x.get('tier', 4),
        -(datetime.strptime(x['date'], '%Y-%m-%d').timestamp() if x.get('date') else 0)
    ))

    print(f"\n한국 언론 차단: {blocked}건")
    print(f"최종: {len(enriched)}건")

    # 카테고리별 카운트
    cat_counts = {}
    for a in enriched:
        c = a.get('category', 'hbf')
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
        c = a.get('category', 'hbf')
        cat_counts[c] = cat_counts.get(c, 0) + 1

    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    rows_html = ""
    for art in articles:
        tier = art.get('tier', 4)
        tier_labels = {1: 'Tier 1', 2: 'Tier 2', 3: 'Tier 3', 4: 'Other'}
        tier_label = tier_labels.get(tier, 'Other')
        tier_class = f"tier-{tier}"
        cat = art.get('category', 'hbf')
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

    # 카테고리 필터 버튼 생성
    cat_buttons = ""
    for cat_id, cfg in CATEGORY_CONFIG.items():
        cnt = cat_counts.get(cat_id, 0)
        cat_buttons += f'  <button class="filter-btn" onclick="setCatFilter(\'cat-{cat_id}\', this)" style="border-color:{cfg["color"]}44">{cfg["label"]} ({cnt})</button>\n'

    # 카테고리 stat 카드
    cat_stats = ""
    for cat_id, cfg in CATEGORY_CONFIG.items():
        cnt = cat_counts.get(cat_id, 0)
        cat_stats += f'  <div class="stat-card" style="border-color:{cfg["color"]}44"><div class="num" style="color:{cfg["color"]}">{cnt}</div><div class="label">{cfg["label"]}</div></div>\n'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tech News Collector</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
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
  .stat-card .num {{ font-size: 26px; font-weight: bold; color: #4fc3f7; }}
  .stat-card .label {{ font-size: 11px; color: #888; margin-top: 4px; }}
  .controls {{ display: flex; gap: 8px; margin: 20px 0; flex-wrap: wrap; align-items: center; }}
  .controls input {{
    flex: 1; min-width: 200px; padding: 10px 15px; border-radius: 8px;
    border: 1px solid #2a2d35; background: #1a1d27; color: #fff; font-size: 14px; outline: none;
  }}
  .controls input:focus {{ border-color: #4fc3f7; }}
  .filter-btn {{
    padding: 7px 14px; border-radius: 8px; border: 1px solid #2a2d35;
    background: #1a1d27; color: #ccc; cursor: pointer; font-size: 12px; transition: all 0.2s;
  }}
  .filter-btn:hover, .filter-btn.active {{ background: #4fc3f7; color: #000; border-color: #4fc3f7; }}
  .sep {{ color: #333; margin: 0 2px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; background: #1a1d27; border-radius: 10px; overflow: hidden; }}
  thead th {{
    background: #252830; padding: 11px 14px; text-align: left;
    font-size: 12px; color: #aaa; cursor: pointer; user-select: none;
    border-bottom: 2px solid #2a2d35; white-space: nowrap;
  }}
  thead th:hover {{ color: #4fc3f7; }}
  tbody td {{ padding: 9px 14px; border-bottom: 1px solid #22252d; font-size: 13px; }}
  tbody tr:hover {{ background: #22252d; }}
  a {{ color: #4fc3f7; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .tier-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 10px; font-weight: 600; white-space: nowrap;
  }}
  .tier-1 .tier-badge {{ background: #ffd70022; color: #ffd700; border: 1px solid #ffd70044; }}
  .tier-2 .tier-badge {{ background: #4fc3f722; color: #4fc3f7; border: 1px solid #4fc3f744; }}
  .tier-3 .tier-badge {{ background: #66bb6a22; color: #66bb6a; border: 1px solid #66bb6a44; }}
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
  <h1>Tech News Collector</h1>
  <div class="meta">
    HBF / Samsung / SK hynix / Dario Amodei | International tech media only | Updated: {now}
  </div>
</div>

<div class="stats">
  <div class="stat-card"><div class="num">{total}</div><div class="label">Total</div></div>
{cat_stats}
</div>

<div class="controls">
  <input type="text" id="searchBox" placeholder="Search articles..." oninput="filterTable()">
  <button class="filter-btn active" onclick="resetFilter(this)">All</button>
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
      <th onclick="sortTable(0)" style="width:100px">Date</th>
      <th onclick="sortTable(1)" style="width:80px">Tier</th>
      <th onclick="sortTable(2)" style="width:90px">Topic</th>
      <th onclick="sortTable(3)" style="width:140px">Source</th>
      <th onclick="sortTable(4)">Title</th>
    </tr>
  </thead>
  <tbody>
    {rows_html if rows_html else '<tr><td colspan="5" class="no-results">No articles found.</td></tr>'}
  </tbody>
</table>

<div class="footer">
  Tech News Collector | Refresh: python collect_hbf.py
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
