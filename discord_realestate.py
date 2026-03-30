"""
Discord 웹훅으로 부동산 Daily Top 20 전송
- 한국어 기사 → 번역 불필요, 본문 추출 + 요약
- gnewsdecoder URL 디코딩 → 본문 추출
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

from newspaper import Article
from playwright.sync_api import sync_playwright
import edge_tts
from googlenewsdecoder import gnewsdecoder

OUTPUT_DIR = Path(__file__).parent
ARTICLES_JSON = OUTPUT_DIR / "articles_realestate.json"
SENT_HISTORY = OUTPUT_DIR / "sent_history_realestate.json"
AUDIO_DIR = OUTPUT_DIR / "audio"
AUDIO_DIR.mkdir(exist_ok=True)

# ── Discord 웹훅 URL (환경변수 또는 직접 입력) ──
WEBHOOK_URL = os.environ.get(
    "DISCORD_REALESTATE_WEBHOOK_URL",
    "https://discordapp.com/api/webhooks/1486327929435590768/97ACKAtI6YmXFuwCNRcJlx-grAMv_xLc5DRjeG3FURpTGn2dP5NIaiLd84-NmuEwLaxS"
)

TTS_VOICE = "en-US-EmmaMultilingualNeural"  # 다국어 여성 (한국어 지원)

# ── 부동산 점수 키워드 ──
REALESTATE_KEYWORDS = {
    '부동산 대책': 5, '규제 완화': 5, '규제 강화': 5,
    '종부세': 4, '양도세': 4, '취득세': 4,
    '다주택자': 4, '투기과열': 5, '조정대상': 5,
    '매매가': 4, '시세': 3, '실거래가': 4,
    '급등': 5, '급락': 5, '신고가': 5,
    '거래량': 4, '전세가': 4, '집값': 3,
    '분양': 3, '청약': 4, '경쟁률': 5,
    '분양가': 4, '미분양': 5, '무순위': 5,
    '금리': 4, '대출': 3, '주담대': 5,
    'DSR': 5, 'LTV': 4,
    '재건축': 4, '재개발': 4, '정비사업': 4,
    '초과이익': 5, '안전진단': 5,
    '서울': 2, '강남': 3, '수도권': 2,
    'GTX': 4, '3기 신도시': 5,
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


def calc_total(art):
    title = art['title']
    score = 0
    for kw, w in REALESTATE_KEYWORDS.items():
        if kw in title:
            score += w
    tier_s = {1: 10, 2: 7, 3: 4, 4: 1}.get(art.get('tier', 4), 1)
    return round(score * 0.7 + tier_s * 0.3, 1)


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
    // 텍스트 기반 폴백: 모든 버튼/링크에서 동의 관련 텍스트 찾기
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
        '.post-body', '.field-body', '#articleBodyContents', '#articeBody',
        '#newsEndContents', '.news_end', '.article_body', '#news_body',
        '.newsct_article', '#dic_area', 'main'
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
        print("  [!] URL 디코딩 전부 실패")
        return results

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

        # newspaper4k
        try:
            article_obj = Article(real_url, language='ko')
            article_obj.download()
            article_obj.parse()
            if article_obj.text and len(article_obj.text) > 100:
                body = article_obj.text
        except Exception:
            pass

        # Playwright 폴백
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
    # 문장 단위로 분리 (한국어: 다. / 요. / 영어: . )
    parts = re.split(r'(?<=[.!?다요])\s+', text.replace('\n', ' '))
    cleaned = [s for s in parts if s.strip() and not NOISE_KEYWORDS.search(s)]
    result = ' '.join(cleaned).strip()
    return result if len(result) > 20 else text


def summarize_text(text, num_sentences=3):
    """한국어 본문 요약 (문장 단위 추출)"""
    if not text:
        return ''
    # 한국어는 마침표(.) 또는 다(다.) 로 문장이 끝남
    sentences = []
    for s in text.replace('\n', ' ').split('.'):
        s = s.strip()
        if len(s) > 20:
            sentences.append(s + '.')
        if len(sentences) >= num_sentences:
            break
    return ' '.join(sentences)


async def _generate_tts_async(text, filepath):
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(str(filepath))


def generate_tts(text, filepath):
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
    data = {'username': '부동산 뉴스봇', 'embeds': embeds}
    resp = requests.post(WEBHOOK_URL, json=data)
    if resp.status_code == 401:
        print(f"  [!] Discord 401 Unauthorized — 웹훅 URL이 유효하지 않습니다!")
        print(f"  환경변수 DISCORD_REALESTATE_WEBHOOK_URL을 확인하세요.")
        raise SystemExit(1)
    if resp.status_code not in (200, 204):
        print(f"  [!] Discord {resp.status_code}")
    time.sleep(1)


def send_discord_audio(filepath, message=""):
    with open(filepath, 'rb') as f:
        data = {'username': '부동산 뉴스봇'}
        if message:
            data['content'] = message
        files = {'file': (filepath.name, f, 'audio/mpeg')}
        resp = requests.post(WEBHOOK_URL, data=data, files=files)
        if resp.status_code == 401:
            print(f"  [!] Discord 401 Unauthorized")
            raise SystemExit(1)
        if resp.status_code not in (200, 204):
            print(f"  [!] Audio upload {resp.status_code}")
    time.sleep(1)


def main():
    if not WEBHOOK_URL:
        print("=" * 50)
        print("  [!] Discord 웹훅 URL이 설정되지 않았습니다!")
        print("  환경변수 DISCORD_REALESTATE_WEBHOOK_URL을 설정해주세요.")
        print("=" * 50)
        return

    with open(ARTICLES_JSON, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    articles = [a for a in articles if a.get('tier', 4) <= 3]

    today = datetime.now().strftime('%Y-%m-%d')
    dates = sorted(set(a['date'] for a in articles if a.get('date')), reverse=True)
    target_date = today if today in dates else (dates[0] if dates else None)
    if not target_date:
        print("기사 없음")
        return

    # 당일 기사 우선, 부족하면 전날까지 포함
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

    # URL 디코딩 + 본문 추출
    extract_results = resolve_and_extract(candidates)

    # 본문 추출 성공한 기사만 Top 20
    top20 = []
    for art in candidates:
        if len(top20) >= 20:
            break

        result = extract_results.get(art['link'])
        if not result:
            continue

        body = result['body']
        real_url = result['real_url']

        body = clean_body_text(body)
        summary = summarize_text(body, num_sentences=3)

        if not summary or len(summary) < 20:
            continue

        art['summary'] = summary[:400]
        art['real_url'] = real_url
        top20.append(art)

    print(f"  중복 스킵: {skipped_dup}건")
    print(f"\n  최종 전송 대상: {len(top20)}건")

    if not top20:
        print("본문 추출 가능한 기사 없음")
        return

    # TTS 음성 생성
    print("\n  음성 생성 중...")
    tts_lines = []
    tts_lines.append(f"안녕하세요. {target_date} 부동산 뉴스 브리핑을 시작하겠습니다.")
    tts_lines.append("")

    for i, art in enumerate(top20):
        rank = i + 1
        tts_lines.append(f"{rank}번째 기사입니다.")
        tts_lines.append(art['title'])
        tts_lines.append(art['summary'])
        tts_lines.append("")

    tts_lines.append("이상으로 오늘의 부동산 뉴스 브리핑을 마치겠습니다. 감사합니다.")

    tts_text = '\n'.join(tts_lines)
    audio_path = AUDIO_DIR / f"realestate_briefing_{target_date}.mp3"

    try:
        generate_tts(tts_text, audio_path)
        print(f"  음성 저장: {audio_path.name}")
        tts_ok = True
    except Exception as e:
        print(f"  음성 생성 실패: {e}")
        tts_ok = False

    # Discord 전송
    cat_colors = {
        'policy': 0xef5350, 'market': 0x42a5f5,
        'subscription': 0x66bb6a, 'finance': 0xffa726,
        'redevelop': 0xab47bc,
    }
    cat_labels = {
        'policy': '정책/규제', 'market': '시장/시세',
        'subscription': '분양/청약', 'finance': '금리/대출',
        'redevelop': '재건축/재개발',
    }
    tier_emojis = {1: ':star:', 2: ':red_circle:', 3: ':blue_circle:', 4: ':white_circle:'}
    rank_medals = {0: ':first_place:', 1: ':second_place:', 2: ':third_place:'}

    # 음성 파일 먼저 전송 (찾기 쉽게)
    if tts_ok and audio_path.exists():
        send_discord_audio(audio_path, f":loud_sound: **{target_date} 부동산 뉴스 브리핑** (음성)")

    # 통합 embed 구성
    desc_lines = []
    for i, art in enumerate(top20):
        cat = art.get('category', 'market')
        cat_label = cat_labels.get(cat, cat)
        tier = art.get('tier', 4)
        tier_emoji = tier_emojis.get(tier, ':white_circle:')
        score = art.get('total_score', 0)
        source = art.get('source_name', '') or ''
        real_url = art.get('real_url', '')
        rank = rank_medals.get(i, f'`#{i+1}`')

        if i < 3:
            title_line = f"[{art['title'][:80]}]({real_url})" if real_url else art['title'][:80]
            summary = (art.get('summary') or '')[:150]
            desc_lines.append(f"{rank} **{art['title'][:60]}**")
            desc_lines.append(f"{title_line}")
            desc_lines.append(f"> {summary}")
            desc_lines.append(f"{tier_emoji} {source} · {cat_label} · `{score}점`\n")
        else:
            title = art.get('title', '')[:50]
            link = f"[링크]({real_url})" if real_url else ''
            desc_lines.append(f"{rank} {title} · `{score}점` {link}")

    description = '\n'.join(desc_lines)
    if len(description) > 4090:
        description = description[:4090] + '…'

    embed = {
        'title': f':house:  부동산 Daily Top 20 — {target_date}',
        'description': description,
        'color': 0xef5350,
        'footer': {'text': f'Tier 1~3 매체 | 전체 {len(day_articles)}건 중 상위 {len(top20)}개'},
    }
    send_discord_embed([embed])

    # 발송 이력 저장
    for art in top20:
        sent_history.add(article_hash(art))
    save_sent_history(sent_history)
    print(f"  발송 이력 저장: 총 {len(sent_history)}건")

    print(f"\nDiscord 전송 완료! (Top {len(top20)}, 요약 + 음성)")


if __name__ == '__main__':
    main()
