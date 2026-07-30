"""
텔레그램 알림 렌더링 테스트.

가장 중요한 회귀 테스트:
  기존 코드는 당첨 '장수'를 집계한 뒤 '{amount:,}원' 으로 렌더링해서
  5등 2장 당첨이 "5등: 2원" 으로 표시되는 버그가 있었습니다.
"""
import pytest

import telegram_notifier
from telegram_notifier import (
    notify_balance,
    notify_lotto645_purchase,
    notify_lotto720_purchase,
    notify_lotto_result,
)


@pytest.fixture
def captured(monkeypatch):
    """send_telegram_message 를 가로채 메시지를 수집합니다."""
    messages = []

    def _capture(message, parse_mode="HTML"):
        messages.append(message)
        return True

    monkeypatch.setattr(telegram_notifier, "send_telegram_message", _capture)
    return messages


WINNING = [3, 11, 19, 27, 35, 43]
BONUS = 7


# ---------------------------------------------------------------- 회귀 테스트


def test_prize_summary_shows_ticket_count_not_currency(captured):
    """
    회귀 테스트: 당첨 집계는 '장수' 이므로 '원' 으로 표시하면 안 됩니다.
    """
    tickets = [
        {
            "numbers": [3, 11, 19, 40, 44, 45],
            "matched": [3, 11, 19],
            "match_count": 3,
            "bonus_matched": False,
            "rank": 5,
        },
        {
            "numbers": [3, 11, 19, 41, 42, 45],
            "matched": [3, 11, 19],
            "match_count": 3,
            "bonus_matched": False,
            "rank": 5,
        },
    ]

    notify_lotto_result(1000, WINNING, BONUS, tickets=tickets)

    assert len(captured) == 1
    message = captured[0]

    # 2장 당첨이 "2장" 으로 표기되어야 함
    assert "5등: 2장" in message
    # 버그 형태("5등: 2원")가 남아 있지 않아야 함
    assert "5등: 2원" not in message
    # 5등 고정 당첨금은 별도로 정확히 계산되어야 함 (5,000 x 2)
    assert "10,000원" in message


def test_fixed_prize_total_calculated(captured):
    tickets = [
        {
            "numbers": [3, 11, 19, 27, 44, 45],
            "matched": [3, 11, 19, 27],
            "match_count": 4,
            "bonus_matched": False,
            "rank": 4,
        }
    ]
    notify_lotto_result(1001, WINNING, BONUS, tickets=tickets)
    message = captured[0]
    assert "4등: 1장" in message
    assert "50,000원" in message


def test_parimutuel_ranks_do_not_claim_fixed_amount(captured):
    tickets = [
        {
            "numbers": WINNING,
            "matched": WINNING,
            "match_count": 6,
            "bonus_matched": False,
            "rank": 1,
        }
    ]
    notify_lotto_result(1002, WINNING, BONUS, tickets=tickets)
    message = captured[0]
    assert "1등: 1장" in message
    # 1등은 분배 방식이므로 금액을 확정 표기하지 않아야 함
    assert "분배" in message


# ---------------------------------------------------------------- 상세 표시


def test_result_message_includes_winning_numbers(captured):
    notify_lotto_result(1003, WINNING, BONUS, tickets=None)
    message = captured[0]
    for number in WINNING:
        assert f"{number:02d}" in message
    assert f"{BONUS:02d}" in message


def test_result_message_marks_matched_numbers(captured):
    tickets = [
        {
            "numbers": [3, 11, 40, 41, 44, 45],
            "matched": [3, 11],
            "match_count": 2,
            "bonus_matched": False,
            "rank": None,
        }
    ]
    notify_lotto_result(1004, WINNING, BONUS, tickets=tickets)
    message = captured[0]
    # 일치 번호는 대괄호로 강조
    assert "[03]" in message
    assert "[11]" in message
    # 미일치 번호는 강조하지 않음
    assert "[40]" not in message
    assert "일치 2개" in message


def test_result_message_shows_bonus_match(captured):
    tickets = [
        {
            "numbers": [3, 11, 19, 27, 35, BONUS],
            "matched": [3, 11, 19, 27, 35],
            "match_count": 5,
            "bonus_matched": True,
            "rank": 2,
        }
    ]
    notify_lotto_result(1005, WINNING, BONUS, tickets=tickets)
    message = captured[0]
    assert "보너스" in message
    assert "2등: 1장" in message


def test_result_message_no_purchase(captured):
    notify_lotto_result(
        1006, WINNING, BONUS, tickets=None, no_purchase_reason="구매 내역이 없습니다."
    )
    message = captured[0]
    assert "구매 내역이 없습니다." in message


def test_result_message_no_winners(captured):
    tickets = [
        {
            "numbers": [1, 2, 4, 5, 6, 8],
            "matched": [],
            "match_count": 0,
            "bonus_matched": False,
            "rank": None,
        }
    ]
    notify_lotto_result(1007, WINNING, BONUS, tickets=tickets)
    message = captured[0]
    assert "당첨되지 않았습니다" in message


def test_result_message_includes_draw_date(captured):
    notify_lotto_result(1008, WINNING, BONUS, tickets=None, draw_date="2026-07-25")
    assert "2026-07-25" in captured[0]


# ---------------------------------------------------------------- 구매 알림


def test_lotto645_purchase_lists_numbers(captured):
    numbers = [[1, 2, 3, 4, 5, 6], [10, 20, 30, 40, 44, 45]]
    notify_lotto645_purchase(
        auto_games=0,
        manual_games=0,
        strategy_games=2,
        success=True,
        numbers=numbers,
    )
    message = captured[0]
    assert "전략번호: 2게임" in message
    assert "2,000원" in message
    assert "01 02 03 04 05 06" in message
    assert "10 20 30 40 44 45" in message


def test_lotto645_purchase_failure_shows_error(captured):
    notify_lotto645_purchase(0, 0, False, error_msg="구매 완료 미확인")
    message = captured[0]
    assert "구매 실패" in message
    assert "구매 완료 미확인" in message


def test_lotto720_purchase_shows_tickets_and_evidence(captured):
    notify_lotto720_purchase(
        True,
        tickets=["3조 512345", "1조 998877"],
        amount=10000,
        purchase_count=2,
        verified_by="예치금 차감 10,000원",
    )
    message = captured[0]
    assert "10,000원" in message
    assert "3조 512345" in message
    assert "예치금 차감" in message


def test_lotto720_failure_shows_reason(captured):
    notify_lotto720_purchase(False, error_msg="예치금이 차감되지 않았습니다")
    message = captured[0]
    assert "구매 실패" in message
    assert "차감되지 않았습니다" in message


# ---------------------------------------------------------------- 잔액 알림


def test_balance_warns_on_shortfall(captured):
    notify_balance(5000, 5000, required=13000)
    message = captured[0]
    assert "8,000원 부족" in message


def test_balance_reports_sufficient(captured):
    notify_balance(20000, 20000, required=13000)
    message = captured[0]
    assert "잔액 충분" in message


# ---------------------------------------------------------------- 설정 감지


def test_unconfigured_returns_false(monkeypatch):
    """
    회귀 테스트: 토큰이 없으면 False 를 반환하되,
    환경변수를 '호출 시점' 에 읽어야 합니다.
    (기존에는 import 시점에 읽어 .env 로딩보다 앞섰습니다)
    """
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    telegram_notifier._WARNED_UNCONFIGURED = False

    assert telegram_notifier.is_configured() is False
    assert telegram_notifier.send_telegram_message("test") is False


def test_is_configured_detects_late_env(monkeypatch):
    """
    핵심 검증: import 이후에 환경변수가 설정되어도 인식해야 합니다.
    """
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert telegram_notifier.is_configured() is False

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "late-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "late-chat")
    assert telegram_notifier.is_configured() is True


def test_html_escaping_in_error(captured):
    notify_lotto645_purchase(0, 0, False, error_msg="<script>alert(1)</script>")
    message = captured[0]
    assert "<script>" not in message
    assert "&lt;script&gt;" in message
