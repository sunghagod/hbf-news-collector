"""
국제정세 뉴스 수집기
- 외교 / 안보·군사 / 무역·제재 / 분쟁·갈등
- 해외 주요 매체 중심 (한국 언론사 제외)
- 출력: articles_geopolitics.json + interactive HTML 보고서
"""

import json
import sys
import io
import time
import hashlib
import re
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import feedparser
from urllib.parse import quote_plus, urlparse

# ── 설정 ──────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent
ARTICLES_JSON = OUTPUT_DIR / "articles_geopolitics.json"
REPORT_HTML = OUTPUT_DIR / "report_geopolitics.html"

START_DATE = datetime(2025, 1, 1)
END_DATE = datetime(2026, 12, 31)

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
    # ── 외교 (Diplomacy) ──
    ('US China relations', 'en', 'diplomacy'),
    ('US foreign policy', 'en', 'diplomacy'),
    ('diplomatic summit', 'en', 'diplomacy'),
    ('G7 summit', 'en', 'diplomacy'),
    ('G20 summit', 'en', 'diplomacy'),
    ('United Nations diplomacy', 'en', 'diplomacy'),
    ('EU foreign policy', 'en', 'diplomacy'),
    ('BRICS alliance', 'en', 'diplomacy'),
    ('Middle East diplomacy', 'en', 'diplomacy'),
    ('NATO alliance', 'en', 'diplomacy'),
    ('Indo-Pacific strategy', 'en', 'diplomacy'),
    # ── 안보·군사 (Security) ──
    ('military buildup', 'en', 'security'),
    ('defense spending', 'en', 'security'),
    ('nuclear weapons proliferation', 'en', 'security'),
    ('missile defense', 'en', 'security'),
    ('cyber warfare', 'en', 'security'),
    ('South China Sea', 'en', 'security'),
    ('Taiwan strait', 'en', 'security'),
    ('North Korea missile', 'en', 'security'),
    ('arms deal', 'en', 'security'),
    ('NATO military', 'en', 'security'),
    # ── 무역·제재 (Trade) ──
    ('trade war tariffs', 'en', 'trade'),
    ('economic sanctions', 'en', 'trade'),
    ('US tariffs China', 'en', 'trade'),
    ('export controls chips', 'en', 'trade'),
    ('supply chain decoupling', 'en', 'trade'),
    ('trade agreement', 'en', 'trade'),
    ('WTO dispute', 'en', 'trade'),
    ('rare earth export', 'en', 'trade'),
    ('oil sanctions', 'en', 'trade'),
    ('technology export ban', 'en', 'trade'),
    # ── 분쟁·갈등 (Conflict) ──
    ('Ukraine Russia war', 'en', 'conflict'),
    ('Israel Hamas conflict', 'en', 'conflict'),
    ('Gaza ceasefire', 'en', 'conflict'),
    ('geopolitical crisis', 'en', 'conflict'),
    ('territorial dispute', 'en', 'conflict'),
    ('civil war conflict', 'en', 'conflict'),
    ('refugee crisis', 'en', 'conflict'),
    ('peace negotiations', 'en', 'conflict'),
]

# ── 매체 신뢰도 ──
TRUSTED_SOURCES = {
    # Tier 1: 핵심 — 국제 뉴스 통신/경제지
    'reuters.com': 1, 'bloomberg.com': 1,
    'apnews.com': 1, 'bbc.com': 1,
    'wsj.com': 1, 'ft.com': 1,
    'nytimes.com': 1, 'washingtonpost.com': 1,
    'economist.com': 1,
    # Tier 2: 외교·안보 전문
    'foreignaffairs.com': 2, 'foreignpolicy.com': 2,
    'cfr.org': 2, 'brookings.edu': 2,
    'csis.org': 2, 'rand.org': 2,
    'chathamhouse.org': 2, 'iiss.org': 2,
    'aljazeera.com': 2, 'france24.com': 2,
    'dw.com': 2, 'scmp.com': 2,
    'politico.com': 2, 'politico.eu': 2,
    'thehill.com': 2, 'defense.gov': 2,
    'defensenews.com': 2, 'janes.com': 2,
    # Tier 3: 보조 비즈니스/일반
    'cnbc.com': 3, 'cnn.com': 3,
    'theguardian.com': 3, 'independent.co.uk': 3,
    'nbcnews.com': 3, 'abcnews.go.com': 3,
    'cbsnews.com': 3, 'axios.com': 3,
    'theatlantic.com': 3, 'vox.com': 3,
    'euronews.com': 3, 'time.com': 3,
    'newsweek.com': 3, 'usnews.com': 3,
    'yahoo.com': 3, 'finance.yahoo.com': 3,
}

SOURCE_NAME_MAP = {
    'reuters.com': 'Reuters', 'bloomberg.com': 'Bloomberg',
    'apnews.com': 'AP News', 'bbc.com': 'BBC',
    'wsj.com': 'WSJ', 'ft.com': 'Financial Times',
    'nytimes.com': 'NY Times', 'washingtonpost.com': 'Washington Post',
    'economist.com': 'The Economist',
    'foreignaffairs.com': 'Foreign Affairs',
    'foreignpolicy.com': 'Foreign Policy',
    'cfr.org': 'CFR', 'brookings.edu': 'Brookings',
    'csis.org': 'CSIS', 'rand.org': 'RAND',
    'chathamhouse.org': 'Chatham House',
    'aljazeera.com': 'Al Jazeera', 'france24.com': 'France 24',
    'dw.com': 'DW', 'scmp.com': 'SCMP',
    'politico.com': 'Politico', 'politico.eu': 'Politico EU',
    'thehill.com': 'The Hill',
    'defensenews.com': 'Defense News', 'janes.com': "Jane's",
    'cnbc.com': 'CNBC', 'cnn.com': 'CNN',
    'theguardian.com': 'The Guardian',
    'axios.com': 'Axios', 'theatlantic.com': 'The Atlantic',
    'euronews.com': 'Euronews', 'time.com': 'TIME',
    'newsweek.com': 'Newsweek',
}

# ── 카테고리 설정 ──
CATEGORY_CONFIG = {
    'diplomacy': {'label': 'Diplomacy',  'color': '#42a5f5', 'filter_fn': 'contains_diplomacy'},
    'security':  {'label': 'Security',   'color': '#ef5350', 'filter_fn': 'contains_security'},
    'trade':     {'label': 'Trade',      'color': '#ffa726', 'filter_fn': 'contains_trade'},
    'conflict':  {'label': 'Conflict',   'color': '#ab47bc', 'filter_fn': 'contains_conflict'},
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


# ── 노이즈 필터 ──
NOISE_PATTERNS = re.compile(
    r'black friday|cyber monday|shopping editor|'
    r'gift guide|gifts? for (him|her|dad|mom|kids|men|women)|'
    r'coupon code|promo code|discount code|'
    r'\bbest .{0,15} to buy\b|'
    r'\bgifts? under \$|'
    r'horoscope|zodiac|celebrity|gossip|entertainment|sports score',
    re.IGNORECASE
)


def is_noise_article(title):
    return bool(NOISE_PATTERNS.search(title))


def contains_diplomacy(text):
    upper = text.upper()
    keywords = ['DIPLOMACY', 'DIPLOMATIC', 'SUMMIT', 'FOREIGN POLICY',
                'AMBASSADOR', 'BILATERAL', 'MULTILATERAL', 'ALLIANCE',
                'NATO', 'G7', 'G20', 'BRICS', 'UNITED NATIONS', 'UN ',
                'INDO-PACIFIC', 'EU FOREIGN']
    return any(k in upper for k in keywords)


def contains_security(text):
    upper = text.upper()
    keywords = ['MILITARY', 'DEFENSE', 'DEFENCE', 'MISSILE', 'NUCLEAR WEAPON',
                'CYBER ATTACK', 'CYBER WAR', 'ARMS DEAL', 'WEAPONS',
                'SOUTH CHINA SEA', 'TAIWAN STRAIT', 'NORTH KOREA',
                'PENTAGON', 'ARMY', 'NAVY', 'AIR FORCE', 'TROOPS']
    return any(k in upper for k in keywords)


def contains_trade(text):
    upper = text.upper()
    keywords = ['TARIFF', 'SANCTION', 'TRADE WAR', 'EXPORT CONTROL',
                'SUPPLY CHAIN', 'DECOUPLING', 'TRADE AGREEMENT', 'WTO',
                'RARE EARTH', 'EMBARGO', 'TRADE DEAL', 'TRADE DEFICIT',
                'IMPORT BAN', 'EXPORT BAN']
    return any(k in upper for k in keywords)


def contains_conflict(text):
    upper = text.upper()
    keywords = ['WAR ', 'CONFLICT', 'CEASEFIRE', 'INVASION', 'CRISIS',
                'TERRITORIAL DISPUTE', 'CIVIL WAR', 'REFUGEE',
                'PEACE NEGOTIATION', 'PEACE DEAL', 'AIRSTRIKE',
                'CASUALTIES', 'HUMANITARIAN', 'OCCUPATION']
    return any(k in upper for k in keywords)


FILTER_FNS = {
    'contains_diplomacy': contains_diplomacy,
    'contains_security': contains_security,
    'contains_trade': contains_trade,
    'contains_conflict': contains_conflict,
}


def fetch_google_news_rss(query, lang='en', category='diplomacy'):
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
    print("  Geopolitics News Collector")
    print("  Diplomacy / Security / Trade / Conflict")
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

    # source_href 기반 필터링
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
        c = a.get('category', 'diplomacy')
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
        c = a.get('category', 'diplomacy')
        cat_counts[c] = cat_counts.get(c, 0) + 1

    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    rows_html = ""
    for art in articles:
        tier = art.get('tier', 4)
        tier_labels = {1: 'Tier 1', 2: 'Tier 2', 3: 'Tier 3', 4: 'Other'}
        tier_label = tier_labels.get(tier, 'Other')
        tier_class = f"tier-{tier}"
        cat = art.get('category', 'diplomacy')
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
<title>Geopolitics News Collector</title>
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
  .stat-card {{ background: #1a1d27; border-radius: 8px; padding: 16px 24px; text-align: center; border-left: 3px solid; }}
  .stat-card .num {{ font-size: 28px; font-weight: 700; }}
  .stat-card .label {{ font-size: 12px; color: #888; margin-top: 4px; }}
  .filters {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; margin: 16px 0; }}
  .filter-btn {{ background: #1a1d27; border: 1px solid #333; color: #ccc; padding: 6px 14px; border-radius: 16px; cursor: pointer; font-size: 13px; }}
  .filter-btn:hover {{ background: #252830; }}
  .filter-btn.active {{ background: #2a3040; color: #fff; border-color: #667; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
  th {{ text-align: left; padding: 10px 12px; background: #1a1d27; color: #999; font-size: 12px; border-bottom: 1px solid #333; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #1e2028; font-size: 13px; }}
  tr:hover {{ background: #1a1d27; }}
  a {{ color: #7eb8ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .tier-badge {{ font-size: 11px; padding: 2px 8px; border-radius: 10px; }}
  .tier-1 {{ background: #ffd70033; color: #ffd700; }}
  .tier-2 {{ background: #66bb6a33; color: #66bb6a; }}
  .tier-3 {{ background: #42a5f533; color: #42a5f5; }}
  .tier-4 {{ background: #88888833; color: #888; }}
  .cat-badge {{ font-size: 11px; padding: 2px 8px; border-radius: 10px; }}
  .hidden {{ display: none; }}
</style>
</head>
<body>
<div class="header">
  <h1>Geopolitics News</h1>
  <div class="meta">Generated: {now} | Total: {total} articles</div>
</div>
<div class="stats">
  <div class="stat-card" style="border-color:#fff3"><div class="num" style="color:#fff">{total}</div><div class="label">Total</div></div>
  {cat_stats}
</div>
<div class="filters">
  <button class="filter-btn active" onclick="setCatFilter('all', this)">All ({total})</button>
  {cat_buttons}
</div>
<table>
<thead><tr><th>Date</th><th>Tier</th><th>Topic</th><th>Source</th><th>Title</th></tr></thead>
<tbody>{rows_html}
</tbody>
</table>
<script>
let currentCat = 'all';
function setCatFilter(cat, btn) {{
  currentCat = cat;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('tbody tr').forEach(row => {{
    row.classList.toggle('hidden', cat !== 'all' && !row.classList.contains(cat));
  }});
}}
</script>
</body>
</html>"""
    return html


if __name__ == '__main__':
    main()
