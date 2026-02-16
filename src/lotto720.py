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


def purchase_lotto720(page: Page, total_amount: int = 10000) -> dict:
    """
    연금복권 720+를 구매합니다 (이미 로그인된 페이지 사용).
    
    Args:
        page: 이미 로그인된 Playwright Page 객체
        total_amount: 구매할 총 금액 (5000=5게임, 10000=10게임 등, 1000원 단위)
        
    Returns:
        dict: {'games': int, 'total_cost': int, 'numbers': str}
    """
    games_per_purchase = 5
    cost_per_purchase = 5000
    num_purchases = total_amount // cost_per_purchase
    
    if num_purchases < 1:
        print("⚠️ 연금복권: 최소 5,000원(5게임) 이상 구매 필요")
        return {'games': 0, 'total_cost': 0, 'numbers': ''}
    
    all_numbers = []
    total_games = 0
    
    for purchase_num in range(num_purchases):
        try:
            print(f"\n🎟️ 연금복권720 구매 ({purchase_num + 1}/{num_purchases}) - 5게임 5,000원")
            
            # Navigate to game page (데스크톱 필수 - 모바일은 리다이렉트됨)
            # 데스크톱 User-Agent/뷰포트 설정 후 이동
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
            
            page.goto("https://el.dhlottery.co.kr/game/LP72/game720.jsp", timeout=60000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=20000)
            time.sleep(3)
            
            current_url = page.url
            if "m.dhlottery.co.kr" in current_url:
                print("  ⚠️ 모바일 리다이렉트됨 - www 경유 재시도")
                page.goto("https://www.dhlottery.co.kr", timeout=30000)
                time.sleep(2)
                page.goto("https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72", timeout=60000)
                time.sleep(3)
            
            if "m.dhlottery.co.kr" in page.url:
                print("  ⚠️ 연금복권 모바일 전용 사이트 - 구매 건너뜀")
                break
            
            iframe_exists = page.locator("#ifrm_tab").count() > 0
            frame = page.frame_locator("#ifrm_tab") if iframe_exists else page
            if iframe_exists:
                frame.locator("#curdeposit, .lpdeposit").first.wait_for(state="attached", timeout=20000)
            
            time.sleep(1)
            if not frame.locator("input[name='USER_ID']").get_attribute("value"):
                raise Exception("❌ 세션 만료")
            
            if frame.locator("#popupLayerAlert").is_visible():
                frame.locator("#popupLayerAlert").get_by_role("button", name="확인").click()
            
            frame.locator(".lotto720_btn_auto_number").wait_for(state="visible", timeout=15000)
            
            page.evaluate("""() => {
                const iframe = document.querySelector('#ifrm_tab');
                if (iframe?.contentDocument) {
                    ['#pause_layer_pop_02','.pause_layer_pop','.pause_bg'].forEach(s => {
                        iframe.contentDocument.querySelectorAll(s).forEach(el => {
                            el.style.display = 'none';
                        });
                    });
                }
            }""")
            
            frame.locator(".lotto720_btn_auto_number").click(force=True)
            time.sleep(2)
            frame.locator(".lotto720_btn_confirm_number").click()
            time.sleep(2)
            
            payment_val = int(re.sub(r'[^0-9]', '', frame.locator(".lotto720_price.lpcurpay").inner_text() or '0'))
            if payment_val != 5000:
                raise Exception(f"금액 불일치 (표시: {payment_val}원)")
            
            frame.locator("a:has-text('구매하기')").first.click()
            time.sleep(2)
            frame.locator("#lotto720_popup_confirm").wait_for(state="visible", timeout=5000)
            frame.locator("#lotto720_popup_confirm a.btn_blue").click()
            time.sleep(3)
            
            total_games += 5
            all_numbers.append("자동 5게임")
            print(f"  ✅ {purchase_num + 1}차 구매 완료 (누적 {total_games}게임)")
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ 연금복권 구매 실패 ({purchase_num + 1}차): {error_msg}")
            if total_games == 0:
                notify_lotto720_purchase(False, error_msg=error_msg)
                raise
            break
    
    if total_games > 0:
        numbers_str = "\n".join(all_numbers) if all_numbers else "자동 선택"
        notify_lotto720_purchase(True, numbers=numbers_str, total_amount=total_games * 1000)
        return {'games': total_games, 'total_cost': total_games * 1000, 'numbers': numbers_str}
    
    return {'games': 0, 'total_cost': 0, 'numbers': ''}


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
