"""
당첨 판정 및 번호 파싱 테스트.
"""

from check_results import (
    check_winning,
    estimate_round,
    evaluate_ticket,
    extract_number_sets,
)

WINNING = [3, 11, 19, 27, 35, 43]
BONUS = 7


# ---------------------------------------------------------------- 등수 판정


def test_first_prize():
    result = evaluate_ticket(WINNING, WINNING, BONUS)
    assert result.rank == 1
    assert result.match_count == 6
    assert result.matched == sorted(WINNING)


def test_second_prize_five_plus_bonus():
    my = [3, 11, 19, 27, 35, BONUS]
    result = evaluate_ticket(my, WINNING, BONUS)
    assert result.match_count == 5
    assert result.bonus_matched is True
    assert result.rank == 2


def test_third_prize_five_without_bonus():
    my = [3, 11, 19, 27, 35, 44]
    result = evaluate_ticket(my, WINNING, BONUS)
    assert result.match_count == 5
    assert result.bonus_matched is False
    assert result.rank == 3


def test_fourth_prize_four_matches():
    my = [3, 11, 19, 27, 44, 45]
    result = evaluate_ticket(my, WINNING, BONUS)
    assert result.match_count == 4
    assert result.rank == 4


def test_fourth_prize_four_matches_with_bonus():
    """4개 일치 + 보너스 보유는 여전히 4등입니다."""
    my = [3, 11, 19, 27, BONUS, 45]
    result = evaluate_ticket(my, WINNING, BONUS)
    assert result.match_count == 4
    assert result.bonus_matched is True
    assert result.rank == 4


def test_fifth_prize_three_matches():
    my = [3, 11, 19, 40, 44, 45]
    result = evaluate_ticket(my, WINNING, BONUS)
    assert result.match_count == 3
    assert result.rank == 5


def test_no_prize_two_matches():
    my = [3, 11, 40, 41, 44, 45]
    result = evaluate_ticket(my, WINNING, BONUS)
    assert result.match_count == 2
    assert result.rank is None


def test_no_prize_bonus_only():
    """보너스만 맞아도 등수는 없습니다."""
    my = [BONUS, 40, 41, 42, 44, 45]
    result = evaluate_ticket(my, WINNING, BONUS)
    assert result.match_count == 0
    assert result.bonus_matched is True
    assert result.rank is None


def test_matched_numbers_are_correct():
    my = [3, 11, 40, 41, 44, 45]
    result = evaluate_ticket(my, WINNING, BONUS)
    assert result.matched == [3, 11]


def test_result_numbers_are_sorted():
    my = [45, 3, 19, 11, 40, 44]
    result = evaluate_ticket(my, WINNING, BONUS)
    assert result.numbers == sorted(my)


# ---------------------------------------------------------------- 하위 호환


def test_check_winning_backward_compatible():
    label, count = check_winning(WINNING, WINNING, BONUS)
    assert label == "1등"
    assert count == 6

    label, count = check_winning([1, 2, 4, 5, 6, 8], WINNING, BONUS)
    assert label is None
    assert count == 0


# ---------------------------------------------------------------- 번호 파싱


def test_extract_number_sets_single_line():
    text = "01 02 03 04 05 06"
    assert extract_number_sets(text) == [[1, 2, 3, 4, 5, 6]]


def test_extract_number_sets_multiline():
    text = "01 02 03 04 05 06\n11 12 13 14 15 16"
    result = extract_number_sets(text)
    assert [1, 2, 3, 4, 5, 6] in result
    assert [11, 12, 13, 14, 15, 16] in result


def test_extract_number_sets_ignores_invalid():
    # 46 은 범위 밖이라 유효 세트를 만들 수 없음
    assert extract_number_sets("46 47 48 49 50 51") == []
    # 5개만 있으면 세트가 아님
    assert extract_number_sets("01 02 03 04 05") == []
    # 중복이 있으면 세트가 아님
    assert extract_number_sets("01 01 02 03 04 05") == []


def test_extract_number_sets_deduplicates():
    text = "01 02 03 04 05 06\n01 02 03 04 05 06"
    assert extract_number_sets(text) == [[1, 2, 3, 4, 5, 6]]


def test_extract_number_sets_handles_empty():
    assert extract_number_sets("") == []
    assert extract_number_sets(None) == []


# ---------------------------------------------------------------- 회차 추정


def test_estimate_round_is_positive():
    import datetime

    assert estimate_round(datetime.date(2002, 12, 7)) == 1
    assert estimate_round(datetime.date(2002, 12, 14)) == 2
    assert estimate_round() > 1000  # 현재 시점 기준 충분히 큰 값
