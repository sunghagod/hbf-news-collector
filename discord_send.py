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
import re
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
from googlenewsdecoder import gnewsdecoder

OUTPUT_DIR = Path(__file__).parent
ARTICLES_JSON = OUTPUT_DIR / "articles.json"
SENT_HISTORY = OUTPUT_DIR / "sent_history.json"
AUDIO_DIR = OUTPUT_DIR / "audio"
AUDIO_DIR.mkdir(exist_ok=True)

WEBHOOK_URL = os.environ.get(
    "DISCORD_WEBHOOK_URL",
    "https://discordapp.com/api/webhooks/1481357268867092575/nyWsUK8gyZ9BdsWlsBq55xLCDtycaAU6xJ_9AhZYpi1OXZI_qUR9rZo5FkmGNVk34J3V"
)

# edge-tts 한국어 음성
TTS_VOICE = "en-US-EmmaMultilingualNeural"  # 다국어 여성 (한국어 지원)

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


def load_sent_history():
    """이미 발송한 기사 해시 목록 로드"""
    if SENT_HISTORY.exists():
        try:
            with open(SENT_HISTORY, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_sent_history(sent_set):
    """발송한 기사 해시 목록 저장"""
    with open(SENT_HISTORY, 'w', encoding='utf-8') as f:
        json.dump(sorted(sent_set), f, ensure_ascii=False)


def article_hash(art):
    """기사 제목 기반 해시 (중복 판별용)"""
    title = art.get('title', '').strip().lower()
    return hashlib.md5(title.encode()).hexdigest()[:16]

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


JS_ACCEPT_COOKIES = """
() => {
    const btnSelectors = [
        '[id*="cookie"] button', '[class*="cookie"] button',
        '[id*="consent"] button', '[class*="consent"] button',
        '[id*="gdpr"] button', '[class*="gdpr"] button',
        '[class*="banner"] button[class*="accept"]',
        '[class*="banner"] button[class*="agree"]',
        'button[id*="accept"]', 'button[class*="accept"]',
        'button[id*="agree"]', 'button[class*="agree"]',
        '[aria-label*="accept" i]', '[aria-label*="agree" i]',
        '[aria-label*="동의" i]', '[aria-label*="수락" i]',
        '[class*="cookie-accept"]', '[class*="cookie-agree"]',
        '#onetrust-accept-btn-handler',
        '.fc-cta-consent', '.fc-button.fc-cta-consent',
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
        '.cc-btn.cc-allow', '.cc-accept',
        '[data-testid="cookie-accept"]',
    ];
    for (const sel of btnSelectors) {
        try {
            const btns = document.querySelectorAll(sel);
            for (const btn of btns) {
                const text = (btn.innerText || '').toLowerCase();
                if (text.match(/(accept|agree|allow|ok|확인|동의|수락|허용|닫기|close|got it|i understand)/)) {
                    btn.click();
                    return 'clicked: ' + sel;
                }
            }
        } catch(e) {}
    }
    const allBtns = document.querySelectorAll('button, a[role="button"], [class*="btn"]');
    for (const btn of allBtns) {
        const text = (btn.innerText || '').trim().toLowerCase();
        if (text.match(/^(accept all|accept cookies|agree|allow all|i agree|동의|수락|허용|쿠키 허용|모두 허용|확인)$/)) {
            btn.click();
            return 'clicked fallback: ' + text;
        }
    }
    return 'no cookie banner found';
}
"""

JS_EXTRACT_TEXT = """
() => {
    const selectors = [
        'article', '[role="article"]', '.article-body', '.article-content',
        '.story-body', '.post-content', '.entry-content', '.content-body',
        '.caas-body', '.article__body', '.article-text', '.story-content',
        '.post-body', '.field-body', 'main'
    ];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el && el.innerText && el.innerText.trim().length > 100) {
            return el.innerText.trim();
        }
    }
    const paragraphs = document.querySelectorAll('p');
    const texts = Array.from(paragraphs)
        .map(p => p.innerText.trim())
        .filter(t => t.length > 40);
    if (texts.length >= 2) return texts.join('\\n');
    return '';
}
"""


def resolve_and_extract(articles):
    """gnewsdecoder로 URL 디코딩 → newspaper4k/Playwright로 본문 추출"""
    results = {}

    print(f"  URL 디코딩 + 본문 추출 ({len(articles)}개)...")

    # Step 1: gnewsdecoder로 URL 디코딩
    decoded_urls = {}
    decode_ok = 0
    decode_fail = 0
    for i, art in enumerate(articles):
        link = art['link']
        try:
            result = gnewsdecoder(link, interval=2)
            if result.get('status') and result.get('decoded_url'):
                decoded_urls[link] = result['decoded_url']
                decode_ok += 1
            else:
                decode_fail += 1
        except Exception:
            decode_fail += 1

        if (i + 1) % 10 == 0:
            print(f"    디코딩 [{i+1}/{len(articles)}] OK:{decode_ok} FAIL:{decode_fail}")

    print(f"  URL 디코딩 완료: {decode_ok}/{len(articles)} 성공")

    if decode_ok == 0:
        print("  [!] URL 디코딩 전부 실패 — Google 접속 차단 가능성 (다음 실행 시 복구)")
        return results

    # Step 2: 본문 추출 (newspaper4k 우선, Playwright 폴백)
    print(f"  본문 추출 중...")
    pw_browser = None
    pw_page = None

    for i, art in enumerate(articles):
        link = art['link']
        real_url = decoded_urls.get(link)
        if not real_url:
            continue

        title = art.get('title', '')
        body = None

        # 2a: newspaper4k
        try:
            article_obj = Article(real_url)
            article_obj.download()
            article_obj.parse()
            if article_obj.text and len(article_obj.text) > 100:
                body = article_obj.text
        except Exception:
            pass

        # 2b: Playwright 폴백
        if not body:
            try:
                if pw_browser is None:
                    from playwright.sync_api import sync_playwright
                    pw = sync_playwright().start()
                    pw_browser = pw.chromium.launch(headless=True)
                    pw_ctx = pw_browser.new_context(
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
                    )
                    pw_page = pw_ctx.new_page()

                pw_page.goto(real_url, wait_until='domcontentloaded', timeout=15000)
                pw_page.wait_for_timeout(1500)
                # 쿠키 동의 배너 자동 수락
                try:
                    cookie_result = pw_page.evaluate(JS_ACCEPT_COOKIES)
                    if 'clicked' in cookie_result:
                        pw_page.wait_for_timeout(1000)
                except Exception:
                    pass
                body = pw_page.evaluate(JS_EXTRACT_TEXT)
                if body and len(body) < 100:
                    body = None
            except Exception:
                pass

        if body:
            results[link] = {'real_url': real_url, 'body': body}
            print(f"    [{len(results)}] OK ({len(body)}자): {title[:45]}...")
        else:
            print(f"    [-] 본문 없음: {title[:45]}...")

    if pw_browser:
        try:
            pw_browser.close()
        except Exception:
            pass

    print(f"  추출 성공: {len(results)}/{decode_ok} (디코딩 성공 기사 중)")
    return results


NOISE_KEYWORDS = re.compile(
    r'쿠키|cookie|개인정보|privacy\s*policy|비밀번호.*저장|password.*save|'
    r'로그인.*저장|로그인\s*정보|sign\s*in.*remember|log\s*in.*save|'
    r'we\s+use\s+cookies|this\s+site\s+uses?\s+cookies|'
    r'GDPR|CCPA|데이터\s*보호|consent|동의.*약관|'
    r'광고\s*차단|ad\s*block|paywall|'
    r'확인란.*선택|사용자\s*ID.*비밀번호|'
    r'browsing\s*experience|tracking\s*technolog',
    re.IGNORECASE
)

def clean_body_text(text):
    """쿠키 동의, 로그인 팝업, 개인정보 안내 등 비기사 문장 제거"""
    if not text:
        return text
    parts = re.split(r'(?<=[.!?다요])\s+', text.replace('\n', ' '))
    cleaned = [s for s in parts if s.strip() and not NOISE_KEYWORDS.search(s)]
    result = ' '.join(cleaned).strip()
    return result if len(result) > 20 else text


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


async def _generate_tts_async(text, filepath):
    """edge-tts로 한국어 음성 파일 생성"""
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(str(filepath))


def generate_tts(text, filepath):
    """이벤트 루프 충돌 방지: 기존 루프가 있으면 nest_asyncio 사용"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import nest_asyncio
        nest_asyncio.apply()
        loop.run_until_complete(_generate_tts_async(text, filepath))
    else:
        asyncio.run(_generate_tts_async(text, filepath))


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
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='특정 날짜 지정 (YYYY-MM-DD)')
    args = parser.parse_args()

    with open(ARTICLES_JSON, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    articles = [a for a in articles if not is_korean(a)]
    articles = [a for a in articles if a.get('tier', 4) <= 3]

    today = datetime.now().strftime('%Y-%m-%d')
    dates = sorted(set(a['date'] for a in articles if a.get('date')), reverse=True)

    if args.date:
        target_date = args.date
    else:
        target_date = today if today in dates else (dates[0] if dates else None)

    if not target_date:
        print("기사 없음")
        return

    day_articles = [a for a in articles if a.get('date') == target_date]
    for a in day_articles:
        a['total_score'] = calc_total(a)
    day_articles.sort(key=lambda x: x['total_score'], reverse=True)

    # 중복 제거
    sent_history = load_sent_history()
    print(f"  기존 발송 이력: {len(sent_history)}건")

    # 이미 보낸 기사 제외
    candidates = []
    skipped_dup = 0
    for a in day_articles:
        h = article_hash(a)
        if h in sent_history:
            skipped_dup += 1
        else:
            candidates.append(a)
        if len(candidates) >= 50:
            break

    print(f"Date: {target_date} | {len(day_articles)}건, 중복 {skipped_dup}건 제외, 후보 {len(candidates)}개")

    if not candidates:
        print("새로 보낼 기사 없음 (모두 기발송)")
        return

    # ── Step 1+2: Playwright로 URL 변환 + 본문 추출 한 번에 ──
    extract_results = resolve_and_extract(candidates)

    # ── 본문 추출 성공한 기사만 Top 20 선별 ──
    top10 = []
    for art in candidates:
        if len(top10) >= 20:
            break

        result = extract_results.get(art['link'])
        if not result:
            continue

        body = result['body']
        real_url = result['real_url']

        body = clean_body_text(body)
        summary_en = summarize_text(body, num_sentences=3)
        title_ko = translate_text(art['title'])
        summary_ko = translate_text(summary_en)

        if not summary_ko or len(summary_ko) < 20:
            continue

        art['title_ko'] = title_ko
        art['summary_ko'] = summary_ko[:400]
        art['real_url'] = real_url
        top10.append(art)

    print(f"  중복 스킵: {skipped_dup}건")
    print(f"\n  최종 전송 대상: {len(top10)}건")

    if not top10:
        print("본문 추출 가능한 기사 없음")
        return

    # ── Step 3: TTS 음성 생성 (존댓말) ──
    print("\n  음성 생성 중...")
    tts_lines = []
    tts_lines.append(f"안녕하세요. {target_date} HBF 뉴스 브리핑을 시작하겠습니다.")
    tts_lines.append("")

    for i, art in enumerate(top10):
        rank = i + 1
        tts_lines.append(f"{rank}번째 기사입니다.")
        tts_lines.append(art['title_ko'])
        tts_lines.append(art['summary_ko'])
        tts_lines.append("")

    tts_lines.append("이상으로 오늘의 HBF 뉴스 브리핑을 마치겠습니다. 감사합니다.")

    tts_text = '\n'.join(tts_lines)
    audio_path = AUDIO_DIR / f"hbf_briefing_{target_date}.mp3"

    try:
        generate_tts(tts_text, audio_path)
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

    # ── Step 5: 발송 이력 저장 (중복 방지) ──
    for art in top10:
        sent_history.add(article_hash(art))
    save_sent_history(sent_history)
    print(f"  발송 이력 저장: 총 {len(sent_history)}건")

    print(f"\nDiscord 전송 완료! (Top {len(top10)}, 번역 + 요약 + 음성)")


if __name__ == '__main__':
    main()
