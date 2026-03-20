"""
에너지 뉴스 수집기
- 재생에너지 / 수소 / 원자력 / 배터리·ESS
- 해외 기술·에너지 전문 매체 중심 (한국 언론사 제외)
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
from urllib.parse import quote_plus, urlparse

# ── 설정 ──────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent
ARTICLES_JSON = OUTPUT_DIR / "articles_energy.json"
REPORT_HTML = OUTPUT_DIR / "report_energy.html"

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
    # ── 재생에너지 (Solar / Wind) ──
    ('solar energy', 'en', 'renewable'),
    ('solar power plant', 'en', 'renewable'),
    ('solar panel market', 'en', 'renewable'),
    ('photovoltaic', 'en', 'renewable'),
    ('wind energy', 'en', 'renewable'),
    ('offshore wind farm', 'en', 'renewable'),
    ('onshore wind power', 'en', 'renewable'),
    ('renewable energy investment', 'en', 'renewable'),
    ('renewable energy policy', 'en', 'renewable'),
    ('clean energy transition', 'en', 'renewable'),
    # ── 수소 / 연료전지 ──
    ('hydrogen energy', 'en', 'hydrogen'),
    ('green hydrogen', 'en', 'hydrogen'),
    ('blue hydrogen', 'en', 'hydrogen'),
    ('hydrogen fuel cell', 'en', 'hydrogen'),
    ('hydrogen electrolyzer', 'en', 'hydrogen'),
    ('hydrogen storage', 'en', 'hydrogen'),
    ('hydrogen infrastructure', 'en', 'hydrogen'),
    ('ammonia fuel', 'en', 'hydrogen'),
    # ── 원자력 ──
    ('nuclear energy', 'en', 'nuclear'),
    ('nuclear power plant', 'en', 'nuclear'),
    ('small modular reactor', 'en', 'nuclear'),
    ('SMR nuclear', 'en', 'nuclear'),
    ('nuclear fusion', 'en', 'nuclear'),
    ('nuclear reactor', 'en', 'nuclear'),
    ('uranium market', 'en', 'nuclear'),
    ('nuclear renaissance', 'en', 'nuclear'),
    # ── 배터리 / ESS ──
    ('battery energy storage', 'en', 'battery'),
    ('lithium ion battery', 'en', 'battery'),
    ('solid state battery', 'en', 'battery'),
    ('ESS energy storage system', 'en', 'battery'),
    ('grid scale battery', 'en', 'battery'),
    ('EV battery', 'en', 'battery'),
    ('sodium ion battery', 'en', 'battery'),
    ('CATL battery', 'en', 'battery'),
    ('LG Energy Solution', 'en', 'battery'),
    ('battery gigafactory', 'en', 'battery'),
]

# ── 매체 신뢰도 (Tier 4 미등록 매체는 Discord/보고서에서 제외) ──
TRUSTED_SOURCES = {
    # Tier 1: 핵심 — 에너지 시장 동향 + 지정학
    'bloomberg.com': 1, 'reuters.com': 1,
    'yahoo.com': 1, 'finance.yahoo.com': 1,
    'wsj.com': 1, 'ft.com': 1,
    'spglobal.com': 1, 'woodmac.com': 1,
    'iea.org': 1, 'irena.org': 1,
    # Tier 2: 에너지/원자재 전문
    'utilitydive.com': 2, 'energymonitor.ai': 2,
    'pv-magazine.com': 2, 'pv-tech.org': 2,
    'windpowermonthly.com': 2, 'rechargenews.com': 2,
    'hydrogeninsight.com': 2, 'h2-view.com': 2,
    'world-nuclear-news.org': 2, 'ans.org': 2,
    'energy-storage.news': 2, 'electrek.co': 2,
    'canarymedia.com': 2, 'energyvoice.com': 2,
    'cleanenergywire.org': 2, 'carbonbrief.org': 2,
    'oilprice.com': 2, 'rigzone.com': 2,
    'energy.gov': 2, 'greentechmedia.com': 2,
    # Tier 3: 보조 비즈니스/기술
    'cnbc.com': 3, 'nytimes.com': 3, 'economist.com': 3,
    'seekingalpha.com': 3, 'barrons.com': 3,
    'bbc.com': 3, 'apnews.com': 3,
    'arstechnica.com': 3, 'techcrunch.com': 3,
}

SOURCE_NAME_MAP = {
    'reuters.com': 'Reuters', 'bloomberg.com': 'Bloomberg',
    'wsj.com': 'WSJ', 'ft.com': 'Financial Times',
    'nytimes.com': 'NY Times', 'cnbc.com': 'CNBC',
    'iea.org': 'IEA', 'irena.org': 'IRENA',
    'utilitydive.com': 'Utility Dive',
    'pv-magazine.com': 'PV Magazine', 'pv-tech.org': 'PV Tech',
    'windpowermonthly.com': 'Windpower Monthly',
    'rechargenews.com': 'Recharge News',
    'hydrogeninsight.com': 'Hydrogen Insight',
    'h2-view.com': 'H2 View',
    'world-nuclear-news.org': 'World Nuclear News',
    'energy-storage.news': 'Energy Storage News',
    'electrek.co': 'Electrek',
    'canarymedia.com': 'Canary Media',
    'cleanenergywire.org': 'Clean Energy Wire',
    'carbonbrief.org': 'Carbon Brief',
    'spglobal.com': 'S&P Global',
    'woodmac.com': 'Wood Mackenzie',
    'greentechmedia.com': 'Greentech Media',
    'energyvoice.com': 'Energy Voice',
    'techcrunch.com': 'TechCrunch',
    'arstechnica.com': 'Ars Technica',
    'theverge.com': 'The Verge', 'wired.com': 'Wired',
    'seekingalpha.com': 'Seeking Alpha',
    'barrons.com': "Barron's", 'bbc.com': 'BBC',
}

# ── 카테고리 설정 ──
CATEGORY_CONFIG = {
    'renewable': {'label': 'Renewable',  'color': '#66bb6a', 'filter_fn': 'contains_renewable'},
    'hydrogen':  {'label': 'Hydrogen',   'color': '#29b6f6', 'filter_fn': 'contains_hydrogen'},
    'nuclear':   {'label': 'Nuclear',    'color': '#ffa726', 'filter_fn': 'contains_nuclear'},
    'battery':   {'label': 'Battery',    'color': '#ab47bc', 'filter_fn': 'contains_battery'},
}


def is_korean_source(url):
    try:
        domain = urlparse(url).netloc.lower().replace('www.', '')
    except Exception:
        domain = url.lower().replace('www.', '')
    for blocked in BLOCKED_KOREAN_DOMAINS:
        if blocked in domain:
            return True
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


import re

# ── 쇼핑/선물(gift)/소비자 기사 필터 ──
NOISE_PATTERNS = re.compile(
    r'black friday|cyber monday|shopping editor|stocking up on|'
    r'gift guide|gifts? for (him|her|dad|mom|kids|men|women)|'
    r'birthday gift|valentine.{0,5} gift|christmas gift|holiday gift|'
    r'coupon code|promo code|discount code|'
    r'\bbest .{0,15} to buy\b|'
    r'\bgifts? under \$',
    re.IGNORECASE
)


def is_noise_article(title):
    """쇼핑/선물(present) 등 에너지와 무관한 소비자 기사 필터"""
    return bool(NOISE_PATTERNS.search(title))


def contains_renewable(text):
    upper = text.upper()
    keywords = ['SOLAR', 'WIND ENERGY', 'WIND FARM', 'WIND POWER',
                'PHOTOVOLTAIC', 'RENEWABLE', 'CLEAN ENERGY']
    return any(k in upper for k in keywords)

def contains_hydrogen(text):
    upper = text.upper()
    keywords = ['HYDROGEN', 'FUEL CELL', 'ELECTROLYZER', 'AMMONIA FUEL',
                'GREEN H2', 'BLUE H2']
    return any(k in upper for k in keywords)

def contains_nuclear(text):
    upper = text.upper()
    keywords = ['NUCLEAR', 'SMR', 'SMALL MODULAR REACTOR', 'FUSION',
                'URANIUM', 'FISSION']
    return any(k in upper for k in keywords)

def contains_battery(text):
    upper = text.upper()
    keywords = ['BATTERY', 'ESS', 'ENERGY STORAGE', 'LITHIUM',
                'SOLID STATE', 'SODIUM ION', 'CATL', 'LG ENERGY',
                'GIGAFACTORY']
    return any(k in upper for k in keywords)

FILTER_FNS = {
    'contains_renewable': contains_renewable,
    'contains_hydrogen': contains_hydrogen,
    'contains_nuclear': contains_nuclear,
    'contains_battery': contains_battery,
}


def fetch_google_news_rss(query, lang='en', category='renewable'):
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
    print("  Energy News Collector")
    print("  Renewable / Hydrogen / Nuclear / Battery·ESS")
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

    # source_href 기반 필터링 (HTTP 요청 없이 빠르게 처리)
    print(f"출처 필터링 중... ({len(unique)}건)")

    enriched = []
    blocked = 0
    for art in unique:
        source_href = art.get('source_href', '')
        if source_href and is_korean_source(source_href):
            blocked += 1
            continue
        art['real_url'] = art['link']
        art['tier'] = get_source_tier(source_href) if source_href else 4
        if not art['source_name'] and source_href:
            art['source_name'] = get_source_name(source_href)
        enriched.append(art)

    enriched.sort(key=lambda x: (
        x.get('tier', 4),
        -(datetime.strptime(x['date'], '%Y-%m-%d').timestamp() if x.get('date') else 0)
    ))

    print(f"\n한국 언론 차단: {blocked}건")
    print(f"최종: {len(enriched)}건")

    cat_counts = {}
    for a in enriched:
        c = a.get('category', 'renewable')
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
        c = a.get('category', 'renewable')
        cat_counts[c] = cat_counts.get(c, 0) + 1

    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    rows_html = ""
    for art in articles:
        tier = art.get('tier', 4)
        tier_labels = {1: 'Tier 1', 2: 'Tier 2', 3: 'Tier 3', 4: 'Other'}
        tier_label = tier_labels.get(tier, 'Other')
        tier_class = f"tier-{tier}"
        cat = art.get('category', 'renewable')
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
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Energy News Collector</title>
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
  .stat-card .num {{ font-size: 26px; font-weight: bold; color: #66bb6a; }}
  .stat-card .label {{ font-size: 11px; color: #888; margin-top: 4px; }}
  .controls {{ display: flex; gap: 8px; margin: 20px 0; flex-wrap: wrap; align-items: center; }}
  .controls input {{
    flex: 1; min-width: 200px; padding: 10px 15px; border-radius: 8px;
    border: 1px solid #2a2d35; background: #1a1d27; color: #fff; font-size: 14px; outline: none;
  }}
  .controls input:focus {{ border-color: #66bb6a; }}
  .filter-btn {{
    padding: 7px 14px; border-radius: 8px; border: 1px solid #2a2d35;
    background: #1a1d27; color: #ccc; cursor: pointer; font-size: 12px; transition: all 0.2s;
  }}
  .filter-btn:hover, .filter-btn.active {{ background: #66bb6a; color: #000; border-color: #66bb6a; }}
  .sep {{ color: #333; margin: 0 2px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; background: #1a1d27; border-radius: 10px; overflow: hidden; }}
  thead th {{
    background: #252830; padding: 11px 14px; text-align: left;
    font-size: 12px; color: #aaa; cursor: pointer; user-select: none;
    border-bottom: 2px solid #2a2d35; white-space: nowrap;
  }}
  thead th:hover {{ color: #66bb6a; }}
  tbody td {{ padding: 9px 14px; border-bottom: 1px solid #22252d; font-size: 13px; }}
  tbody tr:hover {{ background: #22252d; }}
  a {{ color: #66bb6a; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .tier-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 10px; font-weight: 600; white-space: nowrap;
  }}
  .tier-1 .tier-badge {{ background: #ffd70022; color: #ffd700; border: 1px solid #ffd70044; }}
  .tier-2 .tier-badge {{ background: #66bb6a22; color: #66bb6a; border: 1px solid #66bb6a44; }}
  .tier-3 .tier-badge {{ background: #29b6f622; color: #29b6f6; border: 1px solid #29b6f644; }}
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
  <h1>Energy News Collector</h1>
  <div class="meta">
    Renewable / Hydrogen / Nuclear / Battery·ESS | International media only | Updated: {now}
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
  Energy News Collector | Refresh: python collect_energy.py
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
