#!/usr/bin/env python3
import json
import re
import sys
import time
from os import environ
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import Playwright, sync_playwright
from login import login
from telegram_notifier import notify_lotto645_purchase

# .env loading is handled by login module import


def parse_arguments():
    """
    커맨드라인 인자를 파싱하여 게임 설정 반환
    
    사용법:
    - Auto: ./lotto645.py 1000  (1게임)
    - Auto: ./lotto645.py 3000  (3게임)
    - Manual: ./lotto645.py 1 2 3 4 5 6  (수동 번호)
    
    Returns:
        tuple: (auto_games, manual_numbers)
    """
    if len(sys.argv) == 1:
        # No arguments - use .env configuration
        auto_games = int(environ.get('AUTO_GAMES', '0'))
        manual_numbers = json.loads(environ.get('MANUAL_NUMBERS', '[]'))
        return auto_games, manual_numbers
    
    # Parse command-line arguments
    args = sys.argv[1:]
    
    # Case 1: Single argument (auto games by amount)
    if len(args) == 1:
        amount_str = args[0].replace(',', '')  # Remove commas
        try:
            amount = int(amount_str)
            
            # Check if it's a valid auto game amount (1000-5000 in 1000 increments)
            if amount in [1000, 2000, 3000, 4000, 5000]:
                auto_games = amount // 1000
                print(f"ℹ️  Auto mode: {auto_games} game(s) (₩{amount:,})")
                return auto_games, []
            else:
                print(f"❌ Error: Invalid amount '{args[0]}'")
                print(f"Valid amounts: 1000, 2000, 3000, 4000, 5000")
                sys.exit(1)
        except ValueError:
            print(f"❌ Error: Invalid amount format '{args[0]}'")
            sys.exit(1)
    
    # Case 2: Six arguments (manual number selection)
    elif len(args) == 6:
        try:
            numbers = [int(arg) for arg in args]
            
            # Validate: all numbers must be 1-45
            if not all(1 <= n <= 45 for n in numbers):
                print(f"❌ Error: All numbers must be between 1 and 45")
                print(f"Provided: {numbers}")
                sys.exit(1)
            
            # Validate: no duplicates
            if len(numbers) != len(set(numbers)):
                print(f"❌ Error: Numbers must not contain duplicates")
                print(f"Provided: {numbers}")
                sys.exit(1)
            
            # Sort numbers for display
            sorted_numbers = sorted(numbers)
            print(f"ℹ️  Manual mode: {sorted_numbers}")
            return 0, [numbers]
            
        except ValueError:
            print(f"❌ Error: All arguments must be numbers")
            print(f"Provided: {args}")
            sys.exit(1)
    
    else:
        print(f"❌ Error: Invalid number of arguments")
        print(f"\nUsage:")
        print(f"  Auto games:   ./lotto645.py [AMOUNT]")
        print(f"                where AMOUNT is 1000, 2000, 3000, 4000, or 5000")
        print(f"  Manual game:  ./lotto645.py [N1] [N2] [N3] [N4] [N5] [N6]")
        print(f"                where each N is a number from 1 to 45 (no duplicates)")
        print(f"\nExamples:")
        print(f"  ./lotto645.py 3000          # Buy 3 auto games")
        print(f"  ./lotto645.py 1 2 3 4 5 6   # Buy 1 manual game with numbers 1,2,3,4,5,6")
        sys.exit(1)


def purchase_lotto645(page, auto_games: int = 0, manual_numbers: list = None, use_mobile: bool = True) -> dict:
    """
    로또 6/45를 자동 및 수동으로 구매합니다 (이미 로그인된 페이지 사용).
    
    Args:
        page: 이미 로그인된 Playwright Page 객체
        auto_games: 자동 구매 게임 수
        manual_numbers: 수동 구매 번호 리스트 (예: [[1,2,3,4,5,6], ...])
        use_mobile: True일 경우 모바일 뷰포트 사용 (동행복권 모바일 구매 지원)
        
    Returns:
        dict: {'games': int, 'total_cost': int, 'numbers': list}
    """
    from datetime import datetime, timezone, timedelta
    
    if manual_numbers is None:
        manual_numbers = []
    
    # Load from env if not provided
    if auto_games == 0 and len(manual_numbers) == 0:
        auto_games = int(environ.get('AUTO_GAMES', '5'))
        manual_numbers = json.loads(environ.get('MANUAL_NUMBERS', '[]'))
    
    # Check if purchase is available (Korean time)
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    day_of_week = now.weekday()  # 0=월요일, 6=일요일
    hour = now.hour
    
    print(f"⏰ 현재 시간: {now.strftime('%Y-%m-%d %H:%M:%S')} (KST, {['월','화','수','목','금','토','일'][day_of_week]}요일)")
    
    # 일요일 전체 구매 불가
    if day_of_week == 6:
        raise Exception("❌ 구매 불가: 일요일에는 로또를 구매할 수 없습니다.")
    
    # 토요일 20:00-24:00 구매 불가 (추첨 시간)
    if day_of_week == 5 and hour >= 20:
        raise Exception("❌ 구매 불가: 추첨 시간(토요일 20:00-24:00)에는 구매할 수 없습니다.")
    
    print(f"✅ 구매 가능 시간입니다!")
    
    # 성공 여부 변수 - 반드시 초기화 (모든 코드 경로에서 notify 시 참조)
    success = False
    final_numbers = []
    
    try:
        # 모바일 뷰포트 설정 (동행복권 모바일 구매 지원)
        if use_mobile:
            try:
                page.set_viewport_size({"width": 390, "height": 844})
                page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"})
                print("  📱 모바일 뷰포트 적용 (390x844)")
            except Exception as e:
                print(f"  ⚠️ 모바일 뷰포트 설정 스킵: {e}")
        
        # Navigate to game page with retry
        print("  로또645 페이지 이동 중...")
        
        max_retries = 3
        for retry in range(max_retries):
            try:
                if retry > 0:
                    print(f"  재시도 {retry}/{max_retries-1}...")
                    time.sleep(10)
                
                page.goto(url="https://ol.dhlottery.co.kr/olotto/game/game645.do", timeout=90000, wait_until="domcontentloaded")
                print('  페이지 로드 완료')
                
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except:
                    print('  ⚠️ networkidle 타임아웃, 계속 진행...')
                
                time.sleep(2)
                print('✅ 로또 6/45 페이지 로드 완료')
                break
                
            except Exception as e:
                if retry < max_retries - 1:
                    print(f"  ⚠️ 페이지 로드 실패, 재시도... ({str(e)[:50]})")
                else:
                    raise
        
        # Check if page shows "구매불가" message
        try:
            # Common selectors for purchase unavailable messages
            unavailable_messages = [
                "text=/구매.*불가/",
                "text=/판매.*중지/",
                "text=/구매.*시간/",
                ".alert",
                ".notice"
            ]
            
            for selector in unavailable_messages:
                try:
                    msg_el = page.locator(selector).first
                    if msg_el.is_visible(timeout=2000):
                        msg_text = msg_el.inner_text()
                        raise Exception(f"❌ 구매 불가: {msg_text}")
                except:
                    pass
        except Exception as e:
            if "구매 불가" in str(e):
                raise
        
        # Remove all intercepting pause layer popups using JavaScript
        # These elements block clicks even when they're not supposed to be visible
        page.evaluate("""
            () => {
                // Hide all known pause layer elements
                const selectors = [
                    '#pause_layer_pop_02',
                    '#ele_pause_layer_pop02',
                    '.pause_layer_pop',
                    '.pause_bg'
                ];
                
                selectors.forEach(selector => {
                    const elements = document.querySelectorAll(selector);
                    elements.forEach(el => {
                        el.style.display = 'none';
                        el.style.visibility = 'hidden';
                        el.style.pointerEvents = 'none';
                    });
                });
            }
        """)
        
        # Dismiss popup if present - use force to bypass any remaining intercepting elements
        try:
            popup_alert = page.locator("#popupLayerAlert")
            if popup_alert.is_visible(timeout=2000):
                # Click the confirmation button with force
                popup_alert.get_by_role("button", name="확인").click(force=True, timeout=5000)
                print('✅ Dismissed popup alert')
        except Exception as e:
            # If popup handling fails, log but continue
            print(f'⚠️  Popup handling: {str(e)}')

        # Manual numbers
        if manual_numbers and len(manual_numbers) > 0:
            print(f"\n수동 번호 선택 중... ({len(manual_numbers)}게임)")
            for i, game in enumerate(manual_numbers, 1):
                print(f"  게임 {i}: {game}")
                for number in game:
                    page.click(f'label[for="check645num{number}"]', force=True)
                    time.sleep(0.1)
                page.click("#btnSelectNum")
                time.sleep(1)
                print(f'  ✅ 게임 {i} 선택 완료')

        # Automatic games
        if auto_games > 0:
            print(f"\n자동 번호 선택 중... ({auto_games}게임)")
            
            # Wait for page interactions
            time.sleep(2)
            
            # Take screenshot for debugging
            page.screenshot(path="debug_lotto645_before_auto.png")
            print("📸 자동 선택 전 스크린샷 저장")
            
            # Try multiple selectors for the auto number button (PC + 모바일 대응)
            auto_button_selectors = [
                "#num2",
                "input#num2",
                "input[name='num2']",
                "input[type='radio'][value='2']",
                "label[for='num2']",
                "text=/자동/",
                ".select_auto",
                "[data-value='2']",
                ".mode_auto",
                "label:has-text('자동')",
                "input[value='2']"
            ]
            
            clicked = False
            for selector in auto_button_selectors:
                try:
                    print(f"  🔍 시도 중: {selector}")
                    element = page.locator(selector)
                    if element.count() > 0:
                        element.first.click(timeout=5000, force=True)
                        print(f"  ✅ 자동 버튼 클릭 성공: {selector}")
                        clicked = True
                        break
                except Exception as e:
                    print(f"  ❌ 실패: {selector}")
            
            if not clicked:
                # Save HTML for debugging
                with open("debug_lotto645.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                print("📄 HTML 저장: debug_lotto645.html")
                raise Exception("❌ 자동 번호 선택 버튼을 찾을 수 없습니다")
            
            time.sleep(1)
            print(f"  게임 수 선택: {auto_games}게임")
            for amt_selector in ["#amoundApply", "#amountApply", "select[name='amoundApply']", "#gameCount", "select.game_count"]:
                try:
                    page.select_option(amt_selector, str(auto_games))
                    print(f"  ✅ 게임 수 선택: {amt_selector}")
                    break
                except:
                    pass
            time.sleep(1)
            
            print("  선택 완료 버튼 클릭...")
            page.click("#btnSelectNum")
            time.sleep(2)
            print(f'✅ 자동 {auto_games}게임 선택 완료')

        # Check if any games were added
        total_games = len(manual_numbers) + auto_games
        if total_games == 0:
            print('⚠️  No games to purchase!')
            return {'games': 0, 'total_cost': 0, 'numbers': []}

        # Verify payment amount (PC/모바일 공통)
        time.sleep(1)
        payment_amount = 0
        for pay_sel in ["#payAmt", "[id*='payAmt']", ".pay_amt", "[class*='pay']"]:
            try:
                payment_text = page.locator(pay_sel).first.inner_text(timeout=3000).strip()
                payment_amount = int(re.sub(r'[^0-9]', '', payment_text))
                break
            except:
                pass
        expected_amount = total_games * 1000
        
        if payment_amount != expected_amount:
            print(f'❌ Error: Payment mismatch (Expected {expected_amount}, Displayed {payment_amount})')
            return {'games': 0, 'total_cost': 0, 'numbers': []}
        
        # 구매 전 번호 추출 (화면에서 보이는 번호 저장)
        purchased_numbers = []
        try:
            # 선택된 번호들 추출 - 여러 셀렉터 시도 (사이트 UI 변경 대응)
            number_selectors = [
                ".select_num", ".num_box", "[class*='selected']",
                ".pub_nums", ".nums", "[class*='nums']",
                ".ball", ".num"
            ]
            for selector in number_selectors:
                try:
                    number_display = page.locator(selector)
                    for i in range(min(total_games, 10)):
                        try:
                            game_el = number_display.nth(i)
                            if game_el.count() > 0:
                                text = game_el.inner_text()
                                numbers = re.findall(r'\d+', text)
                                # 1-45 범위의 중복 없는 6개 번호만 추출
                                valid = []
                                seen = set()
                                for n in numbers:
                                    num = int(n)
                                    if 1 <= num <= 45 and num not in seen:
                                        valid.append(num)
                                        seen.add(num)
                                    if len(valid) == 6:
                                        break
                                if len(valid) == 6:
                                    purchased_numbers.append(valid)
                        except:
                            pass
                    if purchased_numbers:
                        break
                except:
                    pass
            
            # 수동 번호는 이미 알고 있음 (구매 순서: 수동 먼저, 자동 나중)
            if manual_numbers:
                auto_extracted = [p for p in purchased_numbers if p not in manual_numbers]
                purchased_numbers = manual_numbers + auto_extracted[:auto_games]
        except Exception as e:
            print(f"⚠️ 번호 추출 실패: {e}")
            if manual_numbers:
                purchased_numbers = manual_numbers
        
        # Purchase
        print("🛒 구매 버튼 클릭...")
        page.click("#btnBuy")
        
        # Confirm purchase popup
        print("✅ 구매 확인 팝업에서 확인 클릭...")
        page.click("#popupLayerConfirm input[value='확인']")
        
        # Wait for purchase to complete
        print("⏳ 구매 처리 대기 중...")
        time.sleep(5)
        
        # 1. Check for purchase limit popup
        # 주의: 한도 초과 팝업이 나와도 이미 구매는 완료된 경우가 많음
        limit_exceeded = False
        limit_popup = page.locator("#recommend720Plus")
        
        if limit_popup.is_visible():
            print(f"⚠️ 주간 구매 한도 초과 팝업 감지")
            limit_exceeded = True
            try:
                content = limit_popup.locator(".cont1").inner_text()
                print(f"   {content.strip()}")
            except:
                pass
            
            # 팝업만으로는 구매 실패를 확정할 수 없음
            # 마이페이지에서 실제 구매 여부 확인 필요
            print("   → 마이페이지에서 실제 구매 여부 확인 예정")
        
        # 2. Check for success message or redirect to purchase complete page
        purchase_completed_by_message = False
        try:
            # 성공 메시지 또는 완료 페이지로 이동 확인
            success_indicators = [
                "text=/구매.*완료/",
                "text=/구매.*성공/",
                ".complete",
                "#successMessage"
            ]
            
            for selector in success_indicators:
                try:
                    if page.locator(selector).is_visible(timeout=3000):
                        purchase_completed_by_message = True
                        print(f"✅ 구매 완료 메시지 감지: {selector}")
                        break
                except:
                    pass
            
            # URL 변경 확인
            current_url = page.url
            if "confirm" in current_url.lower() or "complete" in current_url.lower():
                purchase_completed_by_message = True
                print(f"✅ 구매 완료 페이지로 이동: {current_url}")
        except Exception as e:
            print(f"⚠️ 구매 완료 메시지 확인 중 에러: {e}")
        
        if not purchase_completed_by_message:
            # 스크린샷 저장
            page.screenshot(path="debug_lotto645_after_purchase.png")
            print("📸 구매 후 스크린샷 저장: debug_lotto645_after_purchase.png")
            
            # HTML 저장
            with open("debug_lotto645_after_purchase.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            print("📄 구매 후 HTML 저장: debug_lotto645_after_purchase.html")
            
            # 경고: 구매 완료를 확인할 수 없음
            print("⚠️ 경고: 구매 완료를 확인할 수 없습니다.")
            print("   마이페이지에서 구매 내역을 직접 확인하세요.")
            print("   https://www.dhlottery.co.kr/mypage/LottoWinHistList.do")
        
        # 3. 최종 검증: 마이페이지에서 실제 구매 내역 및 번호 확인
        print("\n🔍 구매 내역 최종 검증 및 번호 추출 중...")
        time.sleep(5)
        
        verified_numbers = []
        actual_purchased = False  # 실제 구매 여부
        
        try:
            page.goto("https://www.dhlottery.co.kr/mypage/LottoWinHistList.do", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=20000)
            time.sleep(2)
            
            # 최근 구매 내역 확인
            recent_purchase = page.locator("table tbody tr").first
            if recent_purchase.count() > 0:
                purchase_text = recent_purchase.inner_text(timeout=5000)
                print(f"✅ 구매 내역 확인됨")
                print(f"   {purchase_text[:150]}")
                
                # 오늘 날짜가 포함된 구매 내역인지 확인
                from datetime import datetime, timezone, timedelta
                kst = timezone(timedelta(hours=9))
                today = datetime.now(kst)
                today_str = today.strftime('%Y-%m-%d')
                
                if today_str in purchase_text or today.strftime('%Y.%m.%d') in purchase_text:
                    print(f"  ✅ 오늘 구매한 내역 확인!")
                    actual_purchased = True
                    success = True
                else:
                    print(f"  ⚠️ 오늘 구매 내역이 아닐 수 있습니다.")
                    # 그래도 최근 내역이 있으면 일단 성공으로 간주
                    actual_purchased = True
                    success = True
                
                # 구매 내역에서 번호 추출 시도
                try:
                    # 1) 테이블 행에서 직접 번호 추출 (번호 컬럼: nth(2) 또는 nth(3))
                    for col_idx in [2, 3]:
                        try:
                            numbers_text = recent_purchase.locator("td").nth(col_idx).inner_text()
                            for line in numbers_text.replace('\r', '\n').split('\n'):
                                numbers = re.findall(r'\d+', line)
                                if len(numbers) >= 6:
                                    nums = [int(n) for n in numbers[:6]]
                                    if all(1 <= n <= 45 for n in nums) and len(set(nums)) == 6:
                                        verified_numbers.append(nums)
                            if verified_numbers:
                                break
                        except:
                            pass
                    
                    # 2) 번호가 없으면 상세 보기 클릭 후 추출
                    if not verified_numbers:
                        detail_btn = recent_purchase.locator("a, button, .btn").first
                        if detail_btn.count() > 0:
                            detail_btn.click(timeout=3000)
                            time.sleep(2)
                        
                        number_elements = page.locator(".win_num, .num, [class*='number']")
                        for i in range(min(number_elements.count(), 10)):
                            try:
                                text = number_elements.nth(i).inner_text()
                                nums = re.findall(r'\b\d{1,2}\b', text)
                                if len(nums) >= 6:
                                    nlist = [int(n) for n in nums[:6]]
                                    if all(1 <= n <= 45 for n in nlist) and len(set(nlist)) == 6:
                                        verified_numbers.append(nlist)
                                        print(f"  번호 {len(verified_numbers)}: {' '.join([f'{n:02d}' for n in nlist])}")
                            except:
                                pass
                except Exception as e:
                    print(f"  ⚠️ 상세 번호 추출 실패: {e}")
                
                # 추출된 번호가 없으면 화면에서 추출한 번호 사용
                if not verified_numbers and purchased_numbers:
                    verified_numbers = purchased_numbers
                    print("  📝 화면에서 추출한 번호 사용")
                
            else:
                print("⚠️ 구매 내역이 없습니다.")
                actual_purchased = False
                success = False
        except Exception as e:
            print(f"⚠️ 구매 내역 확인 실패: {e}")
            # 검증 실패는 구매 실패를 의미하지 않음
        
        # 최종 판단: 구매 완료 메시지 또는 마이페이지 내역
        if actual_purchased or purchase_completed_by_message:
            success = True
            print(f'\n✅ Lotto 6/45: 구매 완료! ({total_games}게임, ₩{total_games * 1000:,})')
            
            # 판단 근거 출력
            if actual_purchased:
                print("  📋 근거: 마이페이지에 구매 내역 확인됨")
            if purchase_completed_by_message:
                print("  ✅ 근거: 구매 완료 메시지 감지됨")
            if limit_exceeded:
                print("  ℹ️  참고: 한도 초과 팝업이 나왔지만 이미 구매는 완료됨")
        else:
            if limit_exceeded:
                # 한도 초과로 구매 안 됨
                print(f'\n⚠️ Lotto 6/45: 주간 구매 한도 초과 (구매 안 됨)')
                from telegram_notifier import send_telegram_message
                message = "⚠️ <b>로또 구매 한도 초과</b>\n\n"
                message += "이번 주 구매 한도를 모두 사용했습니다.\n"
                message += "다음 회차(토요일 21:00 이후)부터 구매 가능합니다."
                send_telegram_message(message)
                return {'games': 0, 'total_cost': 0, 'numbers': [], 'limit_exceeded': True}
            else:
                print(f'\n❌ Lotto 6/45: 구매 실패')
                success = False
        
        # 최종 구매 번호 (검증된 번호 우선, 없으면 추출한 번호)
        final_numbers = verified_numbers if verified_numbers else purchased_numbers
        
        # 구매한 번호 출력
        if final_numbers:
            print("\n📋 구매한 번호:")
            for i, nums in enumerate(final_numbers, 1):
                print(f"  {i}. {' '.join([f'{n:02d}' for n in sorted(nums)])}")
        else:
            print("\n⚠️ 구매 번호를 확인할 수 없습니다. 마이페이지에서 확인하세요.")
        
        # 텔레그램 알림 (실패해도 구매 결과는 반환)
        try:
            notify_lotto645_purchase(auto_games, len(manual_numbers), success, numbers=final_numbers)
        except Exception as notify_err:
            print(f"⚠️ 텔레그램 알림 전송 실패: {notify_err}")
        
        return {'games': total_games if success else 0, 'total_cost': total_games * 1000 if success else 0, 'numbers': final_numbers if final_numbers else purchased_numbers}

    except Exception as e:
        print(f"❌ Error during purchase: {e}")
        try:
            notify_lotto645_purchase(auto_games, len(manual_numbers) if manual_numbers else 0, False, error_msg=str(e), numbers=final_numbers)
        except Exception as notify_err:
            print(f"⚠️ 텔레그램 알림 전송 실패: {notify_err}")
        raise


def run(playwright: Playwright, auto_games: int, manual_numbers: list) -> None:
    """
    로또 6/45를 자동 및 수동으로 구매합니다 (독립 실행용).
    
    Args:
        playwright: Playwright 객체
        auto_games: 자동 구매 게임 수
        manual_numbers: 수동 구매 번호 리스트 (예: [[1,2,3,4,5,6], ...])
    """
    # Create browser, context, and page (모바일 뷰포트)
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={'width': 390, 'height': 844},
        user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
    )
    page = context.new_page()
    
    # Perform login
    try:
        login(page)
        # Purchase
        purchase_lotto645(page, auto_games, manual_numbers)
    finally:
        # Cleanup
        context.close()
        browser.close()


if __name__ == "__main__":
    # Parse command-line arguments or use .env configuration
    auto_games, manual_numbers = parse_arguments()
    
    with sync_playwright() as playwright:
        run(playwright, auto_games, manual_numbers)
