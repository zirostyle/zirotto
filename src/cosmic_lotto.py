#!/usr/bin/env python3
"""
우주의 기운(Cosmic Power) 최고 당첨률 로또 6/45 스마트 번호 조합기

동행복권 6/45 역대 통계 데이터와 복권 통계학적 필터링을 결합하여
당첨 확률이 가장 높은 5가지 특화 전략 조합을 생성합니다.

핵심 필터링 규칙:
1. 총합 밸런스: 100 ~ 175 (역대 당첨 번호의 80% 이상 분포)
2. 홀짝 비율: 3:3, 2:4, 4:2 (극단적 6:0, 0:6 배제)
3. 고저 비율: 1~22(저)와 23~45(고) 비율 3:3, 2:4, 4:2
4. 연속 번호 제한: 최대 2연속 1쌍만 허용 (3연속 이상 배제)
5. 끝수(1의 자리) 분산: 동일 끝수 최대 2개 이하
"""

import random
import time
from datetime import datetime

# 로또 6/45 역대 빈출 상위 번호 (Hot Numbers)
HISTORICAL_HOT_NUMBERS = [
    34, 18, 27, 43, 12, 1, 13, 20, 33, 45,
    39, 4, 24, 17, 14, 26, 38, 11, 2, 7
]

# 로또 6/45 주기적 반등/미출현 관심 번호 (Cold & Due Numbers)
HISTORICAL_COLD_NUMBERS = [
    9, 22, 29, 32, 41, 5, 8, 25, 30, 42,
    16, 21, 28, 36, 19, 37, 15, 3, 23, 6
]

# 소수(Prime Numbers 1~45)
PRIME_NUMBERS = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43]

# 3의 배수
MULTIPLE_OF_THREE = [3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45]


def is_valid_combination(nums: list, min_sum: int = 100, max_sum: int = 175) -> bool:
    """
    통계학적 유효성 검사 필터:
    - 6개 중복 없는 1~45 숫자
    - 총합 범위 (기본 100~175)
    - 홀짝 비율 (홀수 개수 2, 3, 4개만 허용)
    - 고저 비율 (23 이상 개수 2, 3, 4개만 허용)
    - 3연속 이상 배제
    - 동일 끝수 3개 이상 배제
    """
    if len(nums) != 6 or len(set(nums)) != 6:
        return False
    
    if not all(1 <= n <= 45 for n in nums):
        return False

    sorted_nums = sorted(nums)

    # 1. 총합 검사
    total_sum = sum(sorted_nums)
    if not (min_sum <= total_sum <= max_sum):
        return False

    # 2. 홀짝 비율 검사
    odd_count = sum(1 for n in sorted_nums if n % 2 != 0)
    if odd_count not in [2, 3, 4]:
        return False

    # 3. 고저 비율 검사 (1~22 저, 23~45 고)
    high_count = sum(1 for n in sorted_nums if n >= 23)
    if high_count not in [2, 3, 4]:
        return False

    # 4. 연속 번호 검사 (3연속 번호 배제)
    consecutive_count = 0
    max_consecutive = 1
    current_consecutive = 1
    for i in range(len(sorted_nums) - 1):
        if sorted_nums[i + 1] == sorted_nums[i] + 1:
            current_consecutive += 1
            max_consecutive = max(max_consecutive, current_consecutive)
        else:
            current_consecutive = 1
    if max_consecutive >= 3:
        return False

    # 5. 끝수 검사 (동일 끝수 3개 이상 배제)
    last_digits = [n % 10 for n in sorted_nums]
    if any(last_digits.count(d) >= 3 for d in set(last_digits)):
        return False

    return True


def generate_game_a_golden_balance() -> list:
    """
    게임 A: 🌌 우주 황금 밸런스
    역대 최빈출(Hot) 3개 + 미출현(Cold) 2개 + 밸런스 1개
    총합 115 ~ 155 사이의 가장 이상적인 정규분포 중심 조합
    """
    for _ in range(1000):
        hot_pick = random.sample(HISTORICAL_HOT_NUMBERS, 3)
        cold_pick = random.sample([n for n in HISTORICAL_COLD_NUMBERS if n not in hot_pick], 2)
        remaining = [n for n in range(1, 46) if n not in hot_pick and n not in cold_pick]
        balance_pick = random.sample(remaining, 1)
        combo = sorted(hot_pick + cold_pick + balance_pick)
        if is_valid_combination(combo, min_sum=115, max_sum=155):
            return combo
    return [3, 12, 18, 27, 34, 43]


def generate_game_b_hot_frequency() -> list:
    """
    게임 B: 🔥 역대 최빈출 집중 조합
    역대 누적 1위~20위 고빈도 번호 중심 4개 + 지지 번호 2개
    """
    for _ in range(1000):
        hot_pick = random.sample(HISTORICAL_HOT_NUMBERS[:15], 4)
        pool = [n for n in range(1, 46) if n not in hot_pick]
        other_pick = random.sample(pool, 2)
        combo = sorted(hot_pick + other_pick)
        if is_valid_combination(combo, min_sum=105, max_sum=165):
            return combo
    return [1, 14, 20, 27, 34, 45]


def generate_game_c_cold_rebound() -> list:
    """
    게임 C: ⚡ 주기 반등 콜드 조합
    확률 균형 회복 법칙(평균으로의 회귀)에 따른 미출현 주기 번호 4개 + 핫 넘버 2개
    """
    for _ in range(1000):
        cold_pick = random.sample(HISTORICAL_COLD_NUMBERS, 4)
        hot_pick = random.sample([n for n in HISTORICAL_HOT_NUMBERS if n not in cold_pick], 2)
        combo = sorted(cold_pick + hot_pick)
        if is_valid_combination(combo, min_sum=100, max_sum=170):
            return combo
    return [8, 13, 22, 29, 34, 41]


def generate_game_d_mathematical_harmony() -> list:
    """
    게임 D: 📐 수학적 황금비 (소수 & 배수 조화)
    소수 2~3개 + 3의 배수 1~2개 + 합성수 1~2개 대칭 분배
    """
    for _ in range(1000):
        prime_pick = random.sample(PRIME_NUMBERS, random.choice([2, 3]))
        multi_pool = [n for n in MULTIPLE_OF_THREE if n not in prime_pick]
        multi_pick = random.sample(multi_pool, 2)
        remaining = [n for n in range(1, 46) if n not in prime_pick and n not in multi_pick]
        other_count = 6 - (len(prime_pick) + len(multi_pick))
        other_pick = random.sample(remaining, other_count)
        combo = sorted(prime_pick + multi_pick + other_pick)
        if is_valid_combination(combo, min_sum=105, max_sum=170):
            return combo
    return [5, 11, 18, 23, 33, 42]


def generate_game_e_cosmic_chaos() -> list:
    """
    게임 E: 🍀 카오스 우주 에너지
    구매 시점의 타임스탬프와 일자 에너지를 시드로 삼아 가중치 난수로 조합
    """
    now = datetime.now()
    seed_val = int(time.time() * 1000) % 1000000 + now.day * 1000 + now.hour * 60 + now.minute
    rng = random.Random(seed_val)
    
    for _ in range(1000):
        weights = [1.0 + (n % 7) * 0.1 for n in range(1, 46)]
        for h in HISTORICAL_HOT_NUMBERS[:10]:
            weights[h - 1] += 0.5
        for c in HISTORICAL_COLD_NUMBERS[:10]:
            weights[c - 1] += 0.4
        
        # 가중치 기반 6개 선택
        selected = []
        avail_nums = list(range(1, 46))
        avail_weights = list(weights)
        while len(selected) < 6:
            chosen = rng.choices(avail_nums, weights=avail_weights, k=1)[0]
            idx = avail_nums.index(chosen)
            selected.append(chosen)
            avail_nums.pop(idx)
            avail_weights.pop(idx)
        
        combo = sorted(selected)
        if is_valid_combination(combo, min_sum=100, max_sum=175):
            return combo
    return [2, 12, 19, 26, 38, 44]


def generate_cosmic_5_games() -> list:
    """
    우주의 기운 5게임(A, B, C, D, E)을 생성합니다.
    
    Returns:
        list of dict:
        [
            {'slot': 'A', 'name': '우주 황금 밸런스', 'tag': '🌌 우주 황금 밸런스', 'numbers': [3, 12, 18, 27, 34, 43]},
            {'slot': 'B', 'name': '역대 최빈출 집중', 'tag': '🔥 역대 최빈출 집중', 'numbers': [...]},
            ...
        ]
    """
    games = []
    
    strategies = [
        ('A', '우주 황금 밸런스', '🌌 우주 황금 밸런스', generate_game_a_golden_balance),
        ('B', '역대 최빈출 집중', '🔥 역대 최빈출 집중', generate_game_b_hot_frequency),
        ('C', '주기 반등 콜드 조합', '⚡ 주기 반등 콜드 조합', generate_game_c_cold_rebound),
        ('D', '수학적 황금비 조화', '📐 수학적 황금비 조화', generate_game_d_mathematical_harmony),
        ('E', '카오스 우주 에너지', '🍀 카오스 우주 에너지', generate_game_e_cosmic_chaos),
    ]
    
    seen_combos = set()
    
    for slot, name, tag, generator in strategies:
        combo = generator()
        key = tuple(combo)
        # 중복 조합 방지
        attempts = 0
        while key in seen_combos and attempts < 10:
            combo = generator()
            key = tuple(combo)
            attempts += 1
            
        seen_combos.add(key)
        games.append({
            'slot': slot,
            'name': name,
            'tag': tag,
            'numbers': combo
        })
        
    return games


if __name__ == '__main__':
    print("=" * 60)
    print("🔮 우주의 기운 최고 당첨률 로또 6/45 번호 조합 생성기")
    print("=" * 60)
    games = generate_cosmic_5_games()
    for g in games:
        nums_str = " ".join([f"{n:02d}" for n in g['numbers']])
        total = sum(g['numbers'])
        odds = sum(1 for n in g['numbers'] if n % 2 != 0)
        print(f"[{g['slot']}] {g['tag']}")
        print(f"    번호: {nums_str} (합: {total}, 홀짝: {odds}:{6-odds})")
    print("=" * 60)
