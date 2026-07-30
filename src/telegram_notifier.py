#!/usr/bin/env python3
"""
텔레그램 알림 모듈.

[중요 수정 이력]
기존 구현은 모듈 import 시점에 os.environ 을 읽었습니다.
CI 는 secrets 를 .env 파일로만 기록하고 환경변수로 export 하지 않기 때문에,
notify_telegram.py 처럼 telegram_notifier 를 직접 import 하는 경로에서는
토큰이 항상 비어 있었고 send_telegram_message() 가 조용히 False 를 반환했습니다.
(로그도 남지 않아 실패를 인지할 수 없었음)

수정: 환경변수를 '함수 호출 시점'에 읽고, config.load_environment() 로
.env 를 명시적으로 로드하며, 미설정 시 경고 로그를 남깁니다.
"""
import html
from collections.abc import Sequence

import requests

from applog import get_logger
from config import env_str, load_environment

log = get_logger(__name__)

TELEGRAM_API_TIMEOUT = 10
MAX_MESSAGE_LENGTH = 4000  # 텔레그램 제한 4096, 여유 확보

_WARNED_UNCONFIGURED = False


def _credentials() -> tuple:
    """
    호출 시점에 토큰/챗ID를 읽습니다.
    (import 시점이 아니라 호출 시점인 것이 핵심 수정 사항)
    """
    load_environment()
    return env_str("TELEGRAM_BOT_TOKEN"), env_str("TELEGRAM_CHAT_ID")


def is_configured() -> bool:
    token, chat_id = _credentials()
    return bool(token and chat_id)


def _esc(value) -> str:
    """HTML parse_mode 에서 안전하도록 이스케이프."""
    return html.escape(str(value), quote=False)


def _format_numbers(numbers: Sequence[int]) -> str:
    return " ".join(f"{int(n):02d}" for n in sorted(numbers))


def send_telegram_message(message: str, parse_mode: str = "HTML") -> bool:
    """
    텔레그램으로 메시지를 전송합니다.

    Returns:
        bool: 전송 성공 여부
    """
    global _WARNED_UNCONFIGURED

    token, chat_id = _credentials()

    if not token or not chat_id:
        if not _WARNED_UNCONFIGURED:
            missing = []
            if not token:
                missing.append("TELEGRAM_BOT_TOKEN")
            if not chat_id:
                missing.append("TELEGRAM_CHAT_ID")
            log.warning(
                "텔레그램 알림이 비활성 상태입니다. 미설정 항목: %s "
                "(.env 또는 GitHub Secrets 확인 필요)",
                ", ".join(missing),
            )
            _WARNED_UNCONFIGURED = True
        return False

    if len(message) > MAX_MESSAGE_LENGTH:
        message = message[: MAX_MESSAGE_LENGTH - 40] + "\n\n... (메시지가 잘렸습니다)"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": parse_mode}

    try:
        response = requests.post(url, data=payload, timeout=TELEGRAM_API_TIMEOUT)
    except requests.RequestException as exc:
        log.warning("텔레그램 전송 실패 (네트워크): %s", exc)
        return False

    if response.status_code != 200:
        # 응답 본문에 토큰은 포함되지 않으므로 로깅해도 안전합니다.
        log.warning(
            "텔레그램 전송 실패 (HTTP %s): %s",
            response.status_code,
            response.text[:300],
        )
        return False

    return True


# ---------------------------------------------------------------- 프로세스 알림


def notify_start(settings_summary: str | None = None) -> bool:
    message = "🎰 <b>로또 자동 구매 시작</b>"
    if settings_summary:
        message += f"\n\n<pre>{_esc(settings_summary)}</pre>"
    return send_telegram_message(message)


def notify_complete(summary_lines: Sequence[str] | None = None) -> bool:
    message = "✅ <b>로또 자동 구매 완료</b>"
    if summary_lines:
        message += "\n\n"
        message += "\n".join(f"• {_esc(line)}" for line in summary_lines)
    return send_telegram_message(message)


def notify_error(error_msg: str) -> bool:
    message = "🚨 <b>오류 발생</b>\n\n"
    message += f"<pre>{_esc(error_msg)}</pre>"
    return send_telegram_message(message)


def notify_dry_run(settings_summary: str) -> bool:
    message = "🧪 <b>DRY RUN 모드</b>\n\n"
    message += "실제 구매/충전을 실행하지 않습니다.\n\n"
    message += f"<pre>{_esc(settings_summary)}</pre>"
    return send_telegram_message(message)


# ---------------------------------------------------------------- 잔액 / 충전


def notify_balance(deposit: int, available: int, required: int | None = None) -> bool:
    message = "💰 <b>예치금 확인</b>\n\n"
    message += f"예치금 잔액: {deposit:,}원\n"
    message += f"구매가능 금액: {available:,}원"
    if required is not None:
        message += f"\n이번 회차 필요 금액: {required:,}원"
        if available < required:
            message += f"\n\n⚠️ {required - available:,}원 부족 → 충전 진행"
        else:
            message += "\n\n✅ 잔액 충분"
    return send_telegram_message(message)


def notify_charge(amount: int, success: bool = True, error_msg: str | None = None) -> bool:
    if success:
        message = "💳 <b>예치금 충전 완료</b>\n\n"
        message += f"충전 금액: {amount:,}원"
    else:
        message = "❌ <b>예치금 충전 실패</b>\n\n"
        message += f"충전 시도 금액: {amount:,}원"
        if error_msg:
            message += f"\n\n<pre>{_esc(error_msg)}</pre>"
    return send_telegram_message(message)


# ---------------------------------------------------------------- 구매 알림


def notify_lotto645_purchase(
    auto_games: int,
    manual_games: int,
    success: bool,
    error_msg: str | None = None,
    numbers: Sequence[Sequence[int]] | None = None,
    strategy_games: int = 0,
    strategy_note: str | None = None,
) -> bool:
    """로또 6/45 구매 결과 알림."""
    total_games = auto_games + manual_games + strategy_games
    total_amount = total_games * 1000

    if not success:
        message = "❌ <b>로또 6/45 구매 실패</b>\n\n"
        if error_msg:
            message += f"<pre>{_esc(error_msg)}</pre>"
        return send_telegram_message(message)

    message = "🎱 <b>로또 6/45 구매 완료</b>\n\n"
    breakdown = []
    if strategy_games > 0:
        breakdown.append(f"전략번호: {strategy_games}게임")
    if manual_games > 0:
        breakdown.append(f"수동: {manual_games}게임")
    if auto_games > 0:
        breakdown.append(f"자동: {auto_games}게임")
    if breakdown:
        message += "\n".join(breakdown) + "\n"
    message += f"\n총 금액: {total_amount:,}원"

    if numbers:
        message += "\n\n<b>구매 번호:</b>\n"
        for i, nums in enumerate(numbers, 1):
            message += f"<code>{i}. {_format_numbers(nums)}</code>\n"

    if strategy_note:
        message += f"\n<i>{_esc(strategy_note)}</i>"

    return send_telegram_message(message)


def notify_lotto720_purchase(
    success: bool,
    error_msg: str | None = None,
    tickets: Sequence[str] | None = None,
    amount: int = 5000,
    purchase_count: int = 1,
    verified_by: str | None = None,
) -> bool:
    """
    연금복권 720+ 구매 결과 알림.

    Args:
        tickets: 구매한 티켓 표기 목록 (예: ["3조 512345", ...])
        verified_by: 성공을 확인한 근거 (예: "잔액 차감 5,000원")
    """
    if not success:
        message = "❌ <b>연금복권 720+ 구매 실패</b>\n\n"
        if error_msg:
            message += f"<pre>{_esc(error_msg)}</pre>"
        return send_telegram_message(message)

    message = "🎟️ <b>연금복권 720+ 구매 완료</b>\n\n"
    message += f"금액: {amount:,}원"
    if purchase_count > 1:
        message += f"\n구매 횟수: {purchase_count}회 (5,000원 × {purchase_count})"

    if tickets:
        message += "\n\n<b>구매 번호:</b>\n"
        for ticket in tickets:
            message += f"<code>{_esc(ticket)}</code>\n"

    if verified_by:
        message += f"\n검증 근거: {_esc(verified_by)}"

    return send_telegram_message(message)


def notify_skipped(game_name: str, reason: str) -> bool:
    message = f"⏭️ <b>{_esc(game_name)} 구매 건너뜀</b>\n\n"
    message += _esc(reason)
    return send_telegram_message(message)


def notify_limit_exceeded() -> bool:
    message = "⚠️ <b>로또 구매 한도 초과</b>\n\n"
    message += "이번 주 구매 한도를 모두 사용했습니다.\n"
    message += "다음 회차(토요일 21:00 이후)부터 구매 가능합니다."
    return send_telegram_message(message)


# ---------------------------------------------------------------- 당첨 결과 알림

RANK_LABELS = {
    1: "1등",
    2: "2등",
    3: "3등",
    4: "4등",
    5: "5등",
}

FIXED_PRIZES = {
    4: 50_000,
    5: 5_000,
}
"""4등/5등은 고정 금액. 1~3등은 파리뮤추얼이라 사전 확정 불가."""


def notify_lotto_result(
    round_num: int,
    winning_numbers: Sequence[int],
    bonus: int,
    tickets: Sequence[dict] | None = None,
    draw_date: str | None = None,
    no_purchase_reason: str | None = None,
) -> bool:
    """
    로또 당첨 결과 상세 알림.

    추첨번호, 내가 구매한 각 게임의 번호, 게임별 일치 번호와 개수,
    보너스 일치 여부, 등수를 모두 표시합니다.

    Args:
        round_num: 회차
        winning_numbers: 당첨 번호 6개
        bonus: 보너스 번호
        tickets: 게임별 결과 목록. 각 항목 형식:
            {
                "numbers": [1,2,3,4,5,6],
                "matched": [2,5],          # 일치한 번호
                "match_count": 2,
                "bonus_matched": False,
                "rank": None or 1~5,
            }
        draw_date: 추첨일
        no_purchase_reason: 구매 내역이 없을 때의 사유
    """
    winning_sorted = sorted(int(n) for n in winning_numbers)

    message = f"🎰 <b>로또 {round_num}회 추첨 결과</b>\n"
    if draw_date:
        message += f"<i>추첨일: {_esc(draw_date)}</i>\n"
    message += "\n"

    # 1. 추첨 번호
    message += "<b>🎯 당첨 번호</b>\n"
    message += f"<code>{_format_numbers(winning_sorted)}</code>\n"
    message += f"보너스: <code>{int(bonus):02d}</code>\n\n"

    # 2. 구매 내역이 없는 경우
    if not tickets:
        message += "<b>📋 내 구매 번호</b>\n"
        message += _esc(no_purchase_reason or "이번 회차 구매 내역이 없습니다.")
        return send_telegram_message(message)

    # 3. 게임별 상세
    message += f"<b>📋 내 구매 번호 ({len(tickets)}게임)</b>\n"

    rank_counts: dict[int, int] = {}

    for i, ticket in enumerate(tickets, 1):
        nums = sorted(int(n) for n in ticket.get("numbers", []))
        matched = sorted(int(n) for n in ticket.get("matched", []))
        match_count = int(ticket.get("match_count", len(matched)))
        bonus_matched = bool(ticket.get("bonus_matched", False))
        rank = ticket.get("rank")

        # 일치 번호는 대괄호로 강조하여 한눈에 보이도록 표기
        parts = []
        for n in nums:
            if n in matched:
                parts.append(f"[{n:02d}]")
            else:
                parts.append(f" {n:02d} ")
        message += f"\n<code>{i}. {''.join(parts)}</code>\n"

        detail = f"   일치 {match_count}개"
        if matched:
            detail += f" → {' '.join(f'{n:02d}' for n in matched)}"
        if bonus_matched:
            detail += f" + 보너스({int(bonus):02d})"
        message += f"{_esc(detail)}\n"

        if rank:
            label = RANK_LABELS.get(rank, f"{rank}등")
            fixed = FIXED_PRIZES.get(rank)
            if fixed:
                message += f"   🎉 <b>{label} 당첨</b> ({fixed:,}원)\n"
            else:
                message += f"   🎉 <b>{label} 당첨</b> (당첨금은 분배 후 확정)\n"
            rank_counts[rank] = rank_counts.get(rank, 0) + 1

    # 4. 요약
    message += "\n"
    if rank_counts:
        message += "<b>🎉 당첨 요약</b>\n"
        fixed_total = 0
        has_parimutuel = False
        for rank in sorted(rank_counts):
            count = rank_counts[rank]
            label = RANK_LABELS.get(rank, f"{rank}등")
            # 여기서 count 는 '장수'입니다. 기존 코드는 이 값을 금액으로 표시하는 버그가 있었습니다.
            message += f"{label}: {count}장\n"
            fixed = FIXED_PRIZES.get(rank)
            if fixed:
                fixed_total += fixed * count
            else:
                has_parimutuel = True
        if fixed_total:
            message += f"\n확정 당첨금: {fixed_total:,}원"
        if has_parimutuel:
            message += "\n<i>1~3등 당첨금은 당첨자 수에 따라 분배되어 추후 확정됩니다.</i>"
    else:
        message += "아쉽게도 당첨되지 않았습니다.\n"
        message += "다음 기회에 도전하세요! 💪"

    return send_telegram_message(message)
