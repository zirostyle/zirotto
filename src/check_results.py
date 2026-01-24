#!/usr/bin/env python3
"""
로또 당첨 결과 확인 스크립트
마이페이지에서 최근 구매 내역을 조회하고 당첨 여부를 확인합니다.
"""
import re
import requests
from playwright.sync_api import Playwright, sync_playwright
from login import login
from telegram_notifier import notify_lotto_result


def get_latest_lotto_winning_numbers() -> dict:
    """
    동행복권 API에서 최신 회차 당첨 번호를 가져옵니다.
    
    Returns:
        dict: {
            'round': int,
            'winning_numbers': list,
            'bonus': int,
            'draw_date': str
        }
    """
    # 동행복권 API (비공식)
    url = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo="
    
    # 최신 회차 찾기 (현재 회차 추정)
    import datetime
    # 로또 1회는 2002-12-07, 매주 토요일 추첨
    first_draw_date = datetime.date(2002, 12, 7)
    today = datetime.date.today()
    weeks = (today - first_draw_date).days // 7
    estimated_round = weeks + 1
    
    # 최근 3개 회차 시도
    for round_num in range(estimated_round, estimated_round - 3, -1):
        try:
            response = requests.get(f"{url}{round_num}", timeout=10)
            data = response.json()
            
            if data.get('returnValue') == 'success':
                winning_numbers = [
                    data['drwtNo1'], data['drwtNo2'], data['drwtNo3'],
                    data['drwtNo4'], data['drwtNo5'], data['drwtNo6']
                ]
                
                return {
                    'round': round_num,
                    'winning_numbers': winning_numbers,
                    'bonus': data['bnusNo'],
                    'draw_date': data['drwNoDate']
                }
        except:
            continue
    
    raise Exception("최신 당첨 번호를 가져올 수 없습니다.")


def get_my_lotto_purchases(page) -> list:
    """
    마이페이지에서 최근 로또 구매 내역을 조회합니다.
    
    Args:
        page: 로그인된 Playwright Page 객체
        
    Returns:
        list: [{'round': int, 'numbers': [[1,2,3,4,5,6], ...], 'date': str}, ...]
    """
    # 마이페이지 > 구매/당첨 내역
    page.goto("https://www.dhlottery.co.kr/mypage/LottoWinHistList.do", timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)
    
    purchases = []
    
    try:
        # 최근 구매 내역 테이블에서 정보 추출
        # 실제 HTML 구조에 맞게 셀렉터 조정 필요
        rows = page.locator("table tbody tr").all()
        
        for row in rows[:10]:  # 최근 10개만
            try:
                # 회차 추출
                round_text = row.locator("td").nth(0).inner_text()
                round_match = re.search(r'(\d+)', round_text)
                if not round_match:
                    continue
                round_num = int(round_match.group(1))
                
                # 번호 추출 (예: "01 02 03 04 05 06")
                numbers_text = row.locator("td").nth(2).inner_text()
                number_sets = []
                
                # 여러 게임이 있을 수 있음
                for line in numbers_text.split('\n'):
                    numbers = re.findall(r'\d+', line)
                    if len(numbers) >= 6:
                        number_sets.append([int(n) for n in numbers[:6]])
                
                if number_sets:
                    purchases.append({
                        'round': round_num,
                        'numbers': number_sets,
                        'date': row.locator("td").nth(1).inner_text().strip()
                    })
            except:
                continue
    except Exception as e:
        print(f"⚠️ 구매 내역 조회 실패: {e}")
    
    return purchases


def check_winning(my_numbers: list, winning_numbers: list, bonus: int) -> tuple:
    """
    당첨 여부를 확인합니다.
    
    Args:
        my_numbers: 내 번호 [1,2,3,4,5,6]
        winning_numbers: 당첨 번호 [1,2,3,4,5,6]
        bonus: 보너스 번호
        
    Returns:
        tuple: (등수, 일치 개수) 예: ("1등", 6) 또는 (None, 3)
    """
    my_set = set(my_numbers)
    winning_set = set(winning_numbers)
    
    match_count = len(my_set & winning_set)
    has_bonus = bonus in my_set
    
    if match_count == 6:
        return ("1등", 6)
    elif match_count == 5 and has_bonus:
        return ("2등", 5)
    elif match_count == 5:
        return ("3등", 5)
    elif match_count == 4:
        return ("4등", 4)
    elif match_count == 3:
        return ("5등", 3)
    else:
        return (None, match_count)


def run(playwright: Playwright):
    """당첨 결과 확인 메인 함수"""
    print("🎰 로또 당첨 결과 확인")
    print("="*50)
    
    # 1. 최신 당첨 번호 가져오기
    try:
        winning_info = get_latest_lotto_winning_numbers()
        print(f"\n🎯 {winning_info['round']}회 당첨 번호:")
        print(f"   {' '.join([f'{n:02d}' for n in winning_info['winning_numbers']])}")
        print(f"   + 보너스: {winning_info['bonus']:02d}")
        print(f"   추첨일: {winning_info['draw_date']}")
    except Exception as e:
        print(f"❌ 당첨 번호 조회 실패: {e}")
        return
    
    # 2. 내 구매 내역 확인
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    page = context.new_page()
    
    try:
        login(page)
        purchases = get_my_lotto_purchases(page)
        
        if not purchases:
            print("\n⚠️ 최근 구매 내역이 없습니다.")
            notify_lotto_result(
                winning_info['round'],
                winning_info['winning_numbers'],
                winning_info['bonus'],
                {}
            )
            return
        
        print(f"\n📋 구매 내역: {len(purchases)}개 회차")
        
        # 3. 해당 회차 구매 내역 찾기
        my_purchase = None
        for p in purchases:
            if p['round'] == winning_info['round']:
                my_purchase = p
                break
        
        if not my_purchase:
            print(f"\n⚠️ {winning_info['round']}회 구매 내역이 없습니다.")
            notify_lotto_result(
                winning_info['round'],
                winning_info['winning_numbers'],
                winning_info['bonus'],
                {}
            )
            return
        
        # 4. 당첨 확인
        print(f"\n🎫 {winning_info['round']}회 구매 번호:")
        prizes = {}
        
        for i, numbers in enumerate(my_purchase['numbers'], 1):
            print(f"   {i}. {' '.join([f'{n:02d}' for n in sorted(numbers)])}")
            
            rank, match_count = check_winning(
                numbers,
                winning_info['winning_numbers'],
                winning_info['bonus']
            )
            
            if rank:
                print(f"      🎉 {rank} 당첨! ({match_count}개 일치)")
                prizes[rank] = prizes.get(rank, 0) + 1
            else:
                print(f"      ({match_count}개 일치)")
        
        # 5. 텔레그램 알림
        notify_lotto_result(
            winning_info['round'],
            winning_info['winning_numbers'],
            winning_info['bonus'],
            prizes if prizes else {}
        )
        
        if prizes:
            print(f"\n🎉 축하합니다! 당첨!")
        else:
            print(f"\n아쉽지만 당첨되지 않았습니다.")
        
    except Exception as e:
        print(f"❌ 에러: {e}")
        import traceback
        traceback.print_exc()
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
