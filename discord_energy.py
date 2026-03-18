"""
Discord 웹훅으로 Energy Daily Top 20 전송
- 본문 추출 성공한 기사만 순위 포함 (실패 시 차순위로 대체)
- Playwright로 URL 변환 → newspaper4k 본문 추출 → 한국어 번역/요약
- edge-tts로 요약 음성 생성 → Discord 음성 파일 전송
- 전부 무료
"""

import json
import sys
import io
import os
import time
import asyncio
import hashlib
import requests
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from deep_translator import GoogleTranslator
from newspaper import Article
from playwright.sync_api import sync_playwright
import edge_tts

OUTPUT_DIR = Path(__file__).parent
ARTICLES_JSON = OUTPUT_DIR / "articles_energy.json"
SENT_HISTORY = OUTPUT_DIR / "sent_history_energy.json"
AUDIO_DIR = OUTPUT_DIR / "audio"
AUDIO_DIR.mkdir(exist_ok=True)

# ── Discord 웹훅 URL (환경변수 또는 직접 입력) ──
WEBHOOK_URL = os.environ.get(
    "DISCORD_ENERGY_WEBHOOK_URL",
    "https://discordapp.com/api/webhooks/1483817944164335766/4lKHXcfIBPPeq-IMzqfjOIl8VZ9fjxsW-1Mv-6KnIZ-CguHPXKoZ18nOIPCeQJ1f5-H_"
)

TTS_VOICE = "ko-KR-SunHiNeural"

KOREAN_INDICATORS = [
    '.co.kr', '.kr/', 'chosun', 'joongang', 'joins.com', 'donga',
    'hankyung', 'mk.co', 'sedaily', 'etnews', 'hani.co', 'khan.co',
    'yonhap', 'newsis', 'news1', 'edaily', 'bloter', 'theelec',
    'daum.net', 'naver.com', 'ajupress', 'aju.news', 'asiae',
    'heraldcorp', 'koreaherald', 'koreatimes', 'koreabiomed',
    'businesskorea', 'pulsenews', 'theinvestor', 'korea',
    'kmib', 'nocutnews', 'fnnews', 'newspim', 'dt.co.kr',
    'inews24', 'ddaily', 'businesspost', 'mt.co.kr', 'zdnet.co.kr',
]

ENERGY_KEYWORDS = {
    'SOLAR': 3, 'PHOTOVOLTAIC': 4, 'WIND FARM': 4, 'WIND ENERGY': 4,
    'OFFSHORE WIND': 5, 'RENEWABLE': 3, 'CLEAN ENERGY': 3,
    'HYDROGEN': 4, 'GREEN HYDROGEN': 5, 'FUEL CELL': 4,
    'ELECTROLYZER': 5, 'AMMONIA': 3,
    'NUCLEAR': 3, 'SMR': 5, 'FUSION': 5, 'URANIUM': 3,
    'BATTERY': 3, 'LITHIUM': 3, 'SOLID STATE': 5,
    'ESS': 4, 'ENERGY STORAGE': 4, 'GIGAFACTORY': 4,
    'INVESTMENT': 3, 'GW': 3, 'MW': 2,
    'BREAKTHROUGH': 4, 'MILESTONE': 4, 'RECORD': 3,
    'MASS PRODUCTION': 4, 'COMMERCIALIZATION': 4,
}

# ── 번역 시 원문 유지할 고유명사 ──
PROPER_NOUNS = [
    # 회사/조직
    'NextEra Energy', 'Enel', 'Iberdrola', 'Orsted', 'Vestas',
    'Siemens Gamesa', 'Siemens Energy', 'First Solar', 'SunPower',
    'Canadian Solar', 'JA Solar', 'LONGi', 'Trina Solar', 'JinkoSolar',
    'Plug Power', 'Bloom Energy', 'Nel ASA', 'ITM Power',
    'Air Liquide', 'Linde', 'Hyzon Motors',
    'CATL', 'BYD', 'LG Energy Solution', 'Samsung SDI', 'SK On',
    'Panasonic', 'Tesla', 'QuantumScape', 'Solid Power', 'LGES',
    'EDF', 'Westinghouse', 'NuScale', 'Rolls-Royce SMR',
    'Cameco', 'Kazatomprom', 'TerraPower', 'X-energy',
    'Commonwealth Fusion', 'Helion Energy', 'TAE Technologies',
    'General Electric', 'GE Vernova', 'Fluence', 'Northvolt',
    'IEA', 'IRENA', 'IAEA', 'DOE', 'EPA', 'FERC',
    'Goldman Sachs', 'Morgan Stanley', 'JP Morgan', 'BloombergNEF',
    'Wood Mackenzie', 'S&P Global', 'Rystad Energy',
    # 인물
    'Elon Musk', 'Bill Gates',
    # 기술 용어
    'GW', 'MW', 'GWh', 'MWh', 'kWh', 'TWh',
    'PV', 'PERC', 'TOPCon', 'HJT', 'IBC',
    'PEMFC', 'SOFC', 'PEM', 'ALK',
    'PWR', 'BWR', 'SMR', 'MSR', 'HTGR',
    'NMC', 'LFP', 'NCA', 'LMFP',
    'ESS', 'BESS', 'V2G', 'VPP',
    'LCOE', 'PPA', 'REC', 'ITC', 'PTC',
    'CCS', 'CCUS', 'DAC',
    'AI', 'EV', 'HVDC', 'AC', 'DC',
    'IRA', 'Inflation Reduction Act',
    'Net Zero', 'Paris Agreement',
]

translator = GoogleTranslator(source='en', target='ko')


def load_sent_history():
    if SENT_HISTORY.exists():
        try:
            with open(SENT_HISTORY, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_sent_history(sent_set):
    with open(SENT_HISTORY, 'w', encoding='utf-8') as f:
        json.dump(sorted(sent_set), f, ensure_ascii=False)


def article_hash(art):
    title = art.get('title', '').strip().lower()
    return hashlib.md5(title.encode()).hexdigest()[:16]


def protect_proper_nouns(text):
    sorted_nouns = sorted(PROPER_NOUNS, key=len, reverse=True)
    replacements = []
    for noun in sorted_nouns:
        if noun in text:
            placeholder = f"__PN{len(replacements):03d}__"
            text = text.replace(noun, placeholder)
            replacements.append((placeholder, noun))
    return text, replacements


def restore_proper_nouns(text, replacements):
    for placeholder, noun in replacements:
        text = text.replace(placeholder, noun)
    return text


def is_korean(art):
    check = (art.get('real_url', '') + ' ' + art.get('source_name', '') + ' ' + art.get('link', '')).lower()
    return any(k in check for k in KOREAN_INDICATORS)


def calc_total(art):
    upper = art['title'].upper()
    score = 0
    for kw, w in ENERGY_KEYWORDS.items():
        if kw in upper:
            score += w
    tier_s = {1: 10, 2: 7, 3: 4, 4: 1}.get(art.get('tier', 4), 1)
    return round(score * 0.7 + tier_s * 0.3, 1)


def translate_text(text):
    if not text:
        return ''
    try:
        if len(text) > 4500:
            text = text[:4500]
        protected, replacements = protect_proper_nouns(text)
        translated = translator.translate(protected)
        result = restore_proper_nouns(translated, replacements)
        return result
    except Exception:
        return text


def resolve_urls_playwright(articles):
    resolved = {}
    google_arts = [a for a in articles if 'news.google.com' in a.get('link', '')]
    if not google_arts:
        return resolved

    print(f"  Playwright: {len(google_arts)}개 URL 변환...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for art in google_arts:
                link = art['link']
                try:
                    page.goto(link, wait_until='domcontentloaded', timeout=12000)
                    page.wait_for_timeout(2000)
                    final = page.url
                    if 'news.google.com' not in final:
                        resolved[link] = final
                except Exception:
                    pass
            browser.close()
    except Exception as e:
        print(f"  Playwright error: {e}")

    print(f"  변환 성공: {len(resolved)}/{len(google_arts)}")
    return resolved


def extract_article_text(url):
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text if article.text and len(article.text) > 50 else None
    except Exception:
        return None


def summarize_text(text, num_sentences=3):
    if not text:
        return ''
    sentences = []
    for s in text.replace('\n', ' ').split('.'):
        s = s.strip()
        if len(s) > 30:
            sentences.append(s + '.')
        if len(sentences) >= num_sentences:
            break
    return ' '.join(sentences)


async def generate_tts(text, filepath):
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(str(filepath))


def send_discord_embed(embeds):
    data = {'username': 'Energy News Bot', 'embeds': embeds}
    resp = requests.post(WEBHOOK_URL, json=data)
    if resp.status_code not in (200, 204):
        print(f"  [!] Discord {resp.status_code}")
    time.sleep(1)


def send_discord_audio(filepath, message=""):
    with open(filepath, 'rb') as f:
        data = {'username': 'Energy News Bot'}
        if message:
            data['content'] = message
        files = {'file': (filepath.name, f, 'audio/mpeg')}
        resp = requests.post(WEBHOOK_URL, data=data, files=files)
        if resp.status_code not in (200, 204):
            print(f"  [!] Audio upload {resp.status_code}")
    time.sleep(1)


def main():
    if 'YOUR_DISCORD_WEBHOOK_URL_HERE' in WEBHOOK_URL:
        print("=" * 50)
        print("  [!] Discord 웹훅 URL을 설정해주세요!")
        print("  discord_energy.py 파일에서 WEBHOOK_URL 수정")
        print("  또는 환경변수 DISCORD_ENERGY_WEBHOOK_URL 설정")
        print("=" * 50)
        return

    with open(ARTICLES_JSON, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    articles = [a for a in articles if not is_korean(a)]

    today = datetime.now().strftime('%Y-%m-%d')
    dates = sorted(set(a['date'] for a in articles if a.get('date')), reverse=True)
    target_date = today if today in dates else (dates[0] if dates else None)
    if not target_date:
        print("기사 없음")
        return

    day_articles = [a for a in articles if a.get('date') == target_date]
    for a in day_articles:
        a['total_score'] = calc_total(a)
    day_articles.sort(key=lambda x: x['total_score'], reverse=True)

    candidates = day_articles[:50]

    print(f"Date: {target_date} | {len(day_articles)}건 중 후보 {len(candidates)}개")

    # ── Step 1: URL 변환 ──
    url_map = resolve_urls_playwright(candidates)
    for art in candidates:
        if art['link'] in url_map:
            art['real_url'] = url_map[art['link']]

    # ── Step 2: 중복 제거 + 본문 추출 성공한 기사만 Top 20 선별 ──
    sent_history = load_sent_history()
    print(f"\n  기존 발송 이력: {len(sent_history)}건")

    top10 = []
    skipped_dup = 0
    print("  본문 추출 중 (중복 제외, 성공한 기사만 선별)...")
    for art in candidates:
        if len(top10) >= 20:
            break

        h = article_hash(art)
        if h in sent_history:
            skipped_dup += 1
            continue

        real_url = art.get('real_url', art.get('link', ''))
        if 'news.google.com' in real_url:
            continue

        body = extract_article_text(real_url)
        if not body:
            continue

        summary_en = summarize_text(body, num_sentences=3)
        title_ko = translate_text(art['title'])
        summary_ko = translate_text(summary_en)

        if not summary_ko or len(summary_ko) < 20:
            continue

        art['title_ko'] = title_ko
        art['summary_ko'] = summary_ko[:400]
        art['real_url'] = real_url
        top10.append(art)
        print(f"    #{len(top10)} {art['title'][:50]}...")

    print(f"  중복 스킵: {skipped_dup}건")
    print(f"\n  본문 추출 성공: {len(top10)}건")

    if not top10:
        print("본문 추출 가능한 기사 없음")
        return

    # ── Step 3: TTS 음성 생성 ──
    print("\n  음성 생성 중...")
    tts_lines = []
    tts_lines.append(f"안녕하세요. {target_date} 에너지 뉴스 브리핑을 시작하겠습니다.")
    tts_lines.append("")

    for i, art in enumerate(top10):
        rank = i + 1
        tts_lines.append(f"{rank}번째 기사입니다.")
        tts_lines.append(art['title_ko'])
        tts_lines.append(art['summary_ko'])
        tts_lines.append("")

    tts_lines.append("이상으로 오늘의 에너지 뉴스 브리핑을 마치겠습니다. 감사합니다.")

    tts_text = '\n'.join(tts_lines)
    audio_path = AUDIO_DIR / f"energy_briefing_{target_date}.mp3"

    try:
        asyncio.run(generate_tts(tts_text, audio_path))
        print(f"  음성 저장: {audio_path.name}")
        tts_ok = True
    except Exception as e:
        print(f"  음성 생성 실패: {e}")
        tts_ok = False

    # ── Step 4: Discord 전송 ──
    cat_colors = {
        'renewable': 0x66bb6a, 'hydrogen': 0x29b6f6,
        'nuclear': 0xffa726, 'battery': 0xab47bc,
    }
    cat_labels = {
        'renewable': 'Renewable', 'hydrogen': 'Hydrogen',
        'nuclear': 'Nuclear', 'battery': 'Battery',
    }
    tier_emojis = {1: ':star:', 2: ':green_circle:', 3: ':blue_circle:', 4: ':white_circle:'}
    rank_medals = {0: ':first_place:', 1: ':second_place:', 2: ':third_place:'}

    header = {
        'title': f':zap:  Energy Daily Top 20 — {target_date}',
        'description': (
            f':loud_sound: 음성 브리핑 포함\n'
            f'본문 요약 + 한국어 번역 | 전체 {len(day_articles)}건 중 상위 {len(top10)}개'
        ),
        'color': 0x66bb6a,
    }
    send_discord_embed([header])

    if tts_ok and audio_path.exists():
        send_discord_audio(audio_path, f":loud_sound: **{target_date} 에너지 뉴스 브리핑** (음성)")

    for i, art in enumerate(top10):
        cat = art.get('category', 'renewable')
        color = cat_colors.get(cat, 0x888888)
        cat_label = cat_labels.get(cat, cat)
        tier = art.get('tier', 4)
        tier_emoji = tier_emojis.get(tier, ':white_circle:')
        score = art.get('total_score', 0)
        source = art.get('source_name', '') or ''
        real_url = art.get('real_url', '')
        rank = rank_medals.get(i, f'`#{i+1}`')

        description = f"**{art['title_ko']}**\n\n{art['summary_ko']}"

        embed = {
            'title': f"{rank}  {art['title'][:200]}",
            'url': real_url,
            'description': description,
            'color': color,
            'fields': [
                {'name': 'Source', 'value': f'{tier_emoji} {source}', 'inline': True},
                {'name': 'Topic', 'value': cat_label, 'inline': True},
                {'name': 'Score', 'value': f'`{score}`', 'inline': True},
            ],
        }
        send_discord_embed([embed])

    # ── Step 5: 발송 이력 저장 ──
    for art in top10:
        sent_history.add(article_hash(art))
    save_sent_history(sent_history)
    print(f"  발송 이력 저장: 총 {len(sent_history)}건")

    print(f"\nDiscord 전송 완료! (Top {len(top10)}, 번역 + 요약 + 음성)")


if __name__ == '__main__':
    main()
