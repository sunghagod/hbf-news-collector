"""
Discord 웹훅으로 HBF Daily Top 20 전송
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
ARTICLES_JSON = OUTPUT_DIR / "articles.json"
AUDIO_DIR = OUTPUT_DIR / "audio"
AUDIO_DIR.mkdir(exist_ok=True)

WEBHOOK_URL = os.environ.get(
    "DISCORD_WEBHOOK_URL",
    "https://discordapp.com/api/webhooks/1481357268867092575/nyWsUK8gyZ9BdsWlsBq55xLCDtycaAU6xJ_9AhZYpi1OXZI_qUR9rZo5FkmGNVk34J3V"
)

# edge-tts 한국어 음성
TTS_VOICE = "ko-KR-SunHiNeural"  # 여성 / ko-KR-InJoonNeural = 남성

KOREAN_INDICATORS = [
    '.co.kr', '.kr/', 'chosun', 'joongang', 'joins.com', 'donga',
    'hankyung', 'mk.co', 'sedaily', 'etnews', 'hani.co', 'khan.co',
    'yonhap', 'newsis', 'news1', 'edaily', 'bloter', 'theelec',
    'daum.net', 'naver.com', 'ajupress', 'aju.news', 'asiae',
    'heraldcorp', 'koreaherald', 'koreatimes', 'koreabiomed',
    'businesskorea', 'pulsenews', 'theinvestor', 'korea',
    'kmib', 'nocutnews', 'fnnews', 'newspim', 'dt.co.kr',
    'inews24', 'ddaily', 'businesspost', 'mt.co.kr', 'zdnet.co.kr',
    '조선', '중앙', '동아', '한겨레', '경향', '매일경제', '한국경제', '연합', '전자신문',
]

HBF_KEYWORDS = {
    'HBF': 5, 'HIGH BANDWIDTH FLASH': 5,
    'MASS PRODUCTION': 4, 'FABRICATION': 4, 'MANUFACTURING': 4,
    'PRODUCTION': 3, 'PROTOTYPE': 4, 'SAMPLE': 4,
    'TAPE-OUT': 4, 'TAPE OUT': 4, 'YIELD': 4,
    'DEVELOPMENT': 3, 'PROGRESS': 3, 'BREAKTHROUGH': 4,
    'MILESTONE': 4, 'UNVEIL': 3, 'LAUNCH': 3,
    'STANDARDIZATION': 4, 'STANDARD': 3, 'CONSORTIUM': 3,
    'ARCHITECTURE': 3, 'BANDWIDTH': 3, 'PERFORMANCE': 2,
    'INFERENCE': 3, 'NAND': 2, 'FLASH': 2, 'STACKING': 3,
    'SK HYNIX': 2, 'SAMSUNG': 1, 'SANDISK': 2, 'KIOXIA': 2,
}
DARIO_KEYWORDS = {'DARIO AMODEI': 5, 'DARIO': 3, 'ANTHROPIC': 2}

translator = GoogleTranslator(source='en', target='ko')

# ── 번역 시 원문 유지할 고유명사 ──
PROPER_NOUNS = [
    # 회사/조직
    'SK hynix', 'SK Hynix', 'Samsung Electronics', 'Samsung',
    'SanDisk', 'Sandisk', 'Kioxia', 'Micron', 'NVIDIA', 'Nvidia',
    'Applied Materials', 'TSMC', 'Intel', 'Qualcomm', 'Broadcom',
    'AMD', 'ARM', 'Arm', 'Apple', 'Google', 'Microsoft', 'Meta',
    'Anthropic', 'OpenAI', 'Western Digital', 'Nanya', 'ASML',
    'Lam Research', 'Tokyo Electron', 'GlobalFoundries',
    'Goldman Sachs', 'Morgan Stanley', 'JP Morgan', 'Citi', 'Barclays',
    'TrendForce', 'SemiAnalysis', 'TechInsights', 'Digitimes',
    # 인물
    'Dario Amodei', 'Jensen Huang', 'Kwak Noh-Jung', 'Jay Y. Lee',
    'Lisa Su', 'Pat Gelsinger', 'Sam Altman', 'Elon Musk',
    # 기술 용어 (영문 유지)
    'HBF', 'HBM', 'HBM4', 'HBM3E', 'HBM3', 'LPDDR6', 'LPDDR5X',
    'DDR5', 'DDR6', 'GDDR7', 'DRAM', 'NAND', 'SRAM',
    'CXL', 'PCIe', 'NVMe', 'TSV', 'GAA', 'FinFET', 'EUV',
    'CoWoS', 'SoIC', 'FOWLP', 'RDL', 'SiP',
    'GPU', 'CPU', 'NPU', 'TPU', 'SoC', 'ASIC', 'FPGA',
    'AI', 'LLM', 'AGI', 'GPT', 'Claude',
    'GB/s', 'TB/s', 'Gbps', 'GHz', 'nm', '1c', '1b', '1a',
    # 제품명
    'Blackwell', 'Hopper', 'Rubin', 'Grace', 'Gaudi',
    'Exynos', 'Snapdragon', 'Dimensity',
]


def protect_proper_nouns(text):
    """고유명사를 플레이스홀더로 치환 (번역 보호)"""
    # 긴 것부터 먼저 치환 (SK hynix > SK 순서)
    sorted_nouns = sorted(PROPER_NOUNS, key=len, reverse=True)
    replacements = []
    for noun in sorted_nouns:
        if noun in text:
            placeholder = f"__PN{len(replacements):03d}__"
            text = text.replace(noun, placeholder)
            replacements.append((placeholder, noun))
    return text, replacements


def restore_proper_nouns(text, replacements):
    """플레이스홀더를 원래 고유명사로 복원"""
    for placeholder, noun in replacements:
        text = text.replace(placeholder, noun)
    return text


def is_korean(art):
    check = (art.get('real_url', '') + ' ' + art.get('source_name', '') + ' ' + art.get('link', '')).lower()
    return any(k in check for k in KOREAN_INDICATORS)


def calc_total(art):
    upper = art['title'].upper()
    cat = art.get('category', 'hbf')
    score = 0
    kws = DARIO_KEYWORDS if cat == 'dario' else HBF_KEYWORDS
    for kw, w in kws.items():
        if kw in upper:
            score += w
    if cat != 'dario' and ('HBF' in upper or 'HIGH BANDWIDTH FLASH' in upper):
        score += 10
        for w in ['PRODUCTION', 'PROTOTYPE', 'SAMPLE', 'FABRICAT', 'MANUFACTUR',
                   'BREAKTHROUGH', 'MILESTONE', 'STANDARD', 'UNVEIL', 'LAUNCH', 'TAPE']:
            if w in upper:
                score += 3
    tier_s = {1: 10, 2: 7, 3: 4, 4: 1}.get(art.get('tier', 4), 1)
    return round(score * 0.7 + tier_s * 0.3, 1)


def translate_text(text):
    """영어 → 한국어 번역 (고유명사는 원문 유지)"""
    if not text:
        return ''
    try:
        if len(text) > 4500:
            text = text[:4500]
        # 고유명사 보호
        protected, replacements = protect_proper_nouns(text)
        # 번역
        translated = translator.translate(protected)
        # 고유명사 복원
        result = restore_proper_nouns(translated, replacements)
        return result
    except Exception:
        return text


def resolve_urls_playwright(articles):
    """Playwright로 Google News URL → 실제 URL 일괄 변환"""
    resolved = {}
    google_arts = [a for a in articles if 'news.google.com' in a.get('link', '')]
    if not google_arts:
        return resolved

    print(f"  Playwright: {len(google_arts)}개 URL 변환...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for i, art in enumerate(google_arts):
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
    """edge-tts로 한국어 음성 파일 생성"""
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(str(filepath))


def send_discord_embed(embeds):
    data = {'username': 'HBF News Bot', 'embeds': embeds}
    resp = requests.post(WEBHOOK_URL, json=data)
    if resp.status_code not in (200, 204):
        print(f"  [!] Discord {resp.status_code}")
    time.sleep(1)


def send_discord_audio(filepath, message=""):
    """Discord에 음성 파일 전송"""
    with open(filepath, 'rb') as f:
        data = {'username': 'HBF News Bot'}
        if message:
            data['content'] = message
        files = {'file': (filepath.name, f, 'audio/mpeg')}
        resp = requests.post(WEBHOOK_URL, data=data, files=files)
        if resp.status_code not in (200, 204):
            print(f"  [!] Audio upload {resp.status_code}")
    time.sleep(1)


def main():
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

    # 넉넉하게 상위 50개 후보 (본문 실패 시 차순위 대체)
    candidates = day_articles[:50]

    print(f"Date: {target_date} | {len(day_articles)}건 중 후보 {len(candidates)}개")

    # ── Step 1: URL 변환 ──
    url_map = resolve_urls_playwright(candidates)
    for art in candidates:
        if art['link'] in url_map:
            art['real_url'] = url_map[art['link']]

    # ── Step 2: 본문 추출 성공한 기사만 Top 20 선별 ──
    top10 = []
    print("\n  본문 추출 중 (성공한 기사만 선별)...")
    for art in candidates:
        if len(top10) >= 20:
            break

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

    print(f"\n  본문 추출 성공: {len(top10)}건")

    if not top10:
        print("본문 추출 가능한 기사 없음")
        return

    # ── Step 3: TTS 음성 생성 ──
    print("\n  음성 생성 중...")
    tts_lines = []
    tts_lines.append(f"{target_date} HBF 뉴스 브리핑을 시작합니다.")
    tts_lines.append("")

    for i, art in enumerate(top10):
        rank = i + 1
        tts_lines.append(f"{rank}번째 기사.")
        tts_lines.append(art['title_ko'])
        tts_lines.append(art['summary_ko'])
        tts_lines.append("")

    tts_lines.append("이상으로 오늘의 HBF 뉴스 브리핑을 마칩니다.")

    tts_text = '\n'.join(tts_lines)
    audio_path = AUDIO_DIR / f"hbf_briefing_{target_date}.mp3"

    try:
        asyncio.run(generate_tts(tts_text, audio_path))
        print(f"  음성 저장: {audio_path.name}")
        tts_ok = True
    except Exception as e:
        print(f"  음성 생성 실패: {e}")
        tts_ok = False

    # ── Step 4: Discord 전송 ──
    cat_colors = {'hbf': 0x4fc3f7, 'samsung': 0x1a73e8, 'skhynix': 0xff6d00, 'dario': 0xe040fb}
    cat_labels = {'hbf': 'HBF', 'samsung': 'Samsung', 'skhynix': 'SK hynix', 'dario': 'Dario Amodei'}
    tier_emojis = {1: ':star:', 2: ':blue_circle:', 3: ':green_circle:', 4: ':white_circle:'}
    rank_medals = {0: ':first_place:', 1: ':second_place:', 2: ':third_place:'}

    # 헤더
    header = {
        'title': f':newspaper:  HBF Daily Top 20 — {target_date}',
        'description': (
            f':loud_sound: 음성 브리핑 포함\n'
            f'본문 요약 + 한국어 번역 | 전체 {len(day_articles)}건 중 상위 {len(top10)}개'
        ),
        'color': 0x4fc3f7,
    }
    send_discord_embed([header])

    # 음성 파일 전송
    if tts_ok and audio_path.exists():
        send_discord_audio(audio_path, f":loud_sound: **{target_date} HBF 뉴스 브리핑** (음성)")

    # 기사 카드 전송
    for i, art in enumerate(top10):
        cat = art.get('category', 'hbf')
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

    print(f"\nDiscord 전송 완료! (Top {len(top10)}, 번역 + 요약 + 음성)")


if __name__ == '__main__':
    main()
