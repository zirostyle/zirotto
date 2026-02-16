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
from playwright.sync_api import Playwright, sync_playwright
from login import login
from balance import get_balance
from telegram_notifier import notify_balance, notify_charge

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
    # 동행복권 플랫폼 판별(모바일 리다이렉트) 우회를 위해 platform/userAgentData를 데스크톱으로 고정
    context.add_init_script("""
        Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
        if (navigator.userAgentData) {
            Object.defineProperty(navigator.userAgentData, 'mobile', { get: () => false });
        }
    """)
    page = context.new_page()
    
    try:
        # Step 1: Login once
        print("\n" + "="*50)
        print("🔐 로그인 중...")
        print("="*50)
        login(page)
        
        # Step 2: Check balance
        print("\n" + "="*50)
        print("💰 잔액 확인 중...")
        print("="*50)
        import time
        time.sleep(3)  # 로그인 후 대기
        
        balance_info = get_balance(page)
        print(f"💰 예치금 잔액: {balance_info['deposit_balance']:,}원")
        print(f"🛒 구매가능: {balance_info['available_amount']:,}원")
        
        # Send balance notification
        notify_balance(balance_info['deposit_balance'], balance_info['available_amount'])
        
        time.sleep(3)  # 잔액 확인 후 대기
        
        # Step 3: Charge if needed
        lotto720_amount = _safe_int_env("LOTTO720_AMOUNT", 10000)
        auto_games = _safe_int_env("AUTO_GAMES", 5)
        manual_games = _safe_manual_games_count()
        lotto645_amount = (auto_games + manual_games) * 1000
        MIN_REQUIRED = max(lotto720_amount + lotto645_amount, 10000)
        CHARGE_AMOUNT = 20000
        
        if balance_info['available_amount'] < MIN_REQUIRED:
            print("\n" + "="*50)
            print(f"💳 잔액 부족 (₩{balance_info['available_amount']:,}). ₩{CHARGE_AMOUNT:,} 충전 중...")
            print("="*50)
            
            try:
                success = charge_balance(page, CHARGE_AMOUNT)
                if success:
                    print(f"✅ 충전 완료! ₩{CHARGE_AMOUNT:,}")
                    notify_charge(CHARGE_AMOUNT, True)
                else:
                    print(f"❌ 충전 실패 (현재 잔액으로 진행)")
                    notify_charge(CHARGE_AMOUNT, False)
            except Exception as e:
                print(f"❌ 충전 중 에러 발생: {e}")
                notify_charge(CHARGE_AMOUNT, False)
                # 충전 실패해도 현재 잔액으로 계속 진행
        else:
            print(f"\n✅ 잔액 충분: ₩{balance_info['available_amount']:,}")
        
        # Step 4: Buy Lotto 720
        print("\n" + "="*50)
        print(f"🎟️ 연금복권 720 구매 중... (목표: ₩{lotto720_amount:,})")
        print("="*50)

        try:
            result_720 = purchase_lotto720(page, lotto720_amount)
            if result_720 and result_720.get('total_cost', 0) > 0:
                print(f"✅ 연금복권 720 구매 완료! (₩{result_720['total_cost']:,})")
            else:
                print("⚠️ 연금복권 720 구매 실패 - 결과를 확인할 수 없습니다.")
        except Exception as e:
            print(f"❌ 연금복권 720 구매 실패: {e}")
            print("   로또 6/45 구매는 계속 진행합니다.")
        
        # Step 5: Buy Lotto 645
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
            else:
                print(f"❌ 로또 645 구매 실패: {e}")
                raise
        
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
