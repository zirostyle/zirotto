"""
번호 생성 전략 테스트.

핵심 검증 항목:
  1. 생성된 번호가 항상 유효한 로또 조합인가 (6개, 중복 없음, 1~45)
  2. 게임 간 중복 제약이 지켜지는가
  3. 출력이 결정적으로 퇴화하지 않는가 (같은 번호만 반복 생성되지 않음)
  4. 인기도 점수가 의도한 방향으로 동작하는가
  5. 확률 중립성: 전략 번호도 균일 분포에서 나온 유효 조합이어야 함
"""
import pytest

from number_strategy import (
    NUMBER_MAX,
    NUMBER_MIN,
    PICK_SIZE,
    count_consecutive_pairs,
    extract_features,
    generate_portfolio,
    is_valid_set,
    longest_arithmetic_run,
    max_same_column,
    max_same_last_digit,
    max_same_row,
    overlap_count,
    popularity_score,
)

# ---------------------------------------------------------------- 유효성


@pytest.mark.parametrize("n_games", [1, 2, 3, 4, 5])
def test_generated_sets_are_valid(n_games):
    portfolio = generate_portfolio(n_games, seed=42)

    assert len(portfolio.sets) == n_games

    for numbers in portfolio.sets:
        assert len(numbers) == PICK_SIZE
        assert len(set(numbers)) == PICK_SIZE
        assert all(NUMBER_MIN <= n <= NUMBER_MAX for n in numbers)
        assert numbers == sorted(numbers), "번호는 오름차순 정렬되어야 합니다"
        assert is_valid_set(numbers)


def test_zero_games_returns_empty():
    portfolio = generate_portfolio(0)
    assert portfolio.sets == []


def test_overlap_constraint_respected():
    portfolio = generate_portfolio(5, seed=7, max_overlap=2)

    for i, a in enumerate(portfolio.sets):
        for b in portfolio.sets[i + 1 :]:
            assert overlap_count(a, b) <= 2, f"{a} 와 {b} 의 중복이 2개를 초과합니다"


def test_no_duplicate_sets_in_portfolio():
    portfolio = generate_portfolio(5, seed=123)
    keys = [tuple(s) for s in portfolio.sets]
    assert len(keys) == len(set(keys)), "포트폴리오 내 동일 조합이 중복되었습니다"


def test_excluded_sets_are_avoided():
    existing = [[1, 2, 3, 4, 5, 6]]
    portfolio = generate_portfolio(3, seed=99, max_overlap=2, exclude=existing)

    for numbers in portfolio.sets:
        assert overlap_count(numbers, existing[0]) <= 2


# ---------------------------------------------------------------- 재현성 / 다양성


def test_same_seed_is_reproducible():
    a = generate_portfolio(5, seed=2024)
    b = generate_portfolio(5, seed=2024)
    assert a.sets == b.sets


def test_different_seeds_differ():
    a = generate_portfolio(5, seed=1)
    b = generate_portfolio(5, seed=2)
    assert a.sets != b.sets


def test_output_is_not_degenerate():
    """
    회귀 테스트: 초기 구현은 점수 최솟값만 취해
    모든 게임이 01 로 시작하는 등 퇴화된 결과를 냈습니다.
    적격 풀에서 무작위 추출하도록 수정한 뒤의 동작을 검증합니다.
    """
    first_numbers = set()
    all_numbers = set()

    for seed in range(20):
        portfolio = generate_portfolio(5, seed=seed)
        for numbers in portfolio.sets:
            first_numbers.add(numbers[0])
            all_numbers.update(numbers)

    # 첫 번호가 한두 가지로 고정되면 퇴화
    assert len(first_numbers) >= 5, f"첫 번호 다양성 부족: {sorted(first_numbers)}"
    # 전체적으로 넓은 범위를 커버해야 함
    assert len(all_numbers) >= 35, f"번호 커버리지 부족: {len(all_numbers)}개"


def test_portfolio_coverage_is_reasonable():
    portfolio = generate_portfolio(5, seed=555)
    # 5게임 30개 번호에서 중복 제약이 있으므로 최소 20개 이상은 커버되어야 함
    assert portfolio.coverage >= 20


# ---------------------------------------------------------------- 특성 계산


def test_count_consecutive_pairs():
    assert count_consecutive_pairs([1, 2, 3, 10, 20, 30]) == 2
    assert count_consecutive_pairs([1, 5, 10, 20, 30, 40]) == 0
    assert count_consecutive_pairs([1, 2, 3, 4, 5, 6]) == 5


def test_longest_arithmetic_run():
    assert longest_arithmetic_run([1, 2, 3, 4, 5, 6]) == 6
    assert longest_arithmetic_run([5, 10, 15, 2, 33, 41]) == 3
    assert longest_arithmetic_run([1, 4, 9, 16, 25, 36]) == 2


def test_grid_helpers():
    # 1~7 은 모두 첫 행
    assert max_same_row([1, 2, 3, 4, 5, 6]) == 6
    # 1, 8, 15, 22, 29, 36 은 모두 첫 열 (7칸 간격)
    assert max_same_column([1, 8, 15, 22, 29, 36]) == 6
    # 끝자리 1
    assert max_same_last_digit([1, 11, 21, 31, 41, 5]) == 5


def test_extract_features_basic():
    features = extract_features([3, 11, 19, 27, 35, 43])
    assert features.total_sum == 138
    assert features.high_range_count == 2  # 35, 43
    assert features.birthday_count == 4    # 3, 11, 19, 27


# ---------------------------------------------------------------- 인기도 점수


def test_popular_combinations_score_worse_than_spread():
    """
    사람들이 많이 고르는 전형적 조합이
    분산된 조합보다 높은(나쁜) 인기도 점수를 받아야 합니다.
    """
    spread = [4, 17, 23, 34, 39, 45]

    popular_cases = {
        "연속수 1-6": [1, 2, 3, 4, 5, 6],
        "생일대역 전체": [3, 7, 12, 19, 24, 31],
        "5의 배수": [5, 10, 15, 20, 25, 30],
        "같은 열(7간격)": [1, 8, 15, 22, 29, 36],
        "끝자리 동일": [1, 11, 21, 31, 41, 2],
    }

    spread_score = popularity_score(spread)

    for label, numbers in popular_cases.items():
        assert popularity_score(numbers) > spread_score, (
            f"{label} 조합이 분산 조합보다 낮은 점수를 받았습니다"
        )


def test_high_range_reduces_score():
    """32~45 구간을 포함하면 점수가 낮아져야 합니다 (덜 인기 있음)."""
    low_only = [2, 6, 13, 18, 24, 29]
    with_high = [2, 6, 13, 18, 38, 44]
    assert popularity_score(with_high) < popularity_score(low_only)


def test_generated_sets_beat_naive_random_on_average():
    """
    생성된 번호의 평균 인기도 점수가
    단순 무작위 조합의 평균보다 낮아야 합니다.
    (= 남들이 덜 고르는 조합을 고르고 있음)
    """
    import random

    rng = random.Random(4242)
    naive_scores = []
    for _ in range(2000):
        pick = sorted(rng.sample(range(NUMBER_MIN, NUMBER_MAX + 1), PICK_SIZE))
        naive_scores.append(popularity_score(pick))
    naive_mean = sum(naive_scores) / len(naive_scores)

    strategy_scores = []
    for seed in range(20):
        portfolio = generate_portfolio(5, seed=seed)
        strategy_scores.extend(portfolio.scores)
    strategy_mean = sum(strategy_scores) / len(strategy_scores)

    assert strategy_mean < naive_mean, (
        f"전략 평균 점수 {strategy_mean:.2f} 가 무작위 평균 {naive_mean:.2f} 보다 낮지 않습니다"
    )


def test_invalid_sets_rejected():
    assert not is_valid_set([1, 2, 3, 4, 5])        # 5개
    assert not is_valid_set([1, 1, 2, 3, 4, 5])     # 중복
    assert not is_valid_set([0, 1, 2, 3, 4, 5])     # 범위 밖
    assert not is_valid_set([1, 2, 3, 4, 5, 46])    # 범위 밖
    assert is_valid_set([1, 2, 3, 4, 5, 45])
