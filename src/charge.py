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
    time.sleep(3)
    
    # 스크린샷 1: 초기 페이지
    page.screenshot(path="debug_charge_01_initial.png")
    print("  📸 충전 페이지 초기 화면 저장")
    
    # 간편충전 선택
    print("  간편충전 탭 클릭...")
    try:
        # 여러 셀렉터 시도
        selectors = ["text=간편충전", "#tab2", ".tab:has-text('간편충전')"]
        clicked = False
        for selector in selectors:
            try:
                page.click(selector, timeout=3000)
                clicked = True
                print(f"  ✅ 간편충전 선택: {selector}")
                break
            except:
                pass
        
        if not clicked:
            print("  ⚠️ 간편충전 탭을 찾을 수 없음, 현재 페이지 그대로 진행...")
    except Exception as e:
        print(f"  ⚠️ 간편충전 선택 실패: {e}")
    
    time.sleep(2)
    page.screenshot(path="debug_charge_02_after_tab.png")
    print("  📸 탭 선택 후 화면 저장")
    
    # 금액 선택
    amount_map = {5000: "5,000", 10000: "10,000", 20000: "20,000"}
    if amount not in amount_map:
        print(f"❌ Error: Invalid amount {amount}. Choose 5000, 10000, 20000.")
        return False
    
    print(f"  금액 선택: {amount_map[amount]}원")
    try:
        page.select_option("select#EcAmt", label=f"{amount_map[amount]}원")
    except Exception as e:
        print(f"  ⚠️ 금액 선택 실패: {e}")
        # 셀렉터 확인을 위해 HTML 저장
        with open("debug_charge_html.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("  📄 HTML 저장: debug_charge_html.html")
    
    time.sleep(2)
    page.screenshot(path="debug_charge_03_after_amount.png")
    print("  📸 금액 선택 후 화면 저장")
    
    # 충전하기 버튼 클릭
    print("  충전하기 버튼 찾기...")
    try:
        # 여러 셀렉터 시도
        charge_selectors = [
            "button:has-text('충전하기')",
            ".btn-rec01",
            "button.btn",
            "[onclick*='charge']",
            "[onclick*='Charge']"
        ]
        
        clicked = False
        for selector in charge_selectors:
            try:
                btn = page.locator(selector)
                if btn.count() > 0:
                    print(f"  시도: {selector} ({btn.count()}개 발견)")
                    btn.first.click(timeout=3000)
                    clicked = True
                    print(f"  ✅ 충전 버튼 클릭: {selector}")
                    break
            except Exception as e:
                print(f"  ❌ {selector}: {str(e)[:40]}")
        
        if not clicked:
            print("  ❌ 충전 버튼을 찾을 수 없습니다.")
            return False
    except Exception as e:
        print(f"❌ 충전 버튼 클릭 실패: {e}")
        return False
    
    time.sleep(3)
    page.screenshot(path="debug_charge_04_after_button.png")
    print("  📸 버튼 클릭 후 화면 저장")
    
    # PIN 키패드 대기
    print("  PIN 키패드 대기 중...")
    
    # 여러 셀렉터 시도
    keypad_selectors = [".nppfs-keypad", ".kpd-layer", "#keypad", ".keypad"]
    keypad_found = False
    
    for selector in keypad_selectors:
        try:
            print(f"  키패드 찾기: {selector}")
            page.wait_for_selector(selector, state="visible", timeout=5000)
            keypad_found = True
            print(f"  ✅ 키패드 발견: {selector}")
            break
        except:
            print(f"  ❌ 없음: {selector}")
    
    if not keypad_found:
        print("❌ 키패드를 찾을 수 없습니다.")
        page.screenshot(path="debug_charge_05_no_keypad.png")
        print("  📸 키패드 없음 스크린샷 저장")
        
        # HTML 저장
        with open("debug_charge_05_no_keypad.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("  📄 HTML 저장")
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
