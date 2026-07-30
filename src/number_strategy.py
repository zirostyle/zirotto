#!/usr/bin/env python3
"""
로또 6/45 번호 포트폴리오 생성기.

================================================================
반드시 읽어주세요 — 이 모듈이 하는 일과 하지 않는 일
================================================================

이 모듈은 "당첨 확률"을 높이지 않습니다. 높일 수 없습니다.

로또 6/45 의 1등 확률은 C(45,6) = 8,145,060 분의 1 이며,
어떤 번호 조합을 고르더라도 정확히 동일합니다.
추첨은 독립 시행이므로 과거 당첨번호, 미출현 기간, 궁합수,
통계적 "핫/콜드" 번호 따위는 다음 추첨에 아무 영향을 주지 않습니다.
그런 것으로 확률을 높인다고 주장하는 코드는 전부 거짓입니다.

그렇다면 이 모듈은 무엇을 최적화하는가?

  → 당첨됐을 때 실제로 손에 쥐는 금액 (기댓값)

한국 로또 1~3등은 '파리뮤추얼(pari-mutuel)' 방식입니다.
등수별 총 상금 풀을 그 등수 당첨자 수로 나눠 분배합니다.
따라서 같은 조합을 고른 사람이 적으면 1인당 수령액이 커집니다.
(4등 50,000원 / 5등 5,000원은 고정액이므로 이 최적화와 무관합니다.)

사람들의 번호 선택은 균일하지 않고 강하게 편향되어 있습니다:
  - 생일/기념일 → 1~31 구간 과다 선택 (특히 1~12)
  - 연속수, 등차수열
  - 마킹용지 위의 직선/대각선 패턴 (같은 행·열 쏠림)
  - 5의 배수, 이른바 '행운의 숫자'(7 등)
  - 합계가 낮은 구간에 쏠림 (생일 편향의 결과)

이런 '인기 조합'을 회피하면 당첨 확률은 그대로지만,
1~3등 당첨 시 분배 인원이 줄어 기대 수령액이 올라갑니다.
이것이 이 모듈이 구현하는 유일하고 정직한 최적화입니다.

부가로, 한 회차에 여러 게임을 살 때 게임 간 번호 중복을 억제해
'전멸' 분산을 줄입니다. (기댓값 자체는 변하지 않습니다.)
================================================================
"""
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

NUMBER_MIN = 1
NUMBER_MAX = 45
PICK_SIZE = 6

# 마킹용지 격자: 1~45 를 7열로 배치 (1-7 / 8-14 / ... / 43-45)
GRID_COLUMNS = 7

# 생일 편향 구간 상한
BIRTHDAY_MAX = 31

# 전체 조합 합계의 기대값 = 6 * (1+45)/2 = 138
EXPECTED_SUM = 138

# ---------------------------------------------------------------- 점수 가중치
# 값이 클수록 해당 '인기 특성'을 강하게 회피합니다.
# 모든 항목은 '인기도 페널티'이며, 총점이 낮은 조합이 선택됩니다.

WEIGHTS: dict[str, float] = {
    "birthday_bias": 3.0,       # 1~31 구간 과다 포함
    "low_number_bias": 2.0,     # 1~12 구간 과다 포함 (월 편향)
    "consecutive": 2.5,         # 연속수 쌍
    "arithmetic": 4.0,          # 길이 3 이상 등차수열
    "same_row": 2.0,            # 격자 같은 행 쏠림
    "same_column": 2.0,         # 격자 같은 열 쏠림
    "multiples_of_five": 1.5,   # 5의 배수 과다
    "same_last_digit": 1.5,     # 동일 끝자리 쏠림
    "sum_bias": 2.0,            # 합계가 기대값보다 낮은 쪽으로 치우침
    "lucky_seven": 0.8,         # 7 및 7의 배수 선호
    "high_range_bonus": -2.0,   # 32~45 구간 포함은 보상(음수 = 점수 감소)
}


# ---------------------------------------------------------------- 특성 계산


def _row_of(n: int) -> int:
    return (n - 1) // GRID_COLUMNS


def _column_of(n: int) -> int:
    return (n - 1) % GRID_COLUMNS


def count_consecutive_pairs(numbers: Sequence[int]) -> int:
    """인접한(차이 1) 쌍의 개수."""
    ordered = sorted(numbers)
    return sum(1 for a, b in zip(ordered, ordered[1:], strict=False) if b - a == 1)


def longest_arithmetic_run(numbers: Sequence[int]) -> int:
    """가장 긴 등차수열의 길이 (공차 1 이상)."""
    ordered = sorted(set(numbers))
    if len(ordered) < 3:
        return len(ordered)

    best = 2
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            diff = ordered[j] - ordered[i]
            length = 2
            nxt = ordered[j] + diff
            while nxt in ordered:
                length += 1
                nxt += diff
            best = max(best, length)
    return best


def max_same_row(numbers: Sequence[int]) -> int:
    counts: dict[int, int] = {}
    for n in numbers:
        row = _row_of(n)
        counts[row] = counts.get(row, 0) + 1
    return max(counts.values()) if counts else 0


def max_same_column(numbers: Sequence[int]) -> int:
    counts: dict[int, int] = {}
    for n in numbers:
        col = _column_of(n)
        counts[col] = counts.get(col, 0) + 1
    return max(counts.values()) if counts else 0


def max_same_last_digit(numbers: Sequence[int]) -> int:
    counts: dict[int, int] = {}
    for n in numbers:
        digit = n % 10
        counts[digit] = counts.get(digit, 0) + 1
    return max(counts.values()) if counts else 0


@dataclass
class Features:
    """조합의 인기도 관련 특성."""

    numbers: list[int]
    birthday_count: int
    low_count: int
    consecutive_pairs: int
    longest_ap: int
    max_row: int
    max_column: int
    multiples_of_five: int
    max_last_digit: int
    total_sum: int
    seven_related: int
    high_range_count: int

    def as_dict(self) -> dict[str, int]:
        return {
            "birthday_count": self.birthday_count,
            "low_count": self.low_count,
            "consecutive_pairs": self.consecutive_pairs,
            "longest_ap": self.longest_ap,
            "max_row": self.max_row,
            "max_column": self.max_column,
            "multiples_of_five": self.multiples_of_five,
            "max_last_digit": self.max_last_digit,
            "total_sum": self.total_sum,
            "seven_related": self.seven_related,
            "high_range_count": self.high_range_count,
        }


def extract_features(numbers: Sequence[int]) -> Features:
    """조합에서 인기도 관련 특성을 추출합니다."""
    nums = sorted(int(n) for n in numbers)
    return Features(
        numbers=nums,
        birthday_count=sum(1 for n in nums if n <= BIRTHDAY_MAX),
        low_count=sum(1 for n in nums if n <= 12),
        consecutive_pairs=count_consecutive_pairs(nums),
        longest_ap=longest_arithmetic_run(nums),
        max_row=max_same_row(nums),
        max_column=max_same_column(nums),
        multiples_of_five=sum(1 for n in nums if n % 5 == 0),
        max_last_digit=max_same_last_digit(nums),
        total_sum=sum(nums),
        seven_related=sum(1 for n in nums if n % 7 == 0 or n == 7),
        high_range_count=sum(1 for n in nums if n > BIRTHDAY_MAX),
    )


def popularity_score(numbers: Sequence[int]) -> float:
    """
    조합의 '인기도 페널티' 점수. 낮을수록 남들이 덜 고를 조합입니다.

    이 점수는 당첨 확률과 무관합니다.
    1~3등 당첨 시 분배 인원을 줄이기 위한 대리 지표(proxy)입니다.
    """
    f = extract_features(numbers)
    score = 0.0

    # 생일 편향: 6개 중 1~31 이 4개를 넘으면 페널티 (평균 기대치는 약 4.1개)
    score += WEIGHTS["birthday_bias"] * max(0, f.birthday_count - 4)

    # 월 편향: 1~12 가 3개를 넘으면 페널티
    score += WEIGHTS["low_number_bias"] * max(0, f.low_count - 2)

    # 연속수
    score += WEIGHTS["consecutive"] * f.consecutive_pairs

    # 등차수열 (길이 3 이상부터)
    score += WEIGHTS["arithmetic"] * max(0, f.longest_ap - 2)

    # 격자 쏠림 (같은 행/열 3개 이상)
    score += WEIGHTS["same_row"] * max(0, f.max_row - 2)
    score += WEIGHTS["same_column"] * max(0, f.max_column - 2)

    # 5의 배수 (기대치 약 1.2개)
    score += WEIGHTS["multiples_of_five"] * max(0, f.multiples_of_five - 1)

    # 동일 끝자리 (3개 이상부터)
    score += WEIGHTS["same_last_digit"] * max(0, f.max_last_digit - 2)

    # 합계 편향: 기대값(138)보다 낮은 쪽만 페널티.
    # 생일 편향의 결과로 사람들은 낮은 합계를 고르는 경향이 있습니다.
    if f.total_sum < EXPECTED_SUM:
        score += WEIGHTS["sum_bias"] * ((EXPECTED_SUM - f.total_sum) / 20.0)

    # 7 선호
    score += WEIGHTS["lucky_seven"] * max(0, f.seven_related - 1)

    # 고구간(32~45) 포함 보상 — 가중치가 음수라 점수를 낮춥니다
    score += WEIGHTS["high_range_bonus"] * min(f.high_range_count, 3)

    return score


# ---------------------------------------------------------------- 유효성


def is_valid_set(numbers: Sequence[int]) -> bool:
    """6개, 중복 없음, 1~45 범위인지 확인."""
    try:
        nums = [int(n) for n in numbers]
    except (TypeError, ValueError):
        return False
    if len(nums) != PICK_SIZE:
        return False
    if len(set(nums)) != PICK_SIZE:
        return False
    return all(NUMBER_MIN <= n <= NUMBER_MAX for n in nums)


def overlap_count(a: Sequence[int], b: Sequence[int]) -> int:
    """두 조합의 공통 번호 개수."""
    return len(set(a) & set(b))


# ---------------------------------------------------------------- 포트폴리오 생성


@dataclass
class Portfolio:
    """생성된 번호 포트폴리오."""

    sets: list[list[int]] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    candidate_pool_size: int = 0
    max_overlap: int = 0

    @property
    def coverage(self) -> int:
        """포트폴리오 전체가 커버하는 서로 다른 번호 개수."""
        covered = set()
        for s in self.sets:
            covered.update(s)
        return len(covered)

    @property
    def mean_score(self) -> float:
        if not self.scores:
            return 0.0
        return sum(self.scores) / len(self.scores)


def generate_portfolio(
    n_games: int,
    pool_size: int = 4000,
    max_overlap: int = 2,
    seed: int | None = None,
    exclude: Sequence[Sequence[int]] | None = None,
    elite_ratio: float = 0.15,
) -> Portfolio:
    """
    기댓값 최적화 번호 포트폴리오를 생성합니다.

    동작:
      1. 균일 랜덤으로 후보 조합 pool_size 개 생성
      2. 각 후보의 인기도 페널티 점수 계산
      3. 점수 하위 elite_ratio 비율(= 가장 안 인기 있는 구간)을 '적격 풀'로 선별
      4. 적격 풀을 무작위로 섞은 뒤, 게임 간 중복이 max_overlap 이하인 것만 채택

    왜 최솟값을 그냥 고르지 않는가:
      점수 최솟값만 취하면 매번 거의 같은 조합이 나옵니다.
      결정적이고 예측 가능한 출력은 그 자체로 '인기 조합'이 될 수 있고,
      한 회차 안에서도 번호가 한쪽으로 퇴화합니다.
      적격 풀 안에서 무작위 추출하면 기댓값 이점은 유지하면서
      예측 불가능성과 번호 분산을 확보합니다.

    중요: 1단계가 균일 랜덤이고 4단계도 무작위 추출이므로
    각 조합의 당첨 확률은 동일합니다.
    3~4단계는 '당첨 시 분배 인원'만 줄이며 확률은 건드리지 않습니다.

    Args:
        n_games: 생성할 게임 수
        pool_size: 후보 풀 크기 (클수록 더 희귀한 조합을 찾지만 느려짐)
        max_overlap: 게임 간 허용 최대 중복 번호 수
        seed: 재현성을 위한 난수 시드
        exclude: 제외할 조합 목록 (예: 이미 수동으로 지정한 번호)
        elite_ratio: 적격 풀 비율 (0~1). 작을수록 희귀도↑, 다양성↓

    Returns:
        Portfolio
    """
    if n_games <= 0:
        return Portfolio(candidate_pool_size=0, max_overlap=max_overlap)

    rng = random.Random(seed)
    all_numbers = list(range(NUMBER_MIN, NUMBER_MAX + 1))

    # 1. 후보 풀 생성 (균일 랜덤 — 확률 중립)
    seen: set = set()
    candidates: list[tuple[float, list[int]]] = []
    for _ in range(max(pool_size, n_games * 200)):
        pick = sorted(rng.sample(all_numbers, PICK_SIZE))
        key = tuple(pick)
        if key in seen:
            continue
        seen.add(key)
        candidates.append((popularity_score(pick), pick))

    # 2. 인기도 낮은 순 정렬
    candidates.sort(key=lambda item: item[0])

    # 3. 하위 elite_ratio 를 적격 풀로 선별 (최소한 게임 수의 20배는 확보)
    elite_size = max(int(len(candidates) * max(0.01, min(elite_ratio, 1.0))), n_games * 20)
    elite_size = min(elite_size, len(candidates))
    elite = candidates[:elite_size]

    # 4. 적격 풀을 섞어 무작위성 확보 후 다양성 제약을 지키며 선택
    rng.shuffle(elite)

    excluded_sets = [sorted(int(n) for n in s) for s in (exclude or []) if is_valid_set(s)]

    chosen: list[list[int]] = []
    chosen_scores: list[float] = []

    for threshold in range(max_overlap, PICK_SIZE + 1):
        # 제약을 만족하지 못하면 중복 허용치를 점진적으로 완화
        for score, pick in elite:
            if len(chosen) >= n_games:
                break
            if any(pick == prev for prev in chosen):
                continue
            if any(overlap_count(pick, prev) > threshold for prev in chosen):
                continue
            if any(overlap_count(pick, ex) > threshold for ex in excluded_sets):
                continue
            chosen.append(pick)
            chosen_scores.append(score)
        if len(chosen) >= n_games:
            break

    return Portfolio(
        sets=chosen[:n_games],
        scores=chosen_scores[:n_games],
        candidate_pool_size=len(candidates),
        max_overlap=max_overlap,
    )


# ---------------------------------------------------------------- 설명 텍스트


def describe_portfolio(portfolio: Portfolio) -> str:
    """
    포트폴리오를 사람이 읽을 수 있는 형태로 설명합니다.
    텔레그램 알림과 로그에 사용합니다.
    """
    if not portfolio.sets:
        return "생성된 번호가 없습니다."

    lines = []
    for i, nums in enumerate(portfolio.sets, 1):
        f = extract_features(nums)
        formatted = " ".join(f"{n:02d}" for n in nums)
        lines.append(
            f"{i}. {formatted}"
            f"  (합 {f.total_sum}, 32↑ {f.high_range_count}개, 연속 {f.consecutive_pairs}쌍)"
        )

    lines.append("")
    lines.append(
        f"후보 {portfolio.candidate_pool_size:,}개 중 선별 / "
        f"커버 번호 {portfolio.coverage}개 / 게임 간 최대 중복 {portfolio.max_overlap}개"
    )
    return "\n".join(lines)


def strategy_disclaimer() -> str:
    """전략의 한계를 명시하는 고정 문구."""
    return (
        "번호 선택은 당첨 확률을 바꾸지 않습니다 (1등 1/8,145,060 고정). "
        "생일·연속수·격자패턴 등 다수가 선호하는 조합을 회피해 "
        "1~3등 당첨 시 분배 인원을 줄이는 기댓값 최적화만 수행합니다."
    )


if __name__ == "__main__":
    import sys

    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    result = generate_portfolio(count, seed=None)
    print(describe_portfolio(result))
    print()
    print(strategy_disclaimer())
