#!/usr/bin/env python3
"""
연금복권 720+ 자동 구매
참고: https://github.com/yoonbae81/lotto
"""
import json
import time
import re
from os import environ
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import Playwright, sync_playwright, Page
from login import login
from telegram_notifier import notify_lotto720_purchase

# .env loading is handled by login module import


def purchase_lotto720(page: Page) -> dict:
    """
    연금복권 720+를 구매합니다 (이미 로그인된 페이지 사용).
    
    Args:
        page: 이미 로그인된 Playwright Page 객체
        
    Returns:
        dict: {'games': 5, 'total_cost': 5000, 'numbers': str}
    """
    try:
        # Navigate to the Wrapper Page
        print("🚀 연금복권720 페이지 이동...")
        page.goto("https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72", timeout=30000, wait_until="domcontentloaded")
        
        # Access the game iframe
        print("  iframe 대기 중...")
        page.locator("#ifrm_tab").wait_for(state="visible", timeout=10000)
        
        frame = page.frame_locator("#ifrm_tab")
        
        # Wait for frame content
        frame.locator("#curdeposit, .lpdeposit").first.wait_for(state="attached", timeout=20000)
        print('✅ 게임 프레임 로드 완료')
        
        time.sleep(1)

        # Check Login Session
        user_id_val = frame.locator("input[name='USER_ID']").get_attribute("value")
        if not user_id_val:
            raise Exception("❌ 세션 만료: 게임 페이지에서 로그인 확인 실패")
        
        print(f"  로그인 ID: {user_id_val}")

        # Check Balance
        balance_val = frame.locator("#curdeposit").get_attribute("value")
        if not balance_val:
            balance_text = frame.locator(".lpdeposit").first.inner_text() 
            balance_val = balance_text.replace(",", "").replace("원", "").strip()
            
        try:
            current_balance = int(balance_val)
        except ValueError:
            current_balance = 0

        print(f"  게임 페이지 잔액: ₩{current_balance:,}")

        if current_balance == 0:
            raise Exception("❌ 잔액 부족: 예치금이 0원입니다.")

        # Dismiss popup if present
        if frame.locator("#popupLayerAlert").is_visible():
            frame.locator("#popupLayerAlert").get_by_role("button", name="확인").click()

        # Wait for the game UI
        frame.locator(".lotto720_btn_auto_number").wait_for(state="visible", timeout=15000)

        # Remove pause layer popups
        page.evaluate("""
            () => {
                const iframe = document.querySelector('#ifrm_tab');
                if (iframe && iframe.contentDocument) {
                    const doc = iframe.contentDocument;
                    const selectors = [
                        '#pause_layer_pop_02',
                        '#ele_pause_layer_pop02',
                        '.pause_layer_pop',
                        '.pause_bg'
                    ];
                    
                    selectors.forEach(selector => {
                        const elements = doc.querySelectorAll(selector);
                        elements.forEach(el => {
                            el.style.display = 'none';
                            el.style.visibility = 'hidden';
                            el.style.pointerEvents = 'none';
                        });
                    });
                }
            }
        """)

        # [자동번호] 클릭
        print("  자동번호 클릭...")
        frame.locator(".lotto720_btn_auto_number").click(force=True)
        time.sleep(2)

        # [선택완료] 클릭
        print("  선택완료 클릭...")
        frame.locator(".lotto720_btn_confirm_number").click()
        time.sleep(2)

        # Verify Amount
        payment_amount_el = frame.locator(".lotto720_price.lpcurpay")
        time.sleep(1)
        
        payment_amount_text = payment_amount_el.inner_text().strip()
        payment_val = int(re.sub(r'[^0-9]', '', payment_amount_text) or '0')

        if payment_val != 5000:
            print(f"❌ Error: 금액 불일치 (예상 5000원, 표시 {payment_val}원)")
            return {'games': 0, 'total_cost': 0, 'numbers': ''}

        # [구매하기] 클릭
        print("  구매하기 클릭...")
        frame.locator("a:has-text('구매하기')").first.click()
        time.sleep(2)
        
        # Handle Confirmation Popup
        confirm_popup = frame.locator("#lotto720_popup_confirm")
        confirm_popup.wait_for(state="visible", timeout=5000)
        
        # Click Final Purchase Button
        print("  최종 구매 확인...")
        confirm_popup.locator("a.btn_blue").click()
        time.sleep(3)
        
        print("✅ 연금복권 720+ 구매 완료!")
        notify_lotto720_purchase(True)
        return {'games': 5, 'total_cost': 5000, 'numbers': '자동 선택'}

    except Exception as e:
        error_msg = str(e)
        print(f"❌ 연금복권 720+ 구매 실패: {error_msg}")
        notify_lotto720_purchase(False, error_msg)
        raise


def run(playwright: Playwright) -> None:
    """연금복권 720+를 구매합니다 (독립 실행용)."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    page = context.new_page()
    
    try:
        login(page)
        purchase_lotto720(page)
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
