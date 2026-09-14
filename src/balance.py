#!/usr/bin/env python3
import re
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import Playwright, sync_playwright, Page, TimeoutError as PlaywrightTimeoutError
from login import login
from telegram_notifier import notify_balance

# .env loading is handled by login module import


def find_element_with_retry(page: Page, selectors: list, element_name: str, max_retries: int = 3) -> str:
    """
    여러 셀렉터를 시도하며 요소를 찾습니다.
    
    Args:
        page: Playwright Page 객체
        selectors: 시도할 셀렉터 리스트
        element_name: 요소 이름 (로깅용)
        max_retries: 최대 재시도 횟수
        
    Returns:
        str: 요소의 텍스트 내용
    """
    for retry in range(max_retries):
        if retry > 0:
            print(f"🔄 재시도 {retry}/{max_retries-1}: {element_name}")
            page.reload(wait_until="networkidle", timeout=30000)
            time.sleep(3)
        
        for selector in selectors:
            try:
                print(f"🔍 시도 중: {selector}")
                element = page.locator(selector).first
                element.wait_for(state="attached", timeout=5000)
                
                text = element.inner_text(timeout=3000).strip()
                if text:
                    print(f"✅ 찾음: {selector} = '{text}'")
                    return text
                else:
                    print(f"⚠️ 요소는 있으나 텍스트 없음: {selector}")
            except PlaywrightTimeoutError:
                print(f"⏱️ 타임아웃: {selector}")
            except Exception as e:
                print(f"❌ 에러 ({selector}): {e}")
    
    raise Exception(f"{element_name}을(를) 찾을 수 없습니다. 모든 셀렉터와 재시도 실패.")


def get_balance(page: Page) -> dict:
    """
    마이페이지에서 예치금 잔액과 구매가능 금액을 조회합니다.
    
    Args:
        page: 로그인된 Playwright Page 객체
    
    Returns:
        dict: {
            'deposit_balance': int,  # 예치금 잔액 (원)
            'available_amount': int  # 구매가능 금액 (원)
        }
    """
    # Navigate to My Page
    print("🔍 마이페이지로 이동 중...")
    page.goto("https://www.dhlottery.co.kr/mypage/home", timeout=60000, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=60000)
    
    # Wait for page to fully load
    print("⏳ 페이지 로딩 대기 중...")
    time.sleep(5)
    
    # Take a screenshot for debugging
    page.screenshot(path="debug_mypage.png")
    print("📸 스크린샷 저장: debug_mypage.png")
    
    # Dump HTML for debugging
    html_content = page.content()
    with open("debug_mypage.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("📄 HTML 저장: debug_mypage.html")
    
    # Check if we're actually logged in
    current_url = page.url
    print(f"📍 현재 URL: {current_url}")
    
    # Try multiple selectors for deposit balance
    deposit_selectors = [
        "#totalAmt",
        "[id='totalAmt']",
        "span#totalAmt",
        ".total_amt",
        "//span[@id='totalAmt']",
        "//div[contains(@class, 'deposit')]//span"
    ]
    
    # Try multiple selectors for available amount
    available_selectors = [
        "#divCrntEntrsAmt",
        "[id='divCrntEntrsAmt']",
        "div#divCrntEntrsAmt",
        ".crnt_entrs_amt",
        "//div[@id='divCrntEntrsAmt']",
        "//div[contains(@class, 'available')]//span"
    ]
    
    print("🔍 잔액 요소를 찾는 중...")
    
    try:
        # Get deposit balance
        deposit_text = find_element_with_retry(page, deposit_selectors, "예치금 잔액")
        print(f"💰 예치금 텍스트: {deposit_text}")
        
        # Get available amount
        available_text = find_element_with_retry(page, available_selectors, "구매가능 금액")
        print(f"🛒 구매가능 텍스트: {available_text}")
        
        # Parse amounts (remove non-digits)
        deposit_balance = int(re.sub(r'[^0-9]', '', deposit_text))
        available_amount = int(re.sub(r'[^0-9]', '', available_text))
        
        return {
            'deposit_balance': deposit_balance,
            'available_amount': available_amount
        }
    except Exception as e:
        print(f"❌ 잔액 조회 실패: {e}")
        print("📋 페이지 내용 일부:")
        print(html_content[:1000])
        raise


def run(playwright: Playwright) -> dict:
    """로그인 후 잔액 정보를 조회합니다."""
    # Create browser, context, and page
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    try:
        # Perform login
        login(page)
        
        # Get balance information
        balance_info = get_balance(page)
        
        # Print results in a clean format
        print(f"💰 예치금 잔액: {balance_info['deposit_balance']:,}원")
        print(f"🛒 구매가능: {balance_info['available_amount']:,}원")
        
        # Send telegram notification
        notify_balance(balance_info['deposit_balance'], balance_info['available_amount'])
        
        return balance_info
        
    except Exception as e:
        print(f"❌ Error: {e}")
        raise
    finally:
        # Cleanup
        context.close()
        browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
