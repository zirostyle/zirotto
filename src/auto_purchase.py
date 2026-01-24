#!/usr/bin/env python3
"""
통합 로또 자동 구매 스크립트
한 번의 브라우저 세션으로 모든 작업을 수행합니다.
"""
import sys
import re
from playwright.sync_api import Playwright, sync_playwright, Page
from login import login
from balance import get_balance
from telegram_notifier import notify_balance, notify_charge, notify_lotto720_purchase, notify_lotto645_purchase

# Import charge and purchase functions
from charge import charge_balance
from lotto720 import purchase_lotto720
from lotto645 import purchase_lotto645


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
        balance_info = get_balance(page)
        print(f"💰 예치금 잔액: {balance_info['deposit_balance']:,}원")
        print(f"🛒 구매가능: {balance_info['available_amount']:,}원")
        
        # Send balance notification
        notify_balance(balance_info['deposit_balance'], balance_info['available_amount'])
        
        # Step 3: Charge if needed
        MIN_REQUIRED = 10000
        CHARGE_AMOUNT = 20000
        
        if balance_info['available_amount'] < MIN_REQUIRED:
            print("\n" + "="*50)
            print(f"💳 잔액 부족 (₩{balance_info['available_amount']:,}). ₩{CHARGE_AMOUNT:,} 충전 중...")
            print("="*50)
            
            charge_balance(page, CHARGE_AMOUNT)
            print(f"✅ 충전 완료!")
            
            # Send charge notification
            notify_charge(CHARGE_AMOUNT)
        else:
            print(f"\n✅ 잔액 충분 (₩{balance_info['available_amount']:,})")
        
        # Step 4: Buy Lotto 720
        print("\n" + "="*50)
        print("🎫 로또 720 구매 중...")
        print("="*50)
        
        result_720 = purchase_lotto720(page)
        print("✅ 로또 720 구매 완료!")
        
        # Step 5: Buy Lotto 645
        print("\n" + "="*50)
        print("🎫 로또 645 구매 중...")
        print("="*50)
        
        result_645 = purchase_lotto645(page)
        print("✅ 로또 645 구매 완료!")
        
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
