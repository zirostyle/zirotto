#!/usr/bin/env python3
"""
통합 로또 자동 구매 스크립트
한 번의 브라우저 세션으로 모든 작업을 수행합니다.

Features:
- 자동 로그인 및 세션 유지
- 예치금 자동 충전 (잔액 부족 시)
- 연금복권 720+ 자동 구매
- 로또 6/45 자동 구매
- 구매 번호 텔레그램 알림
- 구매 완료 검증
"""
import os
import json
from datetime import datetime, timedelta, timezone
from playwright.sync_api import Playwright, sync_playwright
from login import login
from balance import get_balance
from telegram_notifier import notify_balance, notify_charge, notify_lotto720_purchase
from check_results import (
    get_latest_lotto_winning_numbers,
    get_my_lotto_purchases,
    check_winning,
)
from telegram_notifier import notify_lotto_result

# Import functions
from charge import charge_balance
from lotto645 import purchase_lotto645
from lotto720 import purchase_lotto720


def _safe_int_env(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, str(default))).replace(",", "").strip())
    except Exception:
        return default


def _safe_manual_games_count() -> int:
    try:
        raw = os.environ.get("MANUAL_NUMBERS", "[]")
        data = json.loads(raw)
        if isinstance(data, list):
            return len(data)
    except Exception:
        pass
    return 0


def _is_enabled(name: str, default: str = "1") -> bool:
    raw = str(os.environ.get(name, default)).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _is_lotto645_date_open() -> bool:
    """
    LOTTO645_ENABLE_FROM(YYYY-MM-DD) 날짜(한국시간)부터 6/45 구매를 허용합니다.
    """
    raw = str(os.environ.get("LOTTO645_ENABLE_FROM", "")).strip()
    if not raw:
        return True

    try:
        # Python 3.9 zoneinfo 우선 사용, 실패 시 UTC+9 고정 오프셋 사용
        try:
            from zoneinfo import ZoneInfo  # type: ignore
            now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
        except Exception:
            now_kst = datetime.now(timezone(timedelta(hours=9)))

        from_date = datetime.strptime(raw, "%Y-%m-%d").date()
        return now_kst.date() >= from_date
    except Exception:
        print(f"⚠️ LOTTO645_ENABLE_FROM 형식이 올바르지 않습니다: '{raw}' (예: 2026-02-23)")
        return True


def _get_balance_resilient(page, attempts: int = 3):
    """
    잔액 조회가 실패할 때 재로그인까지 포함해 재시도합니다.
    """
    import time

    last_error = None
    for i in range(attempts):
        try:
            if i > 0:
                print(f"🔄 잔액 조회 재시도 {i + 1}/{attempts}")
            return get_balance(page)
        except Exception as e:
            last_error = e
            print(f"⚠️ 잔액 조회 실패: {e}")
            try:
                # 세션/도메인 꼬임 복구
                page.goto("https://www.dhlottery.co.kr/main", timeout=60000, wait_until="domcontentloaded")
                time.sleep(1)
                login(page, max_retries=2)
            except Exception as relogin_error:
                print(f"⚠️ 재로그인 실패: {relogin_error}")
            time.sleep(2)

    raise Exception(f"잔액 조회 최종 실패: {last_error}")


def _notify_latest_lotto_result(page) -> None:
    """
    1) 최신 당첨번호 알림
    2) 내 구매번호와 대조 후 당첨여부 알림
    """
    print("\n" + "=" * 50)
    print("🎯 당첨번호 확인 및 대조 중...")
    print("=" * 50)

    try:
        winning_info = get_latest_lotto_winning_numbers()
        print(f"🎰 {winning_info['round']}회 당첨번호: {' '.join([f'{n:02d}' for n in winning_info['winning_numbers']])} + {winning_info['bonus']:02d}")
        print(f"📅 추첨일: {winning_info['draw_date']}")
    except Exception as e:
        print(f"❌ 당첨번호 조회 실패: {e}")
        return

    try:
        purchases = get_my_lotto_purchases(page)
    except Exception as e:
        print(f"⚠️ 구매내역 조회 실패: {e}")
        purchases = []

    my_purchase = None
    for p in purchases:
        if p.get("round") == winning_info["round"]:
            my_purchase = p
            break

    if not my_purchase:
        print(f"⚠️ {winning_info['round']}회 구매내역이 없습니다.")
        notify_lotto_result(
            winning_info["round"],
            winning_info["winning_numbers"],
            winning_info["bonus"],
            {},
        )
        return

    prizes = {}
    for numbers in my_purchase.get("numbers", []):
        rank, _ = check_winning(numbers, winning_info["winning_numbers"], winning_info["bonus"])
        if rank:
            prizes[rank] = prizes.get(rank, 0) + 1

    notify_lotto_result(
        winning_info["round"],
        winning_info["winning_numbers"],
        winning_info["bonus"],
        prizes if prizes else {},
    )

    if prizes:
        print(f"✅ 당첨 내역 발견: {prizes}")
    else:
        print("ℹ️ 당첨 내역 없음")


def run_all_tasks(playwright: Playwright) -> None:
    """
    한 번의 브라우저 세션으로 모든 로또 구매 작업을 수행합니다.
    """
    # Create browser, context, and page (only once!)
    print("🌐 브라우저 시작...")
    browser = playwright.chromium.launch(headless=True)
    
    # Use desktop viewport and user agent
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    page = context.new_page()
    
    try:
        # Step 1: Login once
        print("\n" + "="*50)
        print("🔐 로그인 중...")
        print("="*50)
        login(page)

        import time
        time.sleep(2)

        # Step 1 + 2: 당첨번호 알림 + 내 구매번호 대조 알림
        _notify_latest_lotto_result(page)

        # 준비값
        lotto720_amount = _safe_int_env("LOTTO720_AMOUNT", 10000)
        auto_games = _safe_int_env("AUTO_GAMES", 5)
        manual_games = _safe_manual_games_count()
        lotto645_amount = (auto_games + manual_games) * 1000
        MIN_REQUIRED_NEXT = max(lotto720_amount + lotto645_amount, 10000)
        CHARGE_AMOUNT = 20000

        # Step 3: Buy Lotto 645
        lotto645_enabled = _is_enabled("ENABLE_LOTTO645", "1") and _is_lotto645_date_open()
        if lotto645_enabled:
            print("\n" + "="*50)
            print("🎫 로또 645 구매 중...")
            print("="*50)
            
            try:
                result_645 = purchase_lotto645(page)
                
                if result_645 and result_645.get('games', 0) > 0:
                    print(f"✅ 로또 645 구매 완료! ({result_645['games']}게임, ₩{result_645['total_cost']:,})")
                else:
                    print("⚠️ 로또 645 구매 실패 - 결과를 확인할 수 없습니다.")
                    
            except Exception as e:
                error_msg = str(e)
                if "구매 불가" in error_msg or "구매.*시간" in error_msg:
                    print(f"⏭️  {error_msg}")
                    print("   (정상적인 구매 불가 시간대입니다)")
                elif "ERR_CONNECTION_TIMED_OUT" in error_msg or "Timeout" in error_msg:
                    print(f"⏭️  로또 645 접속 지연/타임아웃으로 이번 회차는 건너뜁니다: {e}")
                else:
                    print(f"❌ 로또 645 구매 실패: {e}")
                    # 645 단일 실패로 전체 워크플로우를 중단하지 않음
        else:
            raw_from = str(os.environ.get("LOTTO645_ENABLE_FROM", "")).strip()
            if not _is_enabled("ENABLE_LOTTO645", "1"):
                print("\n⏭️ 로또 6/45 구매는 비활성화되어 건너뜁니다. (ENABLE_LOTTO645=0)")
            elif raw_from:
                print(f"\n⏭️ 로또 6/45 구매는 시작일({raw_from}, KST) 이전이라 건너뜁니다.")
            else:
                print("\n⏭️ 로또 6/45 구매를 건너뜁니다.")

        # Step 4: Buy Lotto 720
        pre_720_available = None
        try:
            pre_720_balance_info = _get_balance_resilient(page)
            pre_720_available = pre_720_balance_info['available_amount']
            print(f"📌 720 구매 전 구매가능 금액: ₩{pre_720_available:,}")
        except Exception:
            pass

        print("\n" + "="*50)
        print(f"🎟️ 연금복권 720 구매 중... (목표: ₩{lotto720_amount:,})")
        print("="*50)

        try:
            result_720 = purchase_lotto720(page, lotto720_amount)
            post_720_balance = None
            try:
                post_720_info = _get_balance_resilient(page)
                post_720_balance = post_720_info['available_amount']
            except Exception:
                pass

            verified = False
            spent = None
            if post_720_balance is not None and pre_720_available is not None:
                spent = pre_720_available - post_720_balance
                print(f"📌 720 구매 후 구매가능 금액: ₩{post_720_balance:,} (차감: ₩{spent:,})")
                if spent >= lotto720_amount:
                    verified = True
                    print(f"✅ 연금복권 720 구매 검증 성공 (차감: ₩{spent:,})")
            else:
                print("⚠️ 720 구매 전/후 잔액 조회 일부 실패")

            if result_720:
                bb = result_720.get("balance_before")
                ba = result_720.get("balance_after")
                dialogs = result_720.get("dialogs") or []
                sale_message = result_720.get("sale_message") or ""
                success_signals = result_720.get("success_signals")
                if bb is not None or ba is not None:
                    print(f"📌 720 내부 잔액 스냅샷: before={bb}, after={ba}")
                if dialogs:
                    print(f"📌 720 dialog: {dialogs}")
                if sale_message:
                    print(f"📌 720 결과 문구: {sale_message}")
                if success_signals is not None:
                    print(f"📌 720 내부 성공 신호: {success_signals}")

            if result_720 and result_720.get('total_cost', 0) > 0 and verified:
                print(f"✅ 연금복권 720 구매 완료! (₩{result_720['total_cost']:,})")
                notify_lotto720_purchase(
                    True,
                    numbers=result_720.get('numbers'),
                    amount=result_720['total_cost'],
                    purchase_count=max(1, result_720['total_cost'] // 5000),
                )
            else:
                print("⚠️ 연금복권 720 구매 미검증 - 성공 알림을 보내지 않습니다.")
                notify_lotto720_purchase(False, "구매내역/잔액 차감 검증 실패")
        except Exception as e:
            print(f"❌ 연금복권 720 구매 실패: {e}")
            notify_lotto720_purchase(False, str(e))

        # Step 5: 잔액 확인 및 부족 시 충전
        print("\n" + "=" * 50)
        print("💰 잔액 확인 및 충전 점검 중...")
        print("=" * 50)
        try:
            balance_info = _get_balance_resilient(page)
            print(f"💰 예치금 잔액: {balance_info['deposit_balance']:,}원")
            print(f"🛒 구매가능: {balance_info['available_amount']:,}원")
            notify_balance(balance_info['deposit_balance'], balance_info['available_amount'])

            if balance_info['available_amount'] < MIN_REQUIRED_NEXT:
                print(f"💳 잔액 부족 (₩{balance_info['available_amount']:,}). ₩{CHARGE_AMOUNT:,} 충전 중...")
                try:
                    success = charge_balance(page, CHARGE_AMOUNT)
                    notify_charge(CHARGE_AMOUNT, bool(success))
                    if success:
                        print(f"✅ 충전 완료! ₩{CHARGE_AMOUNT:,}")
                    else:
                        print(f"❌ 충전 실패 (다음 회차 전 확인 필요)")
                except Exception as e:
                    print(f"❌ 충전 중 에러 발생: {e}")
                    notify_charge(CHARGE_AMOUNT, False)
            else:
                print(f"✅ 잔액 충분: ₩{balance_info['available_amount']:,}")
        except Exception as e:
            print(f"⚠️ 잔액/충전 점검 실패: {e}")
        
        print("\n" + "="*50)
        print("✅ 모든 작업 완료!")
        print("="*50)
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        raise
        
    finally:
        # Cleanup
        print("\n🧹 브라우저 종료 중...")
        context.close()
        browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run_all_tasks(playwright)
# Test trigger Mon Jan 26 07:40:08 AM UTC 2026
