#!/usr/bin/env python3
"""
예치금 잔액 조회.

[수정 이력]
- 미사용 import (Path, load_dotenv) 제거
- 디버그 산출물을 DEBUG 플래그로 게이팅하고 debug/ 로 격리
- print → logging
- bare except 제거
"""
import re
import time

from playwright.sync_api import (
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from applog import get_logger
from config import debug_path, env_bool, load_settings
from login import login

log = get_logger(__name__)

MYPAGE_URL = "https://www.dhlottery.co.kr/mypage/home"

DEPOSIT_SELECTORS = (
    "#totalAmt",
    "[id='totalAmt']",
    "span#totalAmt",
    ".total_amt",
    "//span[@id='totalAmt']",
)

AVAILABLE_SELECTORS = (
    "#divCrntEntrsAmt",
    "[id='divCrntEntrsAmt']",
    "div#divCrntEntrsAmt",
    ".crnt_entrs_amt",
    "//div[@id='divCrntEntrsAmt']",
)


def _parse_amount(text: str) -> int | None:
    """'12,345원' → 12345. 숫자가 없으면 None."""
    digits = re.sub(r"[^0-9]", "", text or "")
    if not digits:
        return None
    return int(digits)


def find_element_with_retry(
    page: Page,
    selectors: list[str],
    element_name: str,
    max_retries: int = 3,
) -> str:
    """여러 셀렉터를 시도하며 요소 텍스트를 찾습니다."""
    for attempt in range(max_retries):
        if attempt > 0:
            log.info("재시도 %s/%s: %s", attempt, max_retries - 1, element_name)
            try:
                page.reload(wait_until="networkidle", timeout=30000)
            except PlaywrightTimeoutError:
                log.debug("reload networkidle 타임아웃")
            time.sleep(3)

        for selector in selectors:
            try:
                element = page.locator(selector)
                element.wait_for(state="attached", timeout=10000)
                if element.count() == 0:
                    continue
                text = element.first.inner_text(timeout=5000).strip()
                if text:
                    log.debug("%s 발견: %s = '%s'", element_name, selector, text)
                    return text
                log.debug("요소는 있으나 텍스트 없음: %s", selector)
            except PlaywrightTimeoutError:
                log.debug("타임아웃: %s", selector)
            except Exception as exc:
                log.debug("셀렉터 오류 (%s): %s", selector, exc)

    raise RuntimeError(f"{element_name}을(를) 찾을 수 없습니다. 모든 셀렉터/재시도 실패.")


def get_balance(page: Page, debug: bool | None = None) -> dict[str, int]:
    """
    마이페이지에서 예치금 잔액과 구매가능 금액을 조회합니다.

    Returns:
        {'deposit_balance': int, 'available_amount': int}
    """
    want_debug = env_bool("DEBUG", False) if debug is None else debug

    log.info("마이페이지로 이동 중...")
    page.goto(MYPAGE_URL, timeout=60000, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except PlaywrightTimeoutError:
        log.warning("마이페이지 networkidle 타임아웃, 계속 진행")

    time.sleep(3)

    if want_debug:
        try:
            page.screenshot(path=debug_path("mypage.png"))
            with open(debug_path("mypage.html"), "w", encoding="utf-8") as fp:
                fp.write(page.content())
            log.debug("마이페이지 디버그 산출물 저장")
        except Exception as exc:
            log.debug("마이페이지 디버그 저장 실패: %s", exc)

    log.debug("현재 URL: %s", page.url)

    deposit_text = find_element_with_retry(page, list(DEPOSIT_SELECTORS), "예치금 잔액")
    available_text = find_element_with_retry(page, list(AVAILABLE_SELECTORS), "구매가능 금액")

    deposit_balance = _parse_amount(deposit_text)
    available_amount = _parse_amount(available_text)

    if deposit_balance is None:
        raise RuntimeError(f"예치금 잔액을 숫자로 변환할 수 없습니다: '{deposit_text}'")
    if available_amount is None:
        raise RuntimeError(f"구매가능 금액을 숫자로 변환할 수 없습니다: '{available_text}'")

    log.info("예치금 잔액: %s원 / 구매가능: %s원", f"{deposit_balance:,}", f"{available_amount:,}")

    return {
        "deposit_balance": deposit_balance,
        "available_amount": available_amount,
    }


def get_balance_resilient(page: Page, attempts: int = 3, debug: bool | None = None) -> dict[str, int]:
    """
    세션이 끊긴 경우 재로그인하며 잔액을 조회합니다.
    """
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return get_balance(page, debug=debug)
        except Exception as exc:
            last_error = exc
            log.warning("잔액 조회 실패 (%s/%s): %s", attempt, attempts, exc)
            if attempt >= attempts:
                break
            try:
                log.info("세션 복구를 위해 재로그인 시도")
                page.goto("https://www.dhlottery.co.kr/main", timeout=60000, wait_until="domcontentloaded")
                login(page, max_retries=2, debug=debug)
            except Exception as relogin_error:
                log.warning("재로그인 실패: %s", relogin_error)
            time.sleep(2)

    raise RuntimeError(f"잔액 조회 최종 실패: {last_error}")


def run(playwright: Playwright) -> dict[str, int]:
    """로그인 후 잔액 정보를 조회합니다 (독립 실행용)."""
    settings = load_settings()

    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    try:
        login(page, debug=settings.debug)
        balance_info = get_balance(page, debug=settings.debug)

        from telegram_notifier import notify_balance

        notify_balance(balance_info["deposit_balance"], balance_info["available_amount"])
        return balance_info
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
