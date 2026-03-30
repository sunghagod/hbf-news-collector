"""
Discord 웹훅으로 Energy Daily Top 20 전송
- 선물 시세 (WTI, 브렌트유, 천연가스, 우라늄) 포함
- gnewsdecoder URL 디코딩 → 본문 추출 → 한국어 번역/요약
- edge-tts 음성 브리핑 → Discord 전송
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
ARTICLES_JSON = OUTPUT_DIR / "articles_energy.json"
SENT_HISTORY = OUTPUT_DIR / "sent_history_energy.json"
AUDIO_DIR = OUTPUT_DIR / "audio"
AUDIO_DIR.mkdir(exist_ok=True)

# ── Discord 웹훅 URL (환경변수 필수) ──
WEBHOOK_URL = os.environ.get("DISCORD_ENERGY_WEBHOOK_URL", "")

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

# ── 에너지 선물 시세 ──
FUTURES_TICKERS = {
    'CL=F':  {'name': 'WTI 원유',    'emoji': ':oil_drum:'},
    'BZ=F':  {'name': '브렌트유',     'emoji': ':oil_drum:'},
    'NG=F':  {'name': '천연가스',     'emoji': ':fire:'},
    'URA':   {'name': '우라늄(URA)',  'emoji': ':radioactive:'},
    'TAN':   {'name': '태양광(TAN)',  'emoji': ':sunny:'},
    'ICLN':  {'name': '클린에너지(ICLN)', 'emoji': ':leaf:'},
}


def fetch_futures_prices():
    """yfinance로 에너지 선물/ETF 시세 조회"""
    try:
        import yfinance as yf
    except ImportError:
        print("  [!] yfinance 미설치")
        return []

    results = []
    for sym, info in FUTURES_TICKERS.items():
        try:
            t = yf.Ticker(sym)
            hist = t.history(period='5d')
            if hist.empty or len(hist) < 2:
                continue
            price = hist.iloc[-1]['Close']
            prev = hist.iloc[-2]['Close']
            chg_pct = ((price - prev) / prev) * 100
            # 5일 전 대비
            price_5d = hist.iloc[0]['Close']
            chg_5d = ((price - price_5d) / price_5d) * 100
            results.append({
                'symbol': sym,
                'name': info['name'],
                'emoji': info['emoji'],
                'price': price,
                'chg_pct': chg_pct,
                'chg_5d': chg_5d,
            })
        except Exception as e:
            print(f"  [!] {sym} 조회 실패: {e}")
    return results


def format_futures_embed(futures_data, target_date):
    """선물 시세를 Discord embed로 포맷"""
    if not futures_data:
        return None

    lines = []
    for f in futures_data:
        arrow = ':chart_with_upwards_trend:' if f['chg_pct'] >= 0 else ':chart_with_downwards_trend:'
        sign = '+' if f['chg_pct'] >= 0 else ''
        sign5 = '+' if f['chg_5d'] >= 0 else ''
        lines.append(
            f"{f['emoji']} **{f['name']}**  `${f['price']:.2f}`  "
            f"{arrow} {sign}{f['chg_pct']:.1f}% (5일 {sign5}{f['chg_5d']:.1f}%)"
        )

    return {
        'title': f':chart_with_upwards_trend:  에너지 선물 시세 — {target_date}',
        'description': '\n'.join(lines),
        'color': 0xf39c12,
        'footer': {'text': 'Yahoo Finance | 전일 종가 기준'},
    }


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

    # Step 1: gnewsdecoder로 URL 디코딩 (Google batchexecute API 사용)
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

        # 2a: newspaper4k (빠르고 가벼움)
        try:
            article_obj = Article(real_url)
            article_obj.download()
            article_obj.parse()
            if article_obj.text and len(article_obj.text) > 100:
                body = article_obj.text
        except Exception:
            pass

        # 2b: Playwright 폴백 (newspaper 실패 시)
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
    data = {'username': 'Energy News Bot', 'embeds': embeds}
    resp = requests.post(WEBHOOK_URL, json=data)
    if resp.status_code == 401:
        print(f"  [!] Discord 401 Unauthorized — 웹훅 URL이 유효하지 않습니다!")
        print(f"  GitHub Secrets에서 DISCORD_ENERGY_WEBHOOK_URL을 확인하세요.")
        raise SystemExit(1)
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
        if resp.status_code == 401:
            print(f"  [!] Discord 401 Unauthorized — 웹훅 URL이 유효하지 않습니다!")
            raise SystemExit(1)
        if resp.status_code not in (200, 204):
            print(f"  [!] Audio upload {resp.status_code}")
    time.sleep(1)


def main():
    if not WEBHOOK_URL:
        print("=" * 50)
        print("  [!] Discord 웹훅 URL이 설정되지 않았습니다!")
        print("  환경변수 DISCORD_ENERGY_WEBHOOK_URL을 설정해주세요.")
        print("  GitHub Actions: Settings > Secrets에 추가")
        print("=" * 50)
        return

    with open(ARTICLES_JSON, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    articles = [a for a in articles if not is_korean(a)]
    articles = [a for a in articles if a.get('tier', 4) <= 3]

    today = datetime.now().strftime('%Y-%m-%d')
    dates = sorted(set(a['date'] for a in articles if a.get('date')), reverse=True)
    target_date = today if today in dates else (dates[0] if dates else None)
    if not target_date:
        print("기사 없음")
        return

    # 당일 기사 우선, 부족하면 전날까지 포함하여 20건 확보
    target_dates = [target_date]
    day_articles = [a for a in articles if a.get('date') == target_date]
    if len(day_articles) < 20:
        prev_dates = [d for d in dates if d < target_date]
        if prev_dates:
            prev_date = prev_dates[0]
            target_dates.append(prev_date)
            day_articles += [a for a in articles if a.get('date') == prev_date]

    for a in day_articles:
        a['total_score'] = calc_total(a)
    day_articles.sort(key=lambda x: x['total_score'], reverse=True)

    # 중복 제거
    sent_history = load_sent_history()
    print(f"  기존 발송 이력: {len(sent_history)}건")

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

    date_label = ' + '.join(target_dates)
    print(f"Date: {date_label} | {len(day_articles)}건, 중복 {skipped_dup}건 제외, 후보 {len(candidates)}개")

    if not candidates:
        print("새로 보낼 기사 없음 (모두 기발송)")
        return

    # ── Step 1+2: URL 디코딩 + 본문 추출 ──
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

    # ── Step 2.5: 선물 시세 조회 ──
    print("\n  선물 시세 조회 중...")
    futures_data = fetch_futures_prices()
    if futures_data:
        print(f"  선물 시세: {len(futures_data)}개 조회 완료")

    # ── Step 3: TTS 음성 생성 ──
    print("\n  음성 생성 중...")
    tts_lines = []
    tts_lines.append(f"안녕하세요. {target_date} 에너지 뉴스 브리핑을 시작하겠습니다.")
    tts_lines.append("")

    # 선물 시세 음성
    if futures_data:
        tts_lines.append("먼저 에너지 선물 시세입니다.")
        for f in futures_data:
            direction = "상승" if f['chg_pct'] >= 0 else "하락"
            tts_lines.append(f"{f['name']} {f['price']:.2f}달러, 전일 대비 {abs(f['chg_pct']):.1f}퍼센트 {direction}.")
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
        generate_tts(tts_text, audio_path)
        print(f"  음성 저장: {audio_path.name}")
        tts_ok = True
    except Exception as e:
        print(f"  음성 생성 실패: {e}")
        tts_ok = False

    # ── Step 4: Discord 전송 ──

    # 선물 시세 먼저 전송
    futures_embed = format_futures_embed(futures_data, target_date)
    if futures_embed:
        send_discord_embed([futures_embed])
        print(f"  선물 시세 전송 완료")

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
            f'Tier 1~3 매체만 | 전체 {len(day_articles)}건 중 상위 {len(top10)}개'
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
