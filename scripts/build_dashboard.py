#!/usr/bin/env python3
"""
대시보드 데이터 빌더 스크립트 (scripts/build_dashboard.py)

1. data/purchased_lotto.json 및 data/purchased_pension720.json 로드
2. 최신 당첨 번호 조회 (로또 6/45 & 연금복권 720+)
3. 각 구매 게임별 실시간 당첨 매칭 및 당첨금/손익/수익률(ROI) 통계 산출
4. docs/data.json 생성 (GitHub Pages 대시보드 연동용)
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta

# src 디렉토리 참조 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, os.path.join(project_root, "src"))

from check_results import (
    get_latest_lotto_winning_numbers,
    get_latest_pension720_winning_numbers,
    check_single_game,
    check_pension720_winning,
)


def build_dashboard_data():
    docs_dir = os.path.join(project_root, "docs")
    data_dir = os.path.join(project_root, "data")
    os.makedirs(docs_dir, exist_ok=True)

    lotto_path = os.path.join(data_dir, "purchased_lotto.json")
    pension_path = os.path.join(data_dir, "purchased_pension720.json")
    output_path = os.path.join(docs_dir, "data.json")

    # 1. 파일 로드
    lotto_history = []
    if os.path.exists(lotto_path):
        try:
            with open(lotto_path, "r", encoding="utf-8") as f:
                lotto_history = json.load(f).get("history", [])
        except Exception as e:
            print(f"⚠️ 로또 데이터 로드 실패: {e}")

    pension_history = []
    if os.path.exists(pension_path):
        try:
            with open(pension_path, "r", encoding="utf-8") as f:
                pension_history = json.load(f).get("history", [])
        except Exception as e:
            print(f"⚠️ 연금복권 데이터 로드 실패: {e}")

    # 2. 최신 당첨 번호 조회
    lotto_winning = None
    try:
        lotto_winning = get_latest_lotto_winning_numbers()
        print(f"🎯 로또 6/45 최신 당첨 번호 확인: {lotto_winning['round']}회")
    except Exception as e:
        print(f"⚠️ 로또 당첨 번호 조회 실패: {e}")

    pension_winning = None
    try:
        pension_winning = get_latest_pension720_winning_numbers()
        print(f"🎯 연금복권 720+ 최신 당첨 번호 확인: {pension_winning['round']}회")
    except Exception as e:
        print(f"⚠️ 연금복권 당첨 번호 조회 실패: {e}")

    # 3. 로또 6/45 통계 및 매칭 결과 가공
    total_lotto_spent = 0
    total_lotto_won = 0
    lotto_rank_counts = {"1등": 0, "2등": 0, "3등": 0, "4등": 0, "5등": 0}
    processed_lotto_history = []

    for item in lotto_history:
        rnd = item.get("round")
        games = item.get("games", [])
        cost = item.get("total_cost", len(games) * 1000)
        total_lotto_spent += cost

        round_won = 0
        games_with_match = []

        # 당첨 정보가 있고 회차가 일치할 경우 대조
        win_info = lotto_winning if (lotto_winning and lotto_winning.get("round") == rnd) else None

        for idx, g in enumerate(games):
            slot = g.get("slot", chr(65 + idx))
            tag = g.get("tag", f"게임 {slot}")
            nums = g.get("numbers", [])
            match_res = {
                "slot": slot,
                "tag": tag,
                "numbers": nums,
                "matched_numbers": [],
                "has_bonus": False,
                "rank": None,
                "prize_amount": 0,
            }

            if win_info:
                check = check_single_game(
                    nums,
                    win_info["winning_numbers"],
                    win_info["bonus"],
                    win_info.get("first_prize", 0),
                )
                match_res["matched_numbers"] = check["matched_numbers"]
                match_res["has_bonus"] = check["has_bonus"]
                match_res["rank"] = check["rank"]
                match_res["prize_amount"] = check["prize_amount"]
                if check["rank"]:
                    lotto_rank_counts[check["rank"]] += 1
                    round_won += check["prize_amount"]

            games_with_match.append(match_res)

        total_lotto_won += round_won
        processed_lotto_history.append({
            "round": rnd,
            "purchase_date": item.get("purchase_date", ""),
            "total_cost": cost,
            "round_won": round_won,
            "games": games_with_match,
        })

    # 4. 연금복권 720+ 통계 및 매칭 결과 가공
    total_pension_spent = 0
    total_pension_won = 0
    pension_rank_counts = {
        "1등": 0, "2등": 0, "보너스": 0, "3등": 0, "4등": 0, "5등": 0, "6등": 0, "7등": 0
    }
    processed_pension_history = []

    for item in pension_history:
        rnd = item.get("round")
        tickets = item.get("tickets", [])
        sets = item.get("sets", [])
        cost = item.get("total_cost", 10000)
        total_pension_spent += cost

        round_won = 0
        p_win_info = pension_winning if (pension_winning and pension_winning.get("round") == rnd) else None
        ticket_results = []
        monthly_pension_desc = None

        if p_win_info and tickets:
            res = check_pension720_winning(tickets, p_win_info)
            ticket_results = res.get("ticket_results", [])
            monthly_pension_desc = res.get("monthly_pension")
            round_won = res.get("total_lump_sum", 0)
            for rk, cnt in res.get("prizes", {}).items():
                if rk in pension_rank_counts:
                    pension_rank_counts[rk] += cnt

        total_pension_won += round_won
        processed_pension_history.append({
            "round": rnd,
            "purchase_date": item.get("purchase_date", ""),
            "total_cost": cost,
            "round_won": round_won,
            "monthly_pension": monthly_pension_desc,
            "sets": sets,
            "ticket_results": ticket_results,
            "ticket_count": len(tickets),
        })

    # 5. 전체 종합 통계
    total_spent = total_lotto_spent + total_pension_spent
    total_won = total_lotto_won + total_pension_won
    net_profit = total_won - total_spent
    roi = round((total_won / total_spent * 100), 1) if total_spent > 0 else 0.0

    kst = timezone(timedelta(hours=9))
    now_kst_str = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S KST")

    dashboard_data = {
        "updated_at": now_kst_str,
        "summary": {
            "total_spent": total_spent,
            "total_won": total_won,
            "net_profit": net_profit,
            "roi_percent": roi,
            "total_lotto_spent": total_lotto_spent,
            "total_lotto_won": total_lotto_won,
            "total_pension_spent": total_pension_spent,
            "total_pension_won": total_pension_won,
            "lotto_rank_counts": lotto_rank_counts,
            "pension_rank_counts": pension_rank_counts,
        },
        "latest_winning": {
            "lotto645": lotto_winning,
            "pension720": pension_winning,
        },
        "lotto645": {
            "history": processed_lotto_history,
        },
        "pension720": {
            "history": processed_pension_history,
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 대시보드 데이터 빌드 완료 -> {output_path}")
    return dashboard_data


if __name__ == "__main__":
    build_dashboard_data()
