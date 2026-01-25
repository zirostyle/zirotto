#!/usr/bin/env python3
import os
import re
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import Playwright, sync_playwright, Page
from login import login
from telegram_notifier import notify_charge

# .env loading is handled by login module import

CHARGE_PIN = os.environ.get('CHARGE_PIN')

def parse_keypad(page: Page) -> dict:
    """
    랜덤 키패드 이미지를 OCR로 분석하여 각 숫자의 위치를 파악합니다.
    
    키패드 구조:
    - 숫자 0-9: 10개
    - 전체삭제: 1개
    - 백스페이스: 1개
    - 총 12개 버튼
    
    Args:
        page: Playwright Page 객체
        
    Returns:
        dict: {숫자(str): element} 형태의 버튼 매핑 (0-9만 포함)
        
    Raises:
        Exception: 키패드 버튼을 찾지 못했을 경우
    """
    import pytesseract
    from PIL import Image, ImageEnhance, ImageFilter
    import io

    # 키패드 이미지 대기
    # Updated from .kpd-layer to .nppfs-keypad based on browser inspection
    keypad_selector = ".nppfs-keypad"
    page.wait_for_selector(keypad_selector, state="visible")
    
    # 키패드 버튼들 가져오기
    buttons = page.locator("img.kpd-data")
    count = buttons.count()
    
    if count == 0:
        raise Exception("No keypad buttons found")

    # 버튼 위치 정보 수집
    button_positions = []
    for i in range(count):
        btn = buttons.nth(i)
        box = btn.bounding_box()
        # box['width'] > 0 and box['height'] > 0 check to prevent ZeroDivisionError later
        if box and box['width'] > 0 and box['height'] > 0:
            button_positions.append({
                'element': btn,
                'x': box['x'],
                'y': box['y'],
                'w': box['width'],
                'h': box['height']
            })

    # 전체 키패드 영역 스크린샷 (캡처 후 메모리에서 처리)
    time.sleep(1) # Wait for animation/render
    keypad_layer = page.locator(keypad_selector)
    keypad_box = keypad_layer.bounding_box()
    
    if not keypad_box or keypad_box['width'] == 0 or keypad_box['height'] == 0:
        raise Exception(f"Keypad container has invalid size: {keypad_box}")

    screenshot_bytes = page.screenshot(clip=keypad_box)
    keypad_img = Image.open(io.BytesIO(screenshot_bytes))

    number_map = {}
    
    # 좌표 기준 정렬 (y 우선, x 다음)
    button_positions.sort(key=lambda b: (b['y'], b['x']))

    for idx, btn_info in enumerate(button_positions):
        # 상대 좌표 계산
        lx = btn_info['x'] - keypad_box['x']
        ly = btn_info['y'] - keypad_box['y']
        
        crop_box = (lx, ly, lx + btn_info['w'], ly + btn_info['h'])
        button_img = keypad_img.crop(crop_box)
        
        text = None
        
        # 전처리 및 OCR 시도 (여러 전략)
        gray = button_img.convert('L')
        
        # 1. 기본 대비 향상
        enhancer = ImageEnhance.Contrast(gray)
        enhanced = enhancer.enhance(2.0)
        binary = enhanced.point(lambda p: p > 128 and 255)
        
        configs = [
            r'--oem 3 --psm 10 -c tessedit_char_whitelist=0123456789', # 단일 문자
            r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789',  # 단일 라인
            r'--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789'   # 단일 단어
        ]
        
        for config in configs:
            result = pytesseract.image_to_string(binary, config=config).strip()
            if result.isdigit() and len(result) == 1:
                text = result
                break
        
        if not text:
            # 샤프닝 시도
            sharp = enhanced.filter(ImageFilter.SHARPEN)
            binary_sharp = sharp.point(lambda p: p > 128 and 255)
            for config in configs:
                result = pytesseract.image_to_string(binary_sharp, config=config).strip()
                if result.isdigit() and len(result) == 1:
                    text = result
                    break

        if text and text not in number_map:
            number_map[text] = btn_info['element']

    return number_map

def charge_balance(page: Page, amount: int) -> bool:
    """
    [간편충전] 기능을 사용하여 예치금을 충전합니다.
    (Alias for charge_deposit - 통합 스크립트에서 사용)
    
    Args:
        page: 로그인된 Playwright Page 객체
        amount: 충전할 금액 (5000, 10000, 20000 중 하나)
        
    Returns:
        bool: 충전 요청 성공 여부
    """
    return charge_deposit(page, amount)


def charge_deposit(page: Page, amount: int) -> bool:
    """
    [간편충전] 기능을 사용하여 예치금을 충전합니다.
    
    Args:
        page: 로그인된 Playwright Page 객체
        amount: 충전할 금액 (5000, 10000, 20000 중 하나)
        
    Returns:
        bool: 충전 요청 성공 여부
    """
    if not CHARGE_PIN:
        print("❌ Error: CHARGE_PIN not found in environment variables.")
        return False

    print(f"💳 충전 페이지로 이동 중... (₩{amount:,})")
    page.goto("https://www.dhlottery.co.kr/mypage/mndpChrg", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20000)
    time.sleep(2)
    
    # 간편충전 선택
    print("  간편충전 선택...")
    page.click("text=간편충전")
    time.sleep(1)
    
    # 금액 선택
    amount_map = {5000: "5,000", 10000: "10,000", 20000: "20,000"}
    if amount not in amount_map:
        print(f"❌ Error: Invalid amount {amount}. Choose 5000, 10000, 20000.")
        return False
    
    print(f"  금액 선택: {amount_map[amount]}원")
    page.select_option("select#EcAmt", label=f"{amount_map[amount]}원")
    time.sleep(1)
    
    # 충전하기 버튼 클릭
    print("  충전하기 버튼 클릭...")
    try:
        charge_btn = page.locator("button:has-text('충전하기')")
        if charge_btn.count() > 0:
            charge_btn.first.click()
        else:
            page.locator(".btn-rec01").first.click()
    except Exception as e:
        print(f"❌ 충전 버튼 클릭 실패: {e}")
        return False
    
    # PIN 키패드 대기
    print("  PIN 키패드 대기 중...")
    try:
        page.wait_for_selector(".nppfs-keypad", state="visible", timeout=10000)
    except Exception:
        try:
            page.wait_for_selector(".kpd-layer", state="visible", timeout=5000)
        except Exception as e:
            print(f"❌ 키패드를 찾을 수 없습니다: {e}")
            page.screenshot(path="debug_charge_no_keypad.png")
            return False

    print("  키패드 분석 중...")
    try:
        number_map = parse_keypad(page)
    except Exception as e:
        print(f"❌ 키패드 분석 실패: {e}")
        page.screenshot(path="debug_charge_keypad_fail.png")
        return False
    
    print(f"  인식된 숫자: {len(number_map)}개")
    if len(number_map) < len(set(CHARGE_PIN)):
        print(f"❌ Error: 필요한 숫자를 모두 인식하지 못했습니다 (인식: {len(number_map)}, 필요: {len(set(CHARGE_PIN))}).")
        return False
    
    print(f"  PIN 입력 중... (길이: {len(CHARGE_PIN)})")
    for i, digit in enumerate(CHARGE_PIN):
        if digit in number_map:
            number_map[digit].click()
            time.sleep(0.3)
        else:
            print(f"❌ Error: 숫자 '{digit}'를 키패드에서 찾을 수 없습니다.")
            return False
    
    print("  충전 완료 대기 중...")
    page.wait_for_load_state("networkidle", timeout=30000)
    time.sleep(2)
    
    print("✅ 충전 완료!")
    return True

def run(playwright: Playwright, amount: int):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    try:
        login(page)
        success = charge_deposit(page, amount)
        if success:
            print("✅ Charge completed successfully!")
            notify_charge(amount, True)
        else:
            print("❌ Charge failed.")
            notify_charge(amount, False)
    except Exception as e:
        print(f"An error occurred: {e}")
        notify_charge(amount, False)
    finally:
        context.close()
        browser.close()

if __name__ == "__main__":
    amount = 10000
    if len(sys.argv) > 1:
        try:
            amount = int(sys.argv[1].replace(',', ''))
        except ValueError:
            pass
            
    with sync_playwright() as playwright:
        run(playwright, amount)
