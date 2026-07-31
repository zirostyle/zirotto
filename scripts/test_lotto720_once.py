#!/usr/bin/env python3
"""
연금복권 720+ 최소 금액(5,000원) 일회성 실구매 점검.

안전장치:
1. 텔레그램 설정 및 테스트 전송이 성공하지 않으면 구매하지 않음
2. 구매가능 잔액이 5,000원 미만이면 구매하지 않음
3. 예치금 자동 충전을 절대 수행하지 않음
4. 6/45 구매를 수행하지 않음
5. 구매 전후 잔액 차감으로 성공 여부를 판정
"""
import sys
import time

from playwright.sync_api import sync_playwright

from applog import get_logger, section
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

TEST_AMOUNT = PER_720_PURCHASE_AMOUNT
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def main() -> int:
    settings = load_settings()
    section(log, "연금복권 720+ 일회성 최소 금액 실구매 테스트")

    if not settings.user_id or not settings.passwd:
        log.error("USER_ID 또는 PASSWD가 설정되지 않았습니다.")
        return 2

    # 텔레그램 미동작을 함께 진단한다. 알림이 안 되면 돈을 사용하지 않는다.
    if not is_configured():
        log.error(
            "TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다. "
            "안전상 실제 구매를 중단합니다."
        )
        return 3

    preflight_message = (
        "🧪 <b>연금복권 720+ 실구매 테스트 시작</b>\n\n"
        "최소 금액: 5,000원\n"
        "자동 충전: 사용 안 함\n"
        "6/45 구매: 사용 안 함\n\n"
        "이 메시지가 도착한 뒤에만 구매를 시도합니다."
    )
    if not send_telegram_message(preflight_message):
        log.error("텔레그램 사전 알림 전송에 실패했습니다. 안전상 실제 구매를 중단합니다.")
        return 4

    log.info("텔레그램 사전 알림 성공 — 구매 점검을 계속합니다.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=USER_AGENT,
        )
        page = context.new_page()

        try:
            login(
                page,
                user_id=settings.user_id,
                passwd=settings.passwd,
                debug=settings.debug,
            )

            before_info = get_balance_resilient(page, debug=settings.debug)
            before = before_info["available_amount"]
            log.info("구매 전 구매가능 금액: %s원", f"{before:,}")

            if before < TEST_AMOUNT:
                reason = (
                    f"구매가능 금액이 부족합니다: {before:,}원 < {TEST_AMOUNT:,}원. "
                    "자동 충전 없이 테스트를 종료합니다."
                )
                log.error(reason)
                notify_lotto720_purchase(False, error_msg=reason)
                return 5

            result = purchase_lotto720(
                page,
                target_amount=TEST_AMOUNT,
                debug=settings.debug,
                dry_run=False,
            )

            time.sleep(2)
            after_info = get_balance_resilient(page, debug=settings.debug)
            after = after_info["available_amount"]
            spent = before - after

            log.info(
                "구매 전/후 잔액: %s원 → %s원 (차감 %s원)",
                f"{before:,}",
                f"{after:,}",
                f"{spent:,}",
            )

            if spent >= TEST_AMOUNT:
                evidence = f"예치금 차감 {spent:,}원"
                if result.success_signals:
                    evidence += f" + 화면 성공신호 {result.success_signals}회"
                notify_lotto720_purchase(
                    True,
                    tickets=result.tickets or None,
                    amount=spent,
                    purchase_count=max(1, spent // TEST_AMOUNT),
                    verified_by=evidence,
                )
                log.info("720+ 실구매 테스트 성공: %s", evidence)
                return 0

            reason = (
                f"구매 후 예치금 차감이 확인되지 않았습니다 "
                f"(전 {before:,}원 / 후 {after:,}원 / 차감 {spent:,}원)."
            )
            if result.success_signals:
                reason += f" 화면 성공신호는 {result.success_signals}회 감지되었습니다."
            log.error(reason)
            notify_lotto720_purchase(False, error_msg=reason)
            return 6

        except Exception as exc:
            log.exception("720+ 실구매 테스트 오류: %s", exc)
            notify_error(f"720+ 실구매 테스트 오류: {type(exc).__name__}: {exc}")
            return 1
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
