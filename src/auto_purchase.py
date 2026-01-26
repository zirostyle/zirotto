#!/usr/bin/env python3
"""
통합 로또 자동 구매 스크립트
한 번의 브라우저 세션으로 모든 작업을 수행합니다.

Features:
- 자동 로그인
- 예치금 자동 충전
- 연금복권 720+ 구매
- 로또 6/45 구매
- 텔레그램 알림
"""
import sys
import re
from playwright.sync_api import Playwright, sync_playwright, Page
from login import login
from balance import get_balance
from telegram_notifier import notify_balance, notify_charge, notify_lotto645_purchase, notify_lotto720_purchase

# Import functions
from charge import charge_balance
from lotto645 import purchase_lotto645
from lotto720 import purchase_lotto720


def run_all_tasks(playwright: Playwright) -> None:
    """
    한 번의 브라우저 세션으로 모든 로또 구매 작업을 수행합니다.
    """
    # Create browser, context, and page (only once!)
    print("🌐 브라우저 시작...")
    browser = playwright.chromium.launch(headless=True)
    
    # Use desktop viewport and user agent to avoid mobile site redirection
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
        MIN_REQUIRED = 10000  # 로또645 5게임 + 로또720 5게임
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
        print("🎫 연금복권 720 구매 중...")
        print("="*50)
        
        time.sleep(5)  # 충전 후 충분한 대기
        
        try:
            result_720 = purchase_lotto720(page)
            if result_720 and result_720.get('games', 0) > 0:
                print(f"✅ 연금복권 720 구매 완료! ({result_720['games']}게임, ₩{result_720['total_cost']:,})")
            else:
                print("⚠️ 연금복권 720 구매 실패")
        except Exception as e:
            error_msg = str(e)
            print(f"❌ 연금복권 720 구매 실패: {error_msg}")
            # 720 실패해도 645는 계속 진행
        
        time.sleep(5)  # 로또720 후 대기
        
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
