#!/usr/bin/env python3
"""
로또 통합 자동 구매 오케스트레이터.

단일 브라우저 세션 / 단일 로그인으로 전체 작업을 수행합니다.

================================================================
[실행 순서 — 중요 수정]
================================================================
기존 순서:  로그인 → 당첨확인 → 645 구매 → 720 구매 → 잔액확인/충전
문제:       잔액이 부족하면 645/720 양쪽 구매가 모두 실패하고,
            충전은 '다음 주'를 위해서만 이뤄졌습니다.
            자동화의 목적 자체가 깨지는 순서였습니다.
            (README 에는 충전이 먼저라고 문서화되어 있었으나 코드는 반대)

수정 순서:  로그인 → 당첨확인 → 잔액확인 → (부족하면) 충전 → 재확인
            → 645 구매 → 720 구매 → 결과 요약
================================================================
"""
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from playwright.sync_api import Page, Playwright, sync_playwright

from applog import get_logger, section
from balance import get_balance_resilient
from charge import charge_balance
from check_results import build_and_notify, get_latest_draw, get_my_lotto_purchases
from config import (
    LOTTO645_PRICE_PER_GAME,
    PER_720_PURCHASE_AMOUNT,
    Settings,
    load_settings,
)
from login import login
from lotto645 import purchase_lotto645
from lotto720 import purchase_lotto720
from number_strategy import (
    describe_portfolio,
    generate_portfolio,
    strategy_disclaimer,
)
from telegram_notifier import (
    notify_balance,
    notify_charge,
    notify_complete,
    notify_dry_run,
    notify_error,
    notify_limit_exceeded,
    notify_lotto645_purchase,
    notify_lotto720_purchase,
    notify_skipped,
    notify_start,
)

log = get_logger(__name__)

KST = timezone(timedelta(hours=9))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------- 실행 요약


@dataclass
class RunSummary:
    """실행 결과 요약 (완료 알림에 사용)."""

    lines: list[str] = field(default_factory=list)
    had_failure: bool = False

    def add(self, message: str) -> None:
        self.lines.append(message)
        log.info("요약 항목: %s", message)

    def fail(self, message: str) -> None:
        self.lines.append(message)
        self.had_failure = True
        log.warning("요약 항목(실패): %s", message)


# ---------------------------------------------------------------- 날짜 게이팅


def is_lotto645_date_open(settings: Settings, now: datetime | None = None) -> bool:
    """
    LOTTO645_ENABLE_FROM (KST, YYYY-MM-DD) 이후인지 확인합니다.
    값이 없으면 항상 True.
    """
    raw = (settings.lotto645_enable_from or "").strip()
    if not raw:
        return True

    try:
        threshold = date.fromisoformat(raw)
    except ValueError:
        log.warning("LOTTO645_ENABLE_FROM 형식이 잘못되었습니다(%s). 게이팅을 무시합니다.", raw)
        return True

    today = (now or datetime.now(KST)).date()
    if today < threshold:
        log.info("6/45 구매 시작일(%s) 이전입니다. 오늘: %s", threshold, today)
        return False
    return True


# ---------------------------------------------------------------- 단계별 작업


def step_notify_previous_draw(page: Page, settings: Settings, summary: RunSummary) -> None:
    """이전 회차 당첨번호와 내 구매번호를 대조하여 알림을 보냅니다."""
    section(log, "당첨번호 확인 및 대조")

    try:
        draw = get_latest_draw()
    except Exception as exc:
        log.warning("당첨번호 조회 실패: %s", exc)
        summary.add("당첨번호 조회 실패 (구매는 계속 진행)")
        return

    try:
        purchases = get_my_lotto_purchases(page, debug=settings.debug)
    except Exception as exc:
        log.warning("구매내역 조회 실패: %s", exc)
        purchases = []

    try:
        results = build_and_notify(draw, purchases, purchase_lookup_failed=not purchases)
        winners = [r for r in results if r.rank]
        if winners:
            detail = ", ".join(f"{r.rank}등" for r in winners)
            summary.add(f"{draw.round_num}회 당첨: {detail}")
        elif results:
            summary.add(f"{draw.round_num}회 미당첨 ({len(results)}게임 대조)")
        else:
            summary.add(f"{draw.round_num}회 구매내역 없음")
    except Exception as exc:
        log.warning("당첨 결과 알림 실패: %s", exc)


def step_ensure_balance(page: Page, settings: Settings, summary: RunSummary) -> int:
    """
    잔액을 확인하고 부족하면 충전합니다.

    [핵심 수정] 이 단계가 구매보다 '먼저' 실행됩니다.

    Returns:
        구매 가능 금액 (조회 실패 시 -1)
    """
    section(log, "잔액 확인 및 충전")

    required = settings.required_balance
    log.info("이번 회차 필요 금액: %s원", f"{required:,}")

    try:
        info = get_balance_resilient(page, debug=settings.debug)
    except Exception as exc:
        log.error("잔액 조회 실패: %s", exc)
        summary.fail(f"잔액 조회 실패: {exc}")
        return -1

    deposit = info["deposit_balance"]
    available = info["available_amount"]

    notify_balance(deposit, available, required=required)
    summary.add(f"잔액 확인: 구매가능 {available:,}원 (필요 {required:,}원)")

    if available >= required:
        log.info("잔액이 충분합니다.")
        return available

    shortfall = required - available
    log.warning("잔액 부족: %s원 부족", f"{shortfall:,}")

    if settings.dry_run:
        log.warning("DRY_RUN: 충전을 실행하지 않습니다.")
        summary.add("DRY_RUN: 충전 생략")
        return available

    # 부족액을 메울 수 있을 만큼 반복 충전 (허용 단위가 고정되어 있으므로)
    charged_total = 0
    max_charges = 5
    for attempt in range(1, max_charges + 1):
        log.info(
            "충전 시도 %s/%s: %s원",
            attempt,
            max_charges,
            f"{settings.charge_amount:,}",
        )
        try:
            ok = charge_balance(
                page,
                settings.charge_amount,
                charge_pin=settings.charge_pin or None,
                debug=settings.debug,
            )
        except Exception as exc:
            log.error("충전 중 오류: %s", exc)
            notify_charge(settings.charge_amount, False, str(exc))
            summary.fail(f"충전 실패: {exc}")
            break

        notify_charge(settings.charge_amount, ok)

        if not ok:
            summary.fail("충전 실패 (다음 회차 전 확인 필요)")
            break

        charged_total += settings.charge_amount
        log.info("충전 완료 누적: %s원", f"{charged_total:,}")

        time.sleep(3)
        try:
            info = get_balance_resilient(page, debug=settings.debug)
            available = info["available_amount"]
            log.info("충전 후 구매가능: %s원", f"{available:,}")
        except Exception as exc:
            log.warning("충전 후 잔액 재조회 실패: %s", exc)
            break

        if available >= required:
            break

    if charged_total:
        summary.add(f"충전 완료: {charged_total:,}원 → 구매가능 {available:,}원")

    if available < required:
        log.warning(
            "충전 후에도 잔액이 부족합니다 (%s원 < %s원). 가능한 범위에서 구매를 시도합니다.",
            f"{available:,}",
            f"{required:,}",
        )

    return available


def step_purchase_lotto645(
    page: Page, settings: Settings, available: int, summary: RunSummary
) -> None:
    """로또 6/45 를 구매합니다 (전략 번호 포함)."""
    if not settings.enable_lotto645:
        log.info("6/45 구매가 비활성화되어 있습니다 (ENABLE_LOTTO645=0).")
        notify_skipped("로또 6/45", "ENABLE_LOTTO645=0 으로 비활성화되어 있습니다.")
        summary.add("6/45 건너뜀 (비활성)")
        return

    if not is_lotto645_date_open(settings):
        reason = f"구매 시작일({settings.lotto645_enable_from}, KST) 이전입니다."
        notify_skipped("로또 6/45", reason)
        summary.add(f"6/45 건너뜀 ({reason})")
        return

    section(log, "로또 6/45 구매")

    # 번호 구성: 전략 번호 + 수동 번호 + 자동
    manual_numbers = list(settings.manual_numbers)
    strategy_note: str | None = None
    strategy_count = 0

    if settings.strategy_games > 0:
        log.info("기댓값 최적화 번호 %s게임 생성 중...", settings.strategy_games)
        portfolio = generate_portfolio(
            settings.strategy_games,
            seed=settings.strategy_seed,
            exclude=manual_numbers,
        )
        if len(portfolio.sets) < settings.strategy_games:
            log.warning(
                "요청 %s게임 중 %s게임만 생성되었습니다.",
                settings.strategy_games,
                len(portfolio.sets),
            )
        log.info("생성 결과:\n%s", describe_portfolio(portfolio))
        log.info(strategy_disclaimer())
        manual_numbers = manual_numbers + portfolio.sets
        strategy_count = len(portfolio.sets)
        strategy_note = strategy_disclaimer()

    total_games = settings.auto_games + len(manual_numbers)
    if total_games == 0:
        log.warning("구매할 6/45 게임이 없습니다. (AUTO_GAMES / STRATEGY_GAMES / MANUAL_NUMBERS 확인)")
        summary.add("6/45 건너뜀 (구매할 게임 없음)")
        return

    cost = total_games * LOTTO645_PRICE_PER_GAME
    if available >= 0 and available < cost:
        reason = f"잔액 부족 (필요 {cost:,}원 / 가능 {available:,}원)"
        log.warning("6/45 구매 건너뜀: %s", reason)
        notify_skipped("로또 6/45", reason)
        summary.fail(f"6/45 건너뜀 ({reason})")
        return

    try:
        result = purchase_lotto645(
            page,
            auto_games=settings.auto_games,
            manual_numbers=manual_numbers,
            debug=settings.debug,
            dry_run=settings.dry_run,
        )
    except Exception as exc:
        message = str(exc)
        if "구매 불가" in message:
            log.info("정상적인 구매 불가 시간대입니다: %s", message)
            notify_skipped("로또 6/45", message)
            summary.add(f"6/45 건너뜀 ({message})")
            return
        if any(marker in message for marker in ("Timeout", "ERR_CONNECTION", "net::ERR_")):
            log.warning("접속 지연/타임아웃으로 6/45 를 건너뜁니다: %s", message)
            notify_skipped("로또 6/45", f"접속 장애로 건너뜀: {message[:200]}")
            summary.fail("6/45 건너뜀 (접속 장애)")
            return
        log.exception("6/45 구매 실패: %s", message)
        notify_lotto645_purchase(0, 0, False, error_msg=message)
        summary.fail(f"6/45 구매 실패: {message[:150]}")
        return

    if result.limit_exceeded and not result.success:
        notify_limit_exceeded()
        summary.add("6/45 주간 구매 한도 초과")
        return

    if result.skipped and result.skip_reason == "dry_run":
        summary.add("DRY_RUN: 6/45 구매 생략")
        return

    if result.success:
        notify_lotto645_purchase(
            auto_games=settings.auto_games,
            manual_games=len(settings.manual_numbers),
            strategy_games=strategy_count,
            success=True,
            numbers=result.numbers,
            strategy_note=strategy_note,
        )
        summary.add(f"6/45 구매 완료: {result.games}게임 {result.total_cost:,}원")
    else:
        reason = result.skip_reason or "구매 완료 미확인"
        notify_lotto645_purchase(0, 0, False, error_msg=reason)
        summary.fail(f"6/45 구매 미확인: {reason}")


def step_purchase_lotto720(
    page: Page, settings: Settings, summary: RunSummary
) -> None:
    """
    연금복권 720+ 를 구매하고 예치금 차감으로 검증합니다.

    화면 신호만으로는 성공을 확정할 수 없어, 구매 전후 예치금 차감액을
    권위 있는 근거로 사용합니다.
    """
    if not settings.enable_lotto720:
        log.info("720+ 구매가 비활성화되어 있습니다 (ENABLE_LOTTO720=0).")
        notify_skipped("연금복권 720+", "ENABLE_LOTTO720=0 으로 비활성화되어 있습니다.")
        summary.add("720+ 건너뜀 (비활성)")
        return

    section(log, f"연금복권 720+ 구매 (목표 {settings.lotto720_amount:,}원)")

    # 구매 전 잔액
    before: int | None = None
    try:
        before = get_balance_resilient(page, debug=settings.debug)["available_amount"]
        log.info("720+ 구매 전 구매가능: %s원", f"{before:,}")
    except Exception as exc:
        log.warning("720+ 구매 전 잔액 조회 실패: %s", exc)

    if before is not None and before < settings.lotto720_amount:
        reason = f"잔액 부족 (필요 {settings.lotto720_amount:,}원 / 가능 {before:,}원)"
        log.warning("720+ 구매 건너뜀: %s", reason)
        notify_skipped("연금복권 720+", reason)
        summary.fail(f"720+ 건너뜀 ({reason})")
        return

    try:
        result = purchase_lotto720(
            page,
            settings.lotto720_amount,
            debug=settings.debug,
            dry_run=settings.dry_run,
        )
    except Exception as exc:
        log.exception("720+ 구매 실패: %s", exc)
        notify_lotto720_purchase(False, error_msg=str(exc))
        summary.fail(f"720+ 구매 실패: {str(exc)[:150]}")
        return

    if settings.dry_run:
        summary.add("DRY_RUN: 720+ 구매 생략")
        return

    # 구매 후 잔액으로 검증
    after: int | None = None
    try:
        time.sleep(2)
        after = get_balance_resilient(page, debug=settings.debug)["available_amount"]
        log.info("720+ 구매 후 구매가능: %s원", f"{after:,}")
    except Exception as exc:
        log.warning("720+ 구매 후 잔액 조회 실패: %s", exc)

    spent: int | None = None
    if before is not None and after is not None:
        spent = before - after
        log.info("예치금 차감액: %s원", f"{spent:,}")

    verified = spent is not None and spent >= PER_720_PURCHASE_AMOUNT

    log.info(
        "720+ 판정 근거 | 화면 성공신호 %s/%s | 차감 %s",
        result.success_signals,
        settings.lotto720_purchase_count,
        f"{spent:,}원" if spent is not None else "확인 불가",
    )

    if verified:
        verified_by = f"예치금 차감 {spent:,}원"
        if result.success_signals:
            verified_by += f" + 화면 성공신호 {result.success_signals}회"

        notify_lotto720_purchase(
            True,
            tickets=result.tickets or None,
            amount=spent,
            purchase_count=max(1, spent // PER_720_PURCHASE_AMOUNT),
            verified_by=verified_by,
        )
        summary.add(f"720+ 구매 완료: {spent:,}원 ({verified_by})")

        if spent < settings.lotto720_amount:
            log.warning(
                "목표 금액(%s원)보다 적게 구매되었습니다 (%s원).",
                f"{settings.lotto720_amount:,}",
                f"{spent:,}",
            )
            summary.fail(
                f"720+ 부분 구매: 목표 {settings.lotto720_amount:,}원 중 {spent:,}원"
            )
        return

    # 검증 실패
    if spent is None:
        reason = (
            "예치금 차감을 확인할 수 없어 구매 성공을 확정하지 못했습니다. "
            "마이페이지에서 직접 확인하세요."
        )
    else:
        reason = (
            f"예치금이 차감되지 않았습니다 (차감 {spent:,}원). "
            f"구매가 실제로 이뤄지지 않은 것으로 판단합니다."
        )

    if result.success_signals:
        reason += f" (화면에는 성공신호 {result.success_signals}회가 있었습니다)"

    log.error("720+ 구매 미검증: %s", reason)
    notify_lotto720_purchase(False, error_msg=reason)
    summary.fail(f"720+ 구매 미검증: {reason[:150]}")


# ---------------------------------------------------------------- 메인


def run_all_tasks(playwright: Playwright) -> bool:
    """
    한 번의 브라우저 세션으로 모든 작업을 수행합니다.

    Returns:
        bool: 치명적 실패 없이 완료되었는지 여부
    """
    settings = load_settings()

    section(log, "로또 자동 구매 시작")
    log.info("설정:\n%s", settings.summary())

    errors = settings.validate()
    if errors:
        for error in errors:
            log.error("설정 오류: %s", error)
        notify_error("설정 오류:\n" + "\n".join(f"- {e}" for e in errors))
        return False

    if settings.dry_run:
        log.warning("DRY_RUN 모드: 실제 구매/충전을 실행하지 않습니다.")
        notify_dry_run(settings.summary())
    else:
        notify_start(settings.summary())

    summary = RunSummary()

    log.info("브라우저 시작")
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=USER_AGENT,
    )
    page = context.new_page()

    try:
        section(log, "로그인")
        login(page, user_id=settings.user_id, passwd=settings.passwd, debug=settings.debug)
        time.sleep(2)

        # 1. 이전 회차 당첨 결과 알림
        step_notify_previous_draw(page, settings, summary)

        # 2. 잔액 확인 및 충전 (구매보다 먼저!)
        available = step_ensure_balance(page, settings, summary)

        # 3. 로또 6/45 구매
        step_purchase_lotto645(page, settings, available, summary)

        # 4. 연금복권 720+ 구매
        step_purchase_lotto720(page, settings, summary)

        section(log, "전체 작업 완료")
        notify_complete(summary.lines)
        return not summary.had_failure

    except Exception as exc:
        log.exception("치명적 오류: %s", exc)
        notify_error(f"{type(exc).__name__}: {exc}")
        return False

    finally:
        try:
            context.close()
        except Exception as exc:
            log.debug("context 종료 실패: %s", exc)
        try:
            browser.close()
        except Exception as exc:
            log.debug("browser 종료 실패: %s", exc)
        log.info("브라우저 종료")


def main() -> int:
    with sync_playwright() as playwright:
        ok = run_all_tasks(playwright)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
