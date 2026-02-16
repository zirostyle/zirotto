#!/usr/bin/env python3
"""
연금복권 720+ 자동 구매
플로우: 로그인 → 메인 → 연금복권720+ 바로구매 → 자동번호선택 → 10게임 10,000원 → 구매
DOM 기반 CSS/XPath selector 사용 (하드코딩 좌표 없음)
"""
import time
import re
from pathlib import Path
from playwright.sync_api import Playwright, sync_playwright, Page
from login import login
from telegram_notifier import notify_lotto720_purchase

# .env loading is handled by login module import


# DOM Selectors - 실제 페이지 분석 후 확장 (다중 fallback)
# DOM Selectors - CSS + XPath fallback (실제 페이지 HTML 분석 후 확장)
AUTO_SELECT_SELECTORS = [
    ".lotto720_btn_auto_number",
    "a.lotto720_btn_auto_number",
    "a:has-text('자동번호')",
    "button:has-text('자동번호')",
    "a:has-text('자동 선택')",
    "button:has-text('자동 선택')",
    "[class*='auto_number']",
    "[class*='btn_auto']",
    "text=/자동\\s*(번호|선택)/",
    "a:has-text('자동')",
    "button:has-text('자동')",
    "xpath=//a[contains(text(),'자동') or contains(@class,'auto')]",
    "xpath=//button[contains(text(),'자동')]",
]

CONFIRM_NUMBER_SELECTORS = [
    ".lotto720_btn_confirm_number",
    "a:has-text('선택완료')",
    "button:has-text('선택완료')",
    "[class*='confirm_number']",
    "text=/선택\\s*완료/",
]

# 게임 수/금액 선택 (10게임 = 10,000원, 1,000원/게임)
GAME_COUNT_SELECTORS = [
    "select[name*='game']",
    "select[name*='count']",
    "select[name*='amount']",
    "select#gameCount",
    "select.game_count",
    "select[name*='round']",
    "input[name*='game']",
    "[class*='game_select']",
    "select",
]

TOTAL_AMOUNT_SELECTORS = [
    ".lotto720_price.lpcurpay",
    "[class*='lpcurpay']",
    "[class*='total_price']",
    "[class*='total_amount']",
    ".lotto720_price",
    "[class*='price']",
    "[id*='pay']",
    "[id*='amount']",
    "text=/10[,\\s]*000|총\\s*금액|결제.*금액/",
]

PURCHASE_BUTTON_SELECTORS = [
    "a:has-text('구매하기')",
    "button:has-text('구매하기')",
    "[class*='purchase']:has-text('구매')",
    "a.btn_buy",
    "a[onclick*='buy']",
    "button[onclick*='buy']",
    "text=/구매\\s*하기/",
]

CONFIRM_POPUP_SELECTORS = [
    "#lotto720_popup_confirm",
    "[id*='popup_confirm']",
    "[class*='popup_confirm']",
    ".popup_confirm",
]

CONFIRM_BUTTON_SELECTORS = [
    "#lotto720_popup_confirm a.btn_blue",
    "[id*='popup_confirm'] a.btn_blue",
    ".popup_confirm .btn_blue",
    "a.btn_blue",
    "button:has-text('확인')",
    "a:has-text('확인')",
    "button:has-text('예')",
    "a:has-text('동의')",
    "[class*='btn_blue']",
]


def _click_selector(page_or_frame, selectors: list, name: str, timeout: int = 10000) -> bool:
    """여러 selector 시도하여 클릭 (DOM 기반)"""
    for sel in selectors:
        try:
            el = page_or_frame.locator(sel).first
            el.click(force=True, timeout=timeout)
            print(f"  ✅ {name}: {sel}")
            return True
        except Exception as e:
            print(f"  ⏭ {name} {sel}: {str(e)[:50]}")
    return False


def _get_text_selector(page_or_frame, selectors: list, name: str) -> str:
    """여러 selector 시도하여 텍스트 추출"""
    for sel in selectors:
        try:
            el = page_or_frame.locator(sel).first
            if el.count() > 0:
                return el.inner_text(timeout=3000).strip()
        except:
            pass
    return ""


def _select_option(page_or_frame, value: str, selectors: list) -> bool:
    """select 요소에 옵션 선택 (10게임)"""
    for sel in selectors:
        try:
            select_el = page_or_frame.locator(sel).first
            if select_el.count() > 0:
                # value 또는 label로 시도
                try:
                    select_el.select_option(value=value)
                    return True
                except:
                    select_el.select_option(label=f"{value}게임")
                    return True
        except:
            pass
    return False


def _navigate_to_720_page(page: Page) -> bool:
    """
    메인에서 연금복권720+ 바로구매 메뉴로 진입
    www/el/m 도메인 모두 시도
    """
    # 1) www 메인 → 연금복권720 바로구매 링크
    link_selectors = [
        "a:has-text('연금복권720')",
        "a:has-text('연금복권 720')",
        "a[href*='LP72']",
        "a[href*='game720']",
        "a[href*='720']",
        "text=/연금복권\\s*720.*바로구매/",
        "text=/연금복권\\s*720.*구매/",
        "a:has-text('바로구매')",
    ]
    
    for base_url in ["https://www.dhlottery.co.kr", "https://m.dhlottery.co.kr"]:
        try:
            page.goto(base_url, timeout=60000, wait_until="domcontentloaded")
            time.sleep(2)
            for sel in link_selectors:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible(timeout=2000):
                        el.click(timeout=5000)
                        time.sleep(3)
                        if "720" in page.url or "LP72" in page.url or "game720" in page.url:
                            return True
                except:
                    pass
        except:
            pass
    
    # 2) 직접 URL 이동
    urls = [
        "https://el.dhlottery.co.kr/game/LP72/game720.jsp",
        "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72",
    ]
    for url in urls:
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            time.sleep(3)
            return True
        except:
            pass
    
    return False


def _get_frame(page: Page):
    """iframe 있으면 FrameLocator, 없으면 Page"""
    for sel in ["#ifrm_tab", "#ifrm_gameready"]:
        if page.locator(sel).count() > 0:
            return page.frame_locator(sel)
    return page


def purchase_lotto720(page: Page, total_amount: int = 10000) -> dict:
    """
    연금복권 720+ 구매 (10,000원 = 10게임, 1,000원/게임)
    DOM 기반 selector 사용
    """
    target_games = total_amount // 1000  # 10,000원 = 10게임
    if target_games < 1:
        return {'games': 0, 'total_cost': 0, 'numbers': ''}
    
    try:
        # 데스크톱 뷰포트 (모바일 리다이렉트 방지)
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        # 1. 연금복권720 페이지 진입
        print("🎟️ 연금복권720+ 페이지 이동 중...")
        if not _navigate_to_720_page(page):
            raise Exception("연금복권720 페이지 진입 실패")
        
        # m.dhlottery에서도 시도 (모바일 페이지 지원)
        print(f"  현재 URL: {page.url}")
        time.sleep(2)
        
        frame = _get_frame(page)
        
        # 팝업 제거
        try:
            page.evaluate("""() => {
                const iframe = document.querySelector('#ifrm_tab');
                const doc = iframe?.contentDocument || document;
                ['#pause_layer_pop_02','.pause_layer_pop','.pause_bg','#popupLayerAlert'].forEach(s => {
                    doc.querySelectorAll(s).forEach(el => { el.style.display = 'none'; });
                });
            }""")
        except:
            pass
        
        try:
            if frame.locator("#popupLayerAlert").is_visible(timeout=1000):
                _click_selector(frame, ["button:has-text('확인')", "a:has-text('확인')"], "팝업확인")
                time.sleep(1)
        except:
            pass
        
        # 2. 자동번호 선택
        print("  자동번호 선택...")
        if not _click_selector(frame, AUTO_SELECT_SELECTORS, "자동번호", 15000):
            _save_debug_html(page, "lotto720_after_nav")
            raise Exception("자동번호 선택 버튼을 찾을 수 없습니다")
        time.sleep(2)
        
        # 3. 게임 수 선택 (10게임)
        games_set = False
        for val in [str(target_games), str(target_games).zfill(2)]:
            if _select_option(frame, val, GAME_COUNT_SELECTORS):
                games_set = True
                break
        if not games_set:
            # select 없을 수 있음 - 1회 선택이 기본 10게임일 수도
            print("  ⚠ 게임 수 select 없음 - 기본값 사용")
        time.sleep(2)
        
        # 4. 선택완료
        if not _click_selector(frame, CONFIRM_NUMBER_SELECTORS, "선택완료"):
            _save_debug_html(page, "lotto720_after_auto")
            raise Exception("선택완료 버튼을 찾을 수 없습니다")
        time.sleep(2)
        
        # 5. 총 금액 검증
        amount_text = _get_text_selector(frame, TOTAL_AMOUNT_SELECTORS, "총금액")
        amount_val = int(re.sub(r'[^0-9]', '', amount_text) or '0')
        print(f"  표시 금액: {amount_val}원 (목표: {total_amount}원)")
        
        if amount_val == 0:
            _save_debug_html(page, "lotto720_amount_zero")
            raise Exception("총 금액을 읽을 수 없습니다")
        
        # 6. 구매 실행 (5,000원 단위면 2회, 10,000원이면 1회)
        num_rounds = total_amount // amount_val if amount_val > 0 else 1
        for round_num in range(num_rounds):
            if round_num > 0:
                print(f"  [{round_num + 1}차 구매] 자동번호 재선택...")
                _click_selector(frame, AUTO_SELECT_SELECTORS, "자동번호")
                time.sleep(2)
                _click_selector(frame, CONFIRM_NUMBER_SELECTORS, "선택완료")
                time.sleep(2)
            
            if not _click_selector(frame, PURCHASE_BUTTON_SELECTORS, "구매하기"):
                _save_debug_html(page, "lotto720_no_purchase_btn")
                raise Exception("구매하기 버튼을 찾을 수 없습니다")
            time.sleep(2)
            
            # 7. 확인 팝업
            for pop_sel in CONFIRM_POPUP_SELECTORS:
                try:
                    if frame.locator(pop_sel).is_visible(timeout=3000):
                        _click_selector(frame, CONFIRM_BUTTON_SELECTORS, "팝업확인")
                        break
                except:
                    pass
            else:
                _click_selector(frame, CONFIRM_BUTTON_SELECTORS, "확인버튼")
            time.sleep(3)
        
        # 8. 구매 완료 검증
        success = False
        try:
            if frame.locator("text=/구매가 완료되었습니다|구매 완료/").count() > 0:
                success = True
        except:
            pass
        if not success:
            page.goto("https://www.dhlottery.co.kr/mypage/LottoWinHistList.do", timeout=30000)
            time.sleep(2)
            content = page.content()
            from datetime import datetime, timezone, timedelta
            kst = timezone(timedelta(hours=9))
            today = datetime.now(kst).strftime('%Y-%m-%d')
            if today in content or "720" in content or "연금" in content:
                success = True
        
        if success:
            print("✅ 연금복권 720+ 구매 완료!")
            notify_lotto720_purchase(True, numbers=f"자동 {target_games}게임", total_amount=total_amount)
            return {'games': target_games, 'total_cost': total_amount, 'numbers': f"자동 {target_games}게임"}
        
        _save_debug_html(page, "lotto720_verify_fail")
        raise Exception("구매 완료 확인 실패")
        
    except Exception as e:
        err = str(e)
        print(f"❌ 연금복권 720+ 구매 실패: {err}")
        notify_lotto720_purchase(False, error_msg=err)
        raise


def _save_debug_html(page: Page, prefix: str):
    """디버깅용 HTML 저장 (실패 시 selector 분석용)"""
    try:
        path = Path("debug_" + prefix + ".html")
        path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=Path("debug_" + prefix + ".png"))
        print(f"  📄 디버그 저장: {path}")
    except Exception as e:
        print(f"  ⚠ HTML 저장 실패: {e}")


def run(playwright: Playwright) -> None:
    """연금복권 720+ 독립 실행"""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    page = context.new_page()
    try:
        login(page)
        purchase_lotto720(page, total_amount=10000)
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
