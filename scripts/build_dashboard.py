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
import base64
import hashlib
import hmac
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


def encrypt_payload(data: dict, pin: str = None) -> dict:
    """
    PBKDF2-HMAC-SHA256 및 Counter-Mode 스트림 암호화, HMAC 태그 인증을 사용해
    대시보드 데이터를 완벽하게 암호화합니다. (외부 라이브러리 불필요)
    """
    if not pin:
        pin = os.environ.get("DASHBOARD_PIN", "").strip()
    if not pin:
        raise ValueError("DASHBOARD_PIN 환경변수가 설정되지 않았습니다.")

    plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 50000)
    nonce = os.urandom(16)
    
    keystream = bytearray()
    counter = 0
    while len(keystream) < len(plaintext):
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        keystream.extend(block)
        counter += 1
        
    ct = bytes([p ^ k for p, k in zip(plaintext, keystream)])
    tag = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    
    return {
        "locked": True,
        "updated_at": data.get("updated_at", ""),
        "salt": base64.b64encode(salt).decode("utf-8"),
        "nonce": base64.b64encode(nonce).decode("utf-8"),
        "tag": base64.b64encode(tag).decode("utf-8"),
        "ct": base64.b64encode(ct).decode("utf-8"),
    }


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
            print(f"⚠️ purchased_lotto.json 로드 실패: {e}")

    pension_history = []
    if os.path.exists(pension_path):
        try:
            with open(pension_path, "r", encoding="utf-8") as f:
                pension_history = json.load(f).get("history", [])
        except Exception as e:
            print(f"⚠️ purchased_pension720.json 로드 실패: {e}")

    # 2. 최신 당첨 번호 실시간 조회
    print("🌐 네이버 검색을 통해 최신 로또 당첨 번호를 조회합니다...")
    lotto_winning = None
    try:
        lotto_winning = get_latest_lotto_winning_numbers()
        if lotto_winning:
            print(f"🎯 로또 6/45 최신 당첨 번호 확인: {lotto_winning.get('round')}회")
    except Exception as e:
        print(f"⚠️ 로또 당첨 번호 조회 실패: {e}")

    print("🌐 네이버 검색을 통해 최신 연금복권 720+ 당첨 번호를 조회합니다...")
    pension_winning = None
    try:
        pension_winning = get_latest_pension720_winning_numbers()
        if pension_winning:
            print(f"🎯 연금복권 720+ 최신 당첨 번호 확인: {pension_winning.get('round')}회")
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

        pwin_info = pension_winning if (pension_winning and pension_winning.get("round") == rnd) else None

        round_won = 0
        matched_tickets = []
        if pwin_info:
            for t in tickets:
                grp = t.get("group", 0)
                num = t.get("number", "")
                m = check_pension720_winning(grp, num, pwin_info["win_group"], pwin_info["win_number"], pwin_info["bonus_number"])
                if m["rank"]:
                    pension_rank_counts[m["rank"]] += 1
                    round_won += m["prize_lump_sum"]
                matched_tickets.append({
                    "group": grp,
                    "number": num,
                    "rank": m["rank"],
                    "matched_digits": m["matched_digits"],
                    "prize_monthly": m["prize_monthly"],
                    "prize_lump_sum": m["prize_lump_sum"],
                })
        else:
            for t in tickets:
                matched_tickets.append({
                    "group": t.get("group", 0),
                    "number": t.get("number", ""),
                    "rank": None,
                    "matched_digits": 0,
                    "prize_monthly": 0,
                    "prize_lump_sum": 0,
                })

        total_pension_won += round_won
        processed_pension_history.append({
            "round": rnd,
            "purchase_date": item.get("purchase_date", ""),
            "total_cost": cost,
            "round_won": round_won,
            "sets": sets,
            "tickets": matched_tickets,
        })

    # 5. 종합 요약
    total_spent = total_lotto_spent + total_pension_spent
    total_won = total_lotto_won + total_pension_won
    net_profit = total_won - total_spent
    roi = round((total_won / total_spent * 100), 1) if total_spent > 0 else 0.0

    kst = timezone(timedelta(hours=9))
    updated_at_str = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S (KST)")

    raw_data = {
        "updated_at": updated_at_str,
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

    # 6. PIN 번호 암호화 (DASHBOARD_PIN 환경변수 필수)
    pin = os.environ.get("DASHBOARD_PIN", "").strip()
    if not pin:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            pin = os.environ.get("DASHBOARD_PIN", "").strip()
        except Exception:
            pass
    if not pin:
        raise ValueError("DASHBOARD_PIN 환경변수가 설정되지 않았습니다. GitHub Secrets 또는 .env 파일에 DASHBOARD_PIN을 설정해주세요.")
    encrypted_packet = encrypt_payload(raw_data, pin)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(encrypted_packet, f, ensure_ascii=False, indent=2)

    print(f"🔒 대시보드 데이터 암호화 완료 (PIN: {len(pin)}자리) -> {output_path}")
    return encrypted_packet


if __name__ == "__main__":
    build_dashboard_data()
