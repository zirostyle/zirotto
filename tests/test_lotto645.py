"""
로또 6/45 순수 로직 테스트 (구매 시간 게이팅, 번호 파싱).
"""
from datetime import datetime, timedelta, timezone

import pytest

from lotto645 import (
    check_purchase_window,
    extract_number_sets_from_text,
    unique_number_sets,
)

KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------- 구매 가능 시간


def test_sunday_is_blocked():
    # 2026-07-26 은 일요일
    sunday = datetime(2026, 7, 26, 10, 0, tzinfo=KST)
    assert sunday.weekday() == 6
    with pytest.raises(RuntimeError, match="일요일"):
        check_purchase_window(sunday)


def test_saturday_evening_is_blocked():
    # 2026-07-25 는 토요일
    saturday_night = datetime(2026, 7, 25, 20, 0, tzinfo=KST)
    assert saturday_night.weekday() == 5
    with pytest.raises(RuntimeError, match="추첨 시간"):
        check_purchase_window(saturday_night)


def test_saturday_morning_is_allowed():
    saturday_morning = datetime(2026, 7, 25, 10, 0, tzinfo=KST)
    check_purchase_window(saturday_morning)  # 예외 없음


def test_saturday_just_before_cutoff_is_allowed():
    saturday = datetime(2026, 7, 25, 19, 59, tzinfo=KST)
    check_purchase_window(saturday)  # 예외 없음


@pytest.mark.parametrize("day", [27, 28, 29, 30, 31])
def test_weekdays_are_allowed(day):
    # 2026-07-27(월) ~ 2026-07-31(금)
    moment = datetime(2026, 7, day, 9, 0, tzinfo=KST)
    assert moment.weekday() <= 4
    check_purchase_window(moment)  # 예외 없음


# ---------------------------------------------------------------- 번호 파싱


def test_extract_number_sets_basic():
    assert extract_number_sets_from_text("01 02 03 04 05 06") == [[1, 2, 3, 4, 5, 6]]


def test_extract_number_sets_sorted_output():
    result = extract_number_sets_from_text("45 03 19 11 40 44")
    assert result == [[3, 11, 19, 40, 44, 45]]


def test_extract_number_sets_multiline():
    text = "01 02 03 04 05 06\n11 12 13 14 15 16\ngarbage line"
    result = extract_number_sets_from_text(text)
    assert len(result) == 2


def test_extract_number_sets_rejects_invalid():
    assert extract_number_sets_from_text("50 51 52 53 54 55") == []
    assert extract_number_sets_from_text("01 02 03") == []
    assert extract_number_sets_from_text("") == []


def test_unique_number_sets_deduplicates():
    sets = [[1, 2, 3, 4, 5, 6], [6, 5, 4, 3, 2, 1], [7, 8, 9, 10, 11, 12]]
    result = unique_number_sets(sets)
    assert len(result) == 2


def test_unique_number_sets_filters_invalid():
    sets = [[1, 2, 3, 4, 5, 6], [1, 2, 3], [1, 1, 2, 3, 4, 5], [0, 2, 3, 4, 5, 6]]
    result = unique_number_sets(sets)
    assert result == [[1, 2, 3, 4, 5, 6]]


def test_unique_number_sets_empty():
    assert unique_number_sets([]) == []
