#!/usr/bin/env python3
"""
연금복권 720+ 자동 구매
"""
import time
import re
from os import environ
from playwright.sync_api import Playwright, sync_playwright, Page
from login import login

PER_PURCHASE_AMOUNT = 5000
DEFAULT_TARGET_AMOUNT = 10000


def _get_target_amount(target_amount: int = None) -> int:
    """구매 목표 금액을 정규화합니다."""
    if target_amount is None:
        raw = environ.get("LOTTO720_AMOUNT", str(DEFAULT_TARGET_AMOUNT))
        try:
            target_amount = int(str(raw).replace(",", "").strip())
        except Exception:
            target_amount = DEFAULT_TARGET_AMOUNT

    if target_amount <= 0:
        raise ValueError("LOTTO720_AMOUNT는 0보다 커야 합니다.")
    if target_amount % PER_PURCHASE_AMOUNT != 0:
        raise ValueError(
            f"LOTTO720_AMOUNT는 {PER_PURCHASE_AMOUNT:,}원 단위여야 합니다. (입력: {target_amount:,}원)"
        )
    return target_amount


def _click_first(target, selectors: list, label: str, timeout: int = 5000, force: bool = False) -> str:
    """여러 셀렉터를 순차 시도하여 첫 클릭 가능한 요소를 클릭합니다."""
    for selector in selectors:
        try:
            el = target.locator(selector)
            if el.count() > 0:
                el.first.click(timeout=timeout, force=force)
                return selector
        except Exception:
            continue
    raise Exception(f"{label} 요소를 찾지 못했습니다: {selectors}")


def _click_keyword(target, keywords: list, label: str, timeout: int = 5000) -> str:
    """
    키워드 기반으로 버튼/링크/입력을 찾아 클릭합니다.
    """
    selector_candidates = []
    for kw in keywords:
        selector_candidates.extend(
            [
                f"button:has-text('{kw}')",
                f"a:has-text('{kw}')",
                f"label:has-text('{kw}')",
                f"input[value*='{kw}']",
                f"[title*='{kw}']",
                f"[aria-label*='{kw}']",
            ]
        )

    for selector in selector_candidates:
        try:
            el = target.locator(selector)
            if el.count() > 0 and el.first.is_visible(timeout=1200):
                el.first.click(timeout=timeout, force=True)
                return selector
        except Exception:
            continue

    # Final fallback: DOM 직접 탐색 클릭
    for kw in keywords:
        try:
            clicked = target.evaluate(
                """
                (keyword) => {
                    const nodes = Array.from(document.querySelectorAll("button,a,label,input,span,div"));
                    const norm = (s) => (s || "").replace(/\\s+/g, " ").trim();
                    const lower = keyword.toLowerCase();
                    for (const n of nodes) {
                        const text = norm(n.textContent);
                        const value = norm(n.value);
                        const title = norm(n.getAttribute("title"));
                        const onclick = norm(n.getAttribute("onclick"));
                        const blob = `${text} ${value} ${title} ${onclick}`.toLowerCase();
                        if (!blob.includes(lower)) continue;
                        if (n.offsetParent === null && !["INPUT"].includes(n.tagName)) continue;
                        try { n.click(); return true; } catch (_) {}
                    }
                    return false;
                }
                """,
                kw,
            )
            if clicked:
                return f"dom-keyword:{kw}"
        except Exception:
            continue

    raise Exception(f"{label} 키워드 클릭 실패: {keywords}")


def _read_amount(target) -> int:
    """결제 금액 텍스트를 읽어 숫자로 변환합니다."""
    selectors = [
        ".lotto720_price.lpcurpay",
        ".lotto720_price",
        ".lpcurpay",
        "#buyAmount",
        "[class*='price']",
    ]
    for selector in selectors:
        try:
            el = target.locator(selector)
            if el.count() == 0:
                continue
            text = el.first.inner_text(timeout=3000).strip()
            amount = int(re.sub(r"[^0-9]", "", text) or "0")
            if amount > 0:
                return amount
        except Exception:
            continue
    return 0


def _read_balance(target) -> int:
    """
    화면 내 잔액 정보를 가능한 셀렉터에서 읽어옵니다.
    """
    selectors = [
        "#curdeposit",
        "#crntEntrsAmt",
        ".lpdeposit",
        "[id*='EntrsAmt']",
        "[class*='deposit']",
    ]

    for selector in selectors:
        try:
            el = target.locator(selector)
            if el.count() == 0:
                continue
            first = el.first

            # input hidden/value 계열
            try:
                value = first.get_attribute("value")
                if value:
                    amount = int(re.sub(r"[^0-9]", "", value) or "0")
                    if amount > 0:
                        return amount
            except Exception:
                pass

            # 일반 텍스트
            try:
                text = first.inner_text(timeout=1000).strip()
                amount = int(re.sub(r"[^0-9]", "", text) or "0")
                if amount > 0:
                    return amount
            except Exception:
                pass
        except Exception:
            continue
    return -1


def _has_failure_signal(target) -> bool:
    # 너무 넓은 패턴(예: '한도', '.alert')은 오탐이 많아 제외
    failure_selectors = [
        "text=/구매.*실패/",
        "text=/결제.*실패/",
        "text=/잔액.*부족/",
        "text=/서비스.*점검/",
        "text=/이용.*불가/",
    ]
    for selector in failure_selectors:
        try:
            if target.locator(selector).first.is_visible(timeout=1200):
                return True
        except Exception:
            continue
    return False


def _dump_interactive_labels(target, label: str) -> None:
    """
    디버깅용: 현재 화면의 주요 버튼/링크 텍스트를 출력합니다.
    """
    try:
        rows = target.evaluate(
            """
            () => {
                const nodes = Array.from(document.querySelectorAll("button,a,input[type='button'],input[type='submit'],label"));
                const norm = (s) => (s || "").replace(/\\s+/g, " ").trim();
                return nodes.slice(0, 120).map(n => {
                    const text = norm(n.textContent) || norm(n.value);
                    const id = n.id || "";
                    const cls = n.className || "";
                    const onclick = n.getAttribute("onclick") || "";
                    return `${text} | id=${id} | class=${cls} | onclick=${onclick}`.trim();
                }).filter(Boolean);
            }
            """
        )
        print(f"  [DEBUG:{label}] interactive candidates:")
        for row in rows[:40]:
            print(f"    - {row}")
    except Exception as e:
        print(f"  [DEBUG:{label}] interactive dump failed: {e}")


def _get_frame(page: Page):
    """720 화면이 iframe인지 직접 페이지인지 감지하여 반환합니다."""
    iframe_exists = page.locator("#ifrm_tab").count() > 0
    if iframe_exists:
        return page.frame_locator("#ifrm_tab")
    return page


def _navigate_to_lotto720(page: Page):
    """720 게임 화면으로 이동합니다."""
    desktop_urls = [
        "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72",
        "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72&kind=1",
    ]

    last_url = ""
    mobile_detected = False
    for idx, url in enumerate(desktop_urls, 1):
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(2)

        last_url = page.url
        print(f"  현재 URL (시도 {idx}): {last_url}")
        if "m.dhlottery.co.kr" in last_url:
            mobile_detected = True
            print("  ℹ️ 모바일 페이지로 이동됨 - 모바일 화면으로 계속 진행")
            break
        else:
            frame = _get_frame(page)
            frame.locator("body").first.wait_for(state="attached", timeout=15000)
            return frame

        # 모바일로 이동된 경우 데스크톱 URL로 재진입 시도
        print("  ⚠️ 모바일 리다이렉트 감지, 데스크톱 URL 재시도")

    if mobile_detected:
        page.locator("body").first.wait_for(state="attached", timeout=15000)

        # 모바일 메인에서 720 바로구매 버튼 클릭 시도
        try:
            mobile_direct_selectors = [
                "#pt720ImdtPrchs",
                "#btnMoPtgmPrchs",
                ".btnBuyPt720",
                "a:has-text('연금복권720+')",
                "button:has-text('연금복권720+')",
            ]
            for selector in mobile_direct_selectors:
                try:
                    el = page.locator(selector)
                    if el.count() > 0:
                        el.first.click(timeout=3000, force=True)
                        page.wait_for_load_state("domcontentloaded", timeout=20000)
                        time.sleep(2)
                        if "game_mobile/pension720" in page.url:
                            print(f"  ✅ 모바일 720 구매 페이지 진입: {page.url}")
                            return page
                except Exception:
                    continue
        except Exception:
            pass

        # 직접 URL 진입 fallback
        mobile_urls = [
            "https://el.dhlottery.co.kr/game_mobile/pension720/game.jsp",
            "https://m.dhlottery.co.kr/game_mobile/pension720/game.jsp",
        ]
        for murl in mobile_urls:
            try:
                page.goto(murl, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=20000)
                time.sleep(2)
                if "pension720" in page.url:
                    print(f"  ✅ 모바일 720 URL 직접 진입 성공: {page.url}")
                    return page
            except Exception:
                continue

        # 실패 시 현재 페이지 반환 (상위 로직에서 디버그 덤프/검증)
        return page

    raise Exception(f"연금복권 페이지 진입 실패 ({last_url})")


def _purchase_once(page: Page) -> dict:
    """연금복권 720+를 1회(5,000원) 구매합니다."""
    frame = _navigate_to_lotto720(page)

    # 로그인 세션 확인 (필드가 있을 때만 검사)
    try:
        user_id_field = frame.locator("input[name='USER_ID']")
        if user_id_field.count() > 0:
            user_id_val = user_id_field.first.get_attribute("value")
            if not user_id_val:
                raise Exception("세션 만료")
    except Exception as e:
        raise Exception(f"게임 페이지 로그인 확인 실패: {e}")

    # 팝업 닫기 시도
    try:
        alert_popup = frame.locator("#popupLayerAlert")
        if alert_popup.count() > 0 and alert_popup.first.is_visible(timeout=1500):
            _click_first(alert_popup, ["button:has-text('확인')", "input[value='확인']", "a:has-text('확인')"], "팝업 확인")
    except Exception:
        pass

    # 구매 전 잔액(가능하면)
    balance_before = _read_balance(frame)

    # 자동번호 -> 선택완료
    try:
        _click_first(
            frame,
            [
                ".lotto720_btn_auto_number",
                "a:has-text('자동번호')",
                "button:has-text('자동번호')",
                "[class*='auto']",
                "[id*='auto']",
                "[onclick*='auto']",
                "[onclick*='Auto']",
            ],
            "자동번호 버튼",
            force=True,
        )
    except Exception:
        _dump_interactive_labels(frame, "auto-button-fallback")
        _click_keyword(frame, ["자동번호", "자동선택", "자동"], "자동번호 버튼")

    time.sleep(1)
    try:
        _click_first(
            frame,
            [
                ".lotto720_btn_confirm_number",
                "a:has-text('선택완료')",
                "button:has-text('선택완료')",
                "[onclick*='confirm']",
                "[onclick*='Confirm']",
            ],
            "선택완료 버튼",
        )
    except Exception:
        _dump_interactive_labels(frame, "confirm-button-fallback")
        _click_keyword(frame, ["선택완료", "선택 완료", "완료", "확인"], "선택완료 버튼")
    time.sleep(1)

    payment_val = _read_amount(frame)
    if payment_val == 0:
        print("  ⚠️ 결제 금액 표시를 읽지 못했습니다. 구매 절차를 계속 진행합니다.")
    elif payment_val != PER_PURCHASE_AMOUNT:
        raise Exception(f"결제 금액 불일치 (예상 {PER_PURCHASE_AMOUNT}원, 표시 {payment_val}원)")

    # 구매하기 -> 최종 확인
    try:
        _click_first(
            frame,
            [
                "a:has-text('구매하기')",
                "button:has-text('구매하기')",
                ".lotto720_btn_buy",
                "[name='btnBuy']",
                "button[name='btnBuy']",
                "[onclick*='buy']",
                "[onclick*='Buy']",
            ],
            "구매하기 버튼",
        )
    except Exception:
        _dump_interactive_labels(frame, "buy-button-fallback")
        _click_keyword(frame, ["구매하기", "구매"], "구매하기 버튼")
    time.sleep(1)

    # 확인 팝업 처리
    confirm_candidates = [
        "#lotto720_popup_confirm a.btn_blue",
        "#lotto720_popup_confirm a:has-text('확인')",
        "button:has-text('확인')",
        "input[value='확인']",
    ]
    try:
        _click_first(frame, confirm_candidates, "최종 확인 버튼", timeout=7000)
    except Exception:
        _dump_interactive_labels(frame, "final-confirm-fallback")
        _click_keyword(frame, ["확인", "결제", "구매"], "최종 확인 버튼")
    time.sleep(3)

    # 구매 후 잔액(가능하면)
    balance_after = _read_balance(frame)

    # 구매 완료 메시지 확인 (모바일/데스크톱 공통 키워드)
    success = False
    success_selectors = [
        "text=/구매.*완료/",
        "text=/구매.*성공/",
        "text=/결제.*완료/",
        ".complete",
        ".success",
        "#successMessage",
    ]
    for selector in success_selectors:
        try:
            if frame.locator(selector).first.is_visible(timeout=1500):
                success = True
                break
        except Exception:
            continue

    # 잔액 감소 확인 (5,000원 이상 감소 시 성공 판정)
    if not success and balance_before > 0 and balance_after > 0:
        if balance_before - balance_after >= PER_PURCHASE_AMOUNT:
            success = True

    if not success and _has_failure_signal(frame):
        # 모바일 UI 텍스트 오탐 가능성이 있어 즉시 실패로 종료하지 않음
        print("  ⚠️ 실패 신호 텍스트가 감지되었지만 오탐 가능성이 있어 계속 진행합니다.")

    if not success:
        # 일부 페이지는 팝업/리다이렉트로만 완료 처리됨
        try:
            current_url = page.url.lower()
            if "complete" in current_url or "confirm" in current_url or "result" in current_url:
                success = True
        except Exception:
            pass

    if not success:
        _dump_interactive_labels(frame, "verify-failed")
        raise Exception("구매 완료 검증 실패")

    return {"games": 5, "total_cost": PER_PURCHASE_AMOUNT, "numbers": "자동 선택", "verified": True}


def purchase_lotto720(page: Page, target_amount: int = None) -> dict:
    """
    연금복권 720+를 구매합니다.
    - 5,000원 단위로 반복 구매하여 목표 금액을 맞춥니다.
    """
    normalized_amount = _get_target_amount(target_amount)
    purchase_count = normalized_amount // PER_PURCHASE_AMOUNT

    total_games = 0
    total_cost = 0

    try:
        print(f"🚀 연금복권720 구매 시작 (목표 금액: ₩{normalized_amount:,}, {purchase_count}회)")

        for i in range(purchase_count):
            print(f"  [{i + 1}/{purchase_count}] 구매 진행 중...")
            result = _purchase_once(page)
            total_games += result.get("games", 0)
            total_cost += result.get("total_cost", 0)
            time.sleep(1)

        print(f"✅ 연금복권 720+ 구매 완료! (총 {total_cost:,}원)")
        numbers_text = f"자동 선택 ({purchase_count}회 구매)"
        return {"games": total_games, "total_cost": total_cost, "numbers": numbers_text, "verified": True}

    except Exception as e:
        error_msg = str(e)
        print(f"❌ 연금복권 720+ 구매 실패: {error_msg}")
        raise


def run(playwright: Playwright) -> None:
    """연금복권 720+를 구매합니다 (독립 실행용)."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    page = context.new_page()

    try:
        login(page)
        purchase_lotto720(page)
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
