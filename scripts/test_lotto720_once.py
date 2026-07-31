#!/usr/bin/env python3
"""텔레그램 선확인 후 720+ 최소 5,000원만 실구매하는 일회성 점검."""
import sys
import time

from playwright.sync_api import sync_playwright

from applog import get_logger
from balance import get_balance_resilient
from config import PER_720_PURCHASE_AMOUNT, load_settings
from login import login
from lotto720 import purchase_lotto720
from telegram_notifier import (
    is_configured,
    notify_error,
    notify_lotto720_purchase,
    send_telegram_message,
)

log = get_logger(__name__)
AMOUNT = PER_720_PURCHASE_AMOUNT
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def main() -> int:
    settings = load_settings()
    if not settings.user_id or not settings.passwd:
        log.error("USER_ID/PASSWD 미설정")
        return 2
    if not is_configured():
        log.error("텔레그램 미설정 — 안전상 구매 중단")
        return 3

    if not send_telegram_message(
        "🔁 <b>720+ 실구매 재테스트 시작</b>\n\n"
        "로그인: 브라우저 + RSA fallback\n"
        "구매액: 5,000원\n자동 충전: 안 함\n6/45: 안 함"
    ):
        log.error("텔레그램 사전 알림 실패 — 안전상 구매 중단")
        return 4

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, user_agent=USER_AGENT
        )
        page = context.new_page()
        try:
            login(
                page,
                user_id=settings.user_id,
                passwd=settings.passwd,
                debug=True,
            )
            before = get_balance_resilient(page, debug=True)["available_amount"]
            if before < AMOUNT:
                reason = (
                    f"구매가능 잔액 부족: {before:,}원. "
                    "자동 충전 없이 테스트를 종료합니다."
                )
                notify_lotto720_purchase(False, error_msg=reason)
                return 5

            result = purchase_lotto720(page, AMOUNT, debug=True, dry_run=False)
            time.sleep(2)
            after = get_balance_resilient(page, debug=True)["available_amount"]
            spent = before - after

            if spent >= AMOUNT:
                evidence = f"예치금 차감 {spent:,}원"
                if result.success_signals:
                    evidence += f" + 화면 성공신호 {result.success_signals}회"
                notify_lotto720_purchase(
                    True,
                    tickets=result.tickets or None,
                    amount=spent,
                    purchase_count=max(1, spent // AMOUNT),
                    verified_by=evidence,
                )
                return 0

            reason = (
                f"예치금 차감 미확인: {before:,}원 → {after:,}원 "
                f"(차감 {spent:,}원, 화면 성공신호 {result.success_signals}회)"
            )
            notify_lotto720_purchase(False, error_msg=reason)
            return 6
        except Exception as exc:
            log.exception("720+ 재테스트 오류: %s", exc)
            notify_error(f"720+ 실구매 재테스트 오류: {type(exc).__name__}: {exc}")
            return 1
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
