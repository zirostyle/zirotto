#!/usr/bin/env python3
import json
import re
import sys
import time
from os import environ
try:
    from playwright.sync_api import Playwright, sync_playwright
except ImportError:
    Playwright = None
    sync_playwright = None
try:
    from login import login
except ImportError:
    login = None
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


def _normalize_number_set(nums: list) -> list:
    filtered = [int(n) for n in nums if 1 <= int(n) <= 45]
    if len(filtered) < 6:
        return []
    candidate = filtered[:6]
    if len(set(candidate)) != 6:
        return []
    return candidate


def _extract_number_sets_from_text(text: str) -> list:
    """
    문자열에서 로또 번호 6개 세트를 추출합니다.
    """
    results = []
    for line in (text or "").splitlines():
        nums = [int(n) for n in re.findall(r"\b\d{1,2}\b", line)]
        normalized = _normalize_number_set(nums)
        if normalized:
            results.append(normalized)
    return results


def _unique_number_sets(number_sets: list) -> list:
    """
    번호 세트 중복 제거 (정렬 기준으로 중복 판단)
    """
    unique = []
    seen = set()
    for nums in number_sets:
        if not nums or len(nums) != 6:
            continue
        key = tuple(sorted(nums))
        if key in seen:
            continue
        seen.add(key)
        unique.append(nums)
    return unique


def _extract_from_selectors(page, selectors: list, limit: int = 20) -> list:
    """
    여러 셀렉터를 순회하며 번호 세트를 추출합니다.
    """
    found = []
    for selector in selectors:
        try:
            loc = page.locator(selector)
            count = min(loc.count(), limit)
            for i in range(count):
                text = loc.nth(i).inner_text(timeout=1500).strip()
                found.extend(_extract_number_sets_from_text(text))
        except Exception:
            continue
    return _unique_number_sets(found)


def _click_by_keyword(page, keywords: list, timeout: int = 4000) -> bool:
    """
    키워드 기반으로 버튼/링크/라벨 클릭을 시도합니다.
    """
    selectors = []
    for kw in keywords:
        selectors.extend(
            [
                f"button:has-text('{kw}')",
                f"a:has-text('{kw}')",
                f"label:has-text('{kw}')",
                f"input[value*='{kw}']",
                f"[title*='{kw}']",
                f"[aria-label*='{kw}']",
            ]
        )

    for selector in selectors:
        try:
            el = page.locator(selector)
            if el.count() > 0:
                el.first.click(timeout=timeout, force=True)
                return True
        except Exception:
            continue
    return False


def _extract_number_sets_dom(page, max_sets: int = 20) -> list:
    """
    브라우저 DOM을 직접 스캔하여 번호 세트를 추출합니다.
    셀렉터/텍스트 추출이 실패할 때의 최종 fallback 용도입니다.
    """
    try:
        raw_sets = page.evaluate(
            """
            (maxSets) => {
                const selectors = [
                    "#article table tbody tr",
                    "#numView tbody tr",
                    ".tbl_data_col tbody tr",
                    ".tbl_data_col tr",
                    ".select_num",
                    ".num_box",
                    ".list_my_number li",
                    ".list_my_number tr",
                    "[class*='num']",
                    "[class*='ball']"
                ];

                const seen = new Set();
                const output = [];

                const normalize = (arr) => {
                    const filtered = arr
                        .map(v => Number(v))
                        .filter(v => Number.isInteger(v) && v >= 1 && v <= 45);
                    if (filtered.length < 6) return null;
                    const firstSix = filtered.slice(0, 6);
                    if (new Set(firstSix).size !== 6) return null;
                    const key = [...firstSix].sort((a, b) => a - b).join(",");
                    if (seen.has(key)) return null;
                    seen.add(key);
                    return firstSix;
                };

                const collectFromElement = (el) => {
                    const childTexts = Array.from(
                        el.querySelectorAll("span,em,strong,li,td,div,p")
                    )
                        .map(n => (n.textContent || "").trim())
                        .filter(Boolean);

                    const directNums = [];
                    for (const t of childTexts) {
                        if (/^\\d{1,2}$/.test(t)) directNums.push(Number(t));
                    }
                    const n1 = normalize(directNums);
                    if (n1) return n1;

                    const txt = (el.textContent || "").replace(/\\s+/g, " ");
                    const matches = txt.match(/\\b([1-9]|[1-3]\\d|4[0-5])\\b/g) || [];
                    const n2 = normalize(matches.map(v => Number(v)));
                    if (n2) return n2;
                    return null;
                };

                for (const selector of selectors) {
                    const nodes = Array.from(document.querySelectorAll(selector));
                    for (const node of nodes) {
                        const picked = collectFromElement(node);
                        if (picked) {
                            output.push(picked);
                            if (output.length >= maxSets) return output;
                        }
                    }
                }
                return output;
            }
            """,
            max_sets,
        )
        if isinstance(raw_sets, list):
            parsed = []
            for item in raw_sets:
                if isinstance(item, list):
                    normalized = _normalize_number_set(item)
                    if normalized:
                        parsed.append(normalized)
            return _unique_number_sets(parsed)
    except Exception:
        pass
    return []


def save_purchased_lotto(round_num: int, games: list, total_cost: int):
    """
    구매한 로또 정보를 data/purchased_lotto.json 파일에 영구 저장합니다.
    """
    import os
    from datetime import datetime, timezone, timedelta
    
    kst = timezone(timedelta(hours=9))
    now_str = datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S')
    
    # zirotto/data 디렉토리
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    file_path = os.path.join(data_dir, "purchased_lotto.json")
    
    data = {"history": []}
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"history": []}
            
    # 직렬화 가능한 게임 데이터 변환
    serialized_games = []
    slot_names = ['A', 'B', 'C', 'D', 'E']
    for idx, item in enumerate(games):
        slot_char = slot_names[idx] if idx < len(slot_names) else str(idx + 1)
        if isinstance(item, dict):
            serialized_games.append({
                "slot": item.get("slot", slot_char),
                "name": item.get("name", f"게임 {slot_char}"),
                "tag": item.get("tag", f"게임 {slot_char}"),
                "numbers": sorted(item.get("numbers", []))
            })
        elif isinstance(item, (list, tuple)):
            serialized_games.append({
                "slot": slot_char,
                "name": f"게임 {slot_char}",
                "tag": f"게임 {slot_char}",
                "numbers": sorted(list(item))
            })

    entry = {
        "round": round_num,
        "purchase_date": now_str,
        "total_cost": total_cost,
        "games": serialized_games
    }
    
    # 중복 회차 업데이트
    existing = [h for h in data.get("history", []) if h.get("round") != round_num]
    existing.append(entry)
    data["history"] = existing
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 구매 정보가 저장되었습니다: {file_path} ({round_num}회, {len(serialized_games)}게임)")


def get_current_round(page=None) -> int:
    """현재 회차 번호를 반환합니다."""
    # 1. 페이지에서 추출 시도
    if page:
        try:
            cur_el = page.locator("#curDrwNo, .cur_round, #drwNo").first
            if cur_el.count() > 0:
                txt = cur_el.inner_text(timeout=2000)
                m = re.search(r'(\d+)', txt)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
            
    # 2. 날짜 기반 회차 계산 (로또 1회: 2002-12-07 20:45)
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    first_draw = datetime(2002, 12, 7, 20, 45, tzinfo=kst)
    diff_days = (now - first_draw).total_seconds() / 86400
    estimated_round = int(diff_days // 7) + 1
    return estimated_round


def purchase_lotto645(page, auto_games: int = 0, manual_numbers: list = None) -> dict:
    """
    로또 6/45를 자동 및 수동으로 구매합니다 (이미 로그인된 페이지 사용).
    
    Args:
        page: 이미 로그인된 Playwright Page 객체
        auto_games: 자동 구매 게임 수
        manual_numbers: 수동 구매 번호 리스트 (예: [[1,2,3,4,5,6], ...])
        
    Returns:
        dict: {'games': int, 'total_cost': int}
    """
    from datetime import datetime, timezone, timedelta
    
    # 우주의 기운 번호 생성 모드 확인 (기본값: 활성화)
    use_cosmic = environ.get('USE_COSMIC_NUMBERS', '1').strip().lower() not in {'0', 'false', 'no', 'off'}
    
    selected_cosmic_games = []
    if use_cosmic and (not manual_numbers or len(manual_numbers) == 0):
        from cosmic_lotto import generate_cosmic_5_games
        print("\n🔮 우주의 기운 최고 당첨률 5개 번호 조합 생성 중...")
        selected_cosmic_games = generate_cosmic_5_games()
        manual_numbers = [g['numbers'] for g in selected_cosmic_games]
        auto_games = 0  # 우주의 기운 5게임으로 전량 구매
        print("  ✨ 우주의 기운 5대 특화 전략 조합 생성 완료:")
        for g in selected_cosmic_games:
            nums_str = " ".join([f"{n:02d}" for n in g['numbers']])
            print(f"  [{g['slot']}] {g['tag']}: {nums_str}")
    elif manual_numbers is None:
        manual_numbers = []
    
    # Load from env if not provided and not cosmic
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
    
    try:

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

        # 대상 회차 확인
        current_round = get_current_round(page)
        print(f"🎯 로또 6/45 구매 대상 회차: {current_round}회")

        # Manual numbers
        if manual_numbers and len(manual_numbers) > 0:
            print(f"\n수동 번호 선택 중... ({len(manual_numbers)}게임)")
            
            # 혼합선택(#num1) 라디오/버튼 클릭
            try:
                mix_btn = page.locator("#num1, label[for='num1'], input[value='1']").first
                if mix_btn.count() > 0:
                    mix_btn.click(timeout=3000, force=True)
                    time.sleep(1)
            except Exception as e:
                print(f"  ℹ️ 혼합선택 모드 전환: {e}")
                
            slot_letters = ['A', 'B', 'C', 'D', 'E']
            for i, game in enumerate(manual_numbers, 1):
                slot_char = slot_letters[i - 1] if i - 1 < len(slot_letters) else str(i)
                game_title = f"게임 [{slot_char}]"
                if selected_cosmic_games and i - 1 < len(selected_cosmic_games):
                    game_title += f" {selected_cosmic_games[i - 1].get('tag', '')}"
                print(f"  {game_title}: {' '.join([f'{n:02d}' for n in sorted(game)])}")
                
                # 번호 6개 클릭
                for number in game:
                    page.click(f'label[for="check645num{number}"]', force=True)
                    time.sleep(0.05)
                time.sleep(0.5)
                
                # 확인(선택 번호 추가) 버튼 클릭
                page.click("#btnSelectNum", force=True)
                time.sleep(1)
                print(f'  ✅ [{slot_char}] 추가 완료')

        # Automatic games
        if auto_games > 0:
            print(f"\n자동 번호 선택 중... ({auto_games}게임)")
            
            # Wait for page interactions
            time.sleep(2)
            
            # Take screenshot for debugging
            page.screenshot(path="debug_lotto645_before_auto.png")
            print("📸 자동 선택 전 스크린샷 저장")
            
            # Try multiple selectors for the auto number button
            auto_button_selectors = [
                "#num2",
                "input#num2",
                "input[name='num2']",
                "input[type='radio'][value='2']",
                "label[for='num2']",
                "text=/자동/",
                ".select_auto"
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
                print("  ⚠️ 자동 버튼 셀렉터 실패, 키워드 기반 클릭 시도...")
                clicked = _click_by_keyword(page, ["자동", "자동선택", "자동 번호"])
                if clicked:
                    print("  ✅ 자동 버튼 클릭 성공: keyword fallback")

            if not clicked:
                print("  ⚠️ 자동 버튼을 찾지 못했습니다. 기본 선택 상태로 계속 진행합니다.")
            
            time.sleep(1)
            print(f"  게임 수 선택: {auto_games}게임")
            try:
                page.select_option("#amoundApply", str(auto_games))
            except Exception:
                # amount selector fallback
                amount_selectors = ["select#amoundApply", "select[name*='amound']", "select[name*='amount']"]
                selected = False
                for selector in amount_selectors:
                    try:
                        page.locator(selector).first.select_option(str(auto_games))
                        selected = True
                        break
                    except Exception:
                        continue
                if not selected:
                    print("  ⚠️ 게임 수 선택 셀렉터를 찾지 못했습니다.")
            time.sleep(1)
            
            print("  선택 완료 버튼 클릭...")
            try:
                page.click("#btnSelectNum")
            except Exception:
                if not _click_by_keyword(page, ["선택완료", "선택 완료", "완료", "확인"]):
                    raise Exception("❌ 선택 완료 버튼을 찾을 수 없습니다")
            time.sleep(2)
            print(f'✅ 자동 {auto_games}게임 선택 완료')

        # Check if any games were added
        total_games = len(manual_numbers) + auto_games
        if total_games == 0:
            print('⚠️  No games to purchase!')
            return {'games': 0, 'total_cost': 0, 'numbers': []}

        # Verify payment amount
        time.sleep(1)
        payment_amount_el = page.locator("#payAmt")
        payment_text = payment_amount_el.inner_text().strip()
        payment_amount = int(re.sub(r'[^0-9]', '', payment_text))
        expected_amount = total_games * 1000
        
        if payment_amount != expected_amount:
            print(f'❌ Error: Payment mismatch (Expected {expected_amount}, Displayed {payment_amount})')
            return {'games': 0, 'total_cost': 0, 'numbers': []}
        
        # 구매 전 번호 추출 (화면에서 보이는 번호 저장)
        purchased_numbers = []
        try:
            pre_purchase_selectors = [
                "#article table tbody tr",
                "#numView tbody tr",
                ".tbl_data_col tbody tr",
                ".tbl_data_col tr",
                ".select_num",
                ".num_box",
                ".list_my_number li",
                ".list_my_number tr",
                "[class*='selected']",
            ]
            purchased_numbers = _extract_from_selectors(page, pre_purchase_selectors, limit=30)
            if not purchased_numbers:
                purchased_numbers = _extract_number_sets_dom(page, max_sets=max(total_games, 10))
            if purchased_numbers:
                print(f"✅ 구매 전 번호 추출 성공: {len(purchased_numbers)}세트")
        except Exception as e:
            print(f"⚠️ 번호 추출 실패: {e}")

        # 수동 번호는 항상 포함
        if manual_numbers:
            purchased_numbers = _unique_number_sets(manual_numbers + purchased_numbers)
        
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
        
        # 구매 완료 메시지/리다이렉트가 있으면 우선 성공으로 간주하고 검증 단계로 진행
        success = purchase_completed_by_message
        if not success:
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
                verified_numbers.extend(_extract_number_sets_from_text(purchase_text))
                
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
                    # 번호 영역 클릭하여 상세 보기
                    detail_btn = recent_purchase.locator("a, button, .btn").first
                    if detail_btn.count() > 0:
                        detail_btn.click(timeout=3000)
                        time.sleep(2)
                    
                    # 상세 페이지에서 번호 추출
                    detail_selectors = [
                        ".win_num",
                        ".num",
                        "[class*='number']",
                        "table tbody tr",
                        "ul li",
                    ]
                    detail_numbers = _extract_from_selectors(page, detail_selectors, limit=60)
                    if not detail_numbers:
                        detail_numbers = _extract_number_sets_dom(page, max_sets=max(total_games, 10))
                    if detail_numbers:
                        verified_numbers.extend(detail_numbers)
                        for i, nums in enumerate(detail_numbers, 1):
                            print(f"  번호 {i}: {' '.join([f'{n:02d}' for n in nums])}")
                except Exception as e:
                    print(f"  ⚠️ 상세 번호 추출 실패: {e}")
                    # 번호 추출 실패해도 구매는 성공
                
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
        
        # 최종 구매 번호 결정
        if selected_cosmic_games:
            final_numbers = selected_cosmic_games
        else:
            final_numbers = _unique_number_sets(verified_numbers if verified_numbers else purchased_numbers)
        
        # 구매 성공 시 local JSON DB에 저장 (추첨 결과 매칭에 활용)
        if success and final_numbers:
            try:
                save_purchased_lotto(current_round, final_numbers, total_games * 1000)
            except Exception as save_err:
                print(f"⚠️ 구매 내역 파일 저장 실패: {save_err}")
        
        # 구매한 번호 출력
        if final_numbers:
            print("\n📋 구매한 번호 조합:")
            slot_letters = ['A', 'B', 'C', 'D', 'E']
            for i, item in enumerate(final_numbers):
                slot_char = slot_letters[i] if i < len(slot_letters) else str(i + 1)
                if isinstance(item, dict):
                    tag = item.get('tag') or item.get('name') or f"게임 {slot_char}"
                    nums_str = " ".join([f"{n:02d}" for n in sorted(item.get('numbers', []))])
                    print(f"  [{slot_char}] {tag}: {nums_str}")
                else:
                    print(f"  [{slot_char}] {' '.join([f'{n:02d}' for n in sorted(item)])}")
        else:
            print("\n⚠️ 구매 번호를 확인할 수 없습니다. 마이페이지에서 확인하세요.")
        
        # 텔레그램 알림 전송
        notify_lotto645_purchase(
            auto_games=0 if selected_cosmic_games else auto_games,
            manual_games=len(selected_cosmic_games) if selected_cosmic_games else len(manual_numbers),
            success=success,
            numbers=final_numbers,
            round_num=current_round,
            is_cosmic=bool(selected_cosmic_games)
        )
        return {'games': total_games if success else 0, 'total_cost': total_games * 1000 if success else 0, 'numbers': final_numbers}

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error during purchase: {error_msg}")

        # 네트워크 타임아웃/접속 장애는 실패 알림 대신 스킵 처리
        timeout_markers = ["ERR_CONNECTION_TIMED_OUT", "Timeout", "net::ERR_", "Page.goto"]
        if any(marker in error_msg for marker in timeout_markers):
            print("⏭️ 로또 6/45 접속 장애로 이번 회차는 건너뜁니다.")
            return {'games': 0, 'total_cost': 0, 'numbers': [], 'skipped': True, 'reason': 'network_timeout'}

        notify_lotto645_purchase(auto_games, len(manual_numbers) if manual_numbers else 0, False, error_msg)
        raise


def run(playwright: Playwright, auto_games: int, manual_numbers: list) -> None:
    """
    로또 6/45를 자동 및 수동으로 구매합니다 (독립 실행용).
    
    Args:
        playwright: Playwright 객체
        auto_games: 자동 구매 게임 수
        manual_numbers: 수동 구매 번호 리스트 (예: [[1,2,3,4,5,6], ...])
    """
    # Create browser, context, and page
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
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
