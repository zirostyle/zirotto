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
from pathlib import Path
from datetime import datetime, timedelta, timezone
try:
    from dotenv import load_dotenv
    project_root = Path(__file__).resolve().parent.parent
    if (project_root / '.env').exists():
        load_dotenv(dotenv_path=project_root / '.env')
    load_dotenv()
except ImportError:
    pass

from playwright.sync_api import Playwright, sync_playwright
from login import login
from balance import get_balance
from telegram_notifier import notify_balance, notify_charge, notify_lotto720_purchase, notify_lotto_result
from check_results import run_result_check

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


def _notify_latest_lotto_result(page=None) -> None:
    """
    1) 최신 당첨번호 확인
    2) 내 구매번호와 대조 후 당첨 결과 리포트 알림
    """
    try:
        run_result_check()
    except Exception as e:
        print(f"⚠️ 당첨 결과 확인/대조 중 오류: {e}")


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

        # Step 3: 사전 예치금 잔액 확인 및 부족 시 자동 충전 (구매 전 필수 점검)
        print("\n" + "=" * 50)
        print("💰 사전 잔액 점검 및 예치금 충전 확인...")
        print("=" * 50)
        try:
            balance_info = _get_balance_resilient(page)
            print(f"💰 현재 예치금 잔액: {balance_info['deposit_balance']:,}원")
            print(f"🛒 현재 구매가능 금액: {balance_info['available_amount']:,}원")
            print(f"🎯 금주 총 구매 필요 금액: ₩{MIN_REQUIRED_NEXT:,} (연금복권 ₩{lotto720_amount:,} + 로또645 ₩{lotto645_amount:,})")

            if balance_info['available_amount'] < MIN_REQUIRED_NEXT:
                print(f"💳 잔액 부족 (보유: ₩{balance_info['available_amount']:,} < 필요: ₩{MIN_REQUIRED_NEXT:,}). ₩{CHARGE_AMOUNT:,} 충전 진행...")
                try:
                    success = charge_balance(page, CHARGE_AMOUNT)
                    notify_charge(CHARGE_AMOUNT, bool(success))
                    if success:
                        print(f"✅ 충전 완료! ₩{CHARGE_AMOUNT:,}")
                        time.sleep(2)
                        balance_info = _get_balance_resilient(page)
                        print(f"🛒 충전 후 구매가능 금액: ₩{balance_info['available_amount']:,}")
                    else:
                        print(f"❌ 예치금 충전 실패")
                except Exception as e:
                    print(f"❌ 충전 중 오류 발생: {e}")
                    notify_charge(CHARGE_AMOUNT, False)
            else:
                print(f"✅ 구매 잔액 충분: ₩{balance_info['available_amount']:,}")
        except Exception as e:
            print(f"⚠️ 사전 잔액/충전 점검 실패: {e}")

        # Step 4: Buy Lotto 720 (연금복권 720+ 10,000원 = 2세트, 10매)
        print("\n" + "=" * 50)
        print(f"🎟️ 연금복권 720+ 구매 중... (목표: ₩{lotto720_amount:,})")
        print("=" * 50)
        try:
            result_720 = purchase_lotto720(page, lotto720_amount)
            if result_720 and result_720.get('total_cost', 0) > 0:
                print(f"✅ 연금복권 720+ 구매 완료! (₩{result_720['total_cost']:,})")
            else:
                print("⚠️ 연금복권 720+ 구매 결과를 확인할 수 없습니다.")
        except Exception as e:
            print(f"❌ 연금복권 720+ 구매 실패: {e}")

        # Step 5: Buy Lotto 645 (로또 6/45 - 우주의 기운 번호)
        lotto645_enabled = _is_enabled("ENABLE_LOTTO645", "1") and _is_lotto645_date_open()
        if lotto645_enabled:
            # 금주 회차 중복 구매 방지 검사
            from lotto645 import get_current_round
            from check_results import get_purchased_lotto_from_file
            cur_round = get_current_round(page)
            existing_record = get_purchased_lotto_from_file(cur_round)
            if existing_record and len(existing_record.get("games", [])) >= 5:
                print("\n" + "=" * 50)
                print(f"⏭️ 로또 6/45 제 {cur_round}회는 이미 {len(existing_record['games'])}게임 구매 완료되어 중복 구매를 건너뜁니다.")
                print("=" * 50)
            else:
                print("\n" + "=" * 50)
                print("🎫 로또 6/45 구매 중...")
                print("=" * 50)
                
                try:
                    result_645 = purchase_lotto645(page)
                    if result_645 and result_645.get('games', 0) > 0:
                        print(f"✅ 로또 6/45 구매 완료! ({result_645['games']}게임, ₩{result_645['total_cost']:,})")
                    else:
                        print("⚠️ 로또 6/45 구매 실패 - 결과를 확인할 수 없습니다.")
                except Exception as e:
                    error_msg = str(e)
                    if "구매 불가" in error_msg or "구매.*시간" in error_msg:
                        print(f"⏭️  {error_msg}")
                        print("   (정상적인 구매 불가 시간대입니다)")
                    elif "ERR_CONNECTION_TIMED_OUT" in error_msg or "Timeout" in error_msg:
                        print(f"⏭️  로또 6/45 접속 지연/타임아웃으로 이번 회차는 건너뜁니다: {e}")
                    else:
                        print(f"❌ 로또 6/45 구매 실패: {e}")
        else:
            raw_from = str(os.environ.get("LOTTO645_ENABLE_FROM", "")).strip()
            if not _is_enabled("ENABLE_LOTTO645", "1"):
                print("\n⏭️ 로또 6/45 구매는 비활성화되어 건너뜁니다. (ENABLE_LOTTO645=0)")
            elif raw_from:
                print(f"\n⏭️ 로또 6/45 구매는 시작일({raw_from}, KST) 이전이라 건너뜁니다.")
            else:
                print("\n⏭️ 로또 6/45 구매를 건너뜁니다.")

        # Step 6: 구매 완료 후 최종 잔액 확인 및 텔레그램 알림
        print("\n" + "=" * 50)
        print("💰 구매 완료 후 최종 잔액 확인 중...")
        print("=" * 50)
        try:
            balance_info = _get_balance_resilient(page)
            print(f"💰 최종 예치금 잔액: {balance_info['deposit_balance']:,}원")
            print(f"🛒 최종 구매가능: {balance_info['available_amount']:,}원")
            notify_balance(balance_info['deposit_balance'], balance_info['available_amount'])
        except Exception as e:
            print(f"⚠️ 최종 잔액 점검 실패: {e}")
        
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
