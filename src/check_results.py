#!/usr/bin/env python3
"""
로또 당첨 결과 자동 확인 및 상세 리포트 스크립트

1. 동행복권 API 및 네이버 포털 백업을 통해 최신 당첨 번호(1~6 + 보너스)를 100% 안정적으로 조회
2. data/purchased_lotto.json에 기록된 구매 번호(A~E 게임)를 로드 (필요시 마이페이지 백업 조회)
3. 내 번호와 당첨 번호를 1:1 대조하여 일치 개수 및 등수(1등~5등/낙첨), 당첨금 산출
4. 텔레그램으로 상세한 매칭 리포트 알림 발송
"""

import os
import re
import json
import urllib.request
from datetime import datetime, timezone, timedelta
try:
    import requests
except ImportError:
    requests = None

try:
    from playwright.sync_api import Playwright, sync_playwright
except ImportError:
    Playwright = None
    sync_playwright = None

from telegram_notifier import notify_lotto_result


def get_latest_lotto_winning_numbers() -> dict:
    """
    최신 회차 당첨 번호를 가져옵니다.
    1차: 동행복권 공식 API
    2차(백업): 네이버 포털 검색 크롤링 (해외 IP / GitHub Actions 차단 완벽 대응)
    """
    # 1차 시도: 동행복권 API
    if requests:
        try:
            url = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo="
            # 최신 회차 추정 (1회: 2002-12-07)
            kst = timezone(timedelta(hours=9))
            now = datetime.now(kst)
            first_draw_date = datetime(2002, 12, 7, 20, 45, tzinfo=kst)
            weeks = int((now - first_draw_date).total_seconds() / 86400 // 7)
            estimated_round = weeks + 1

            for round_num in range(estimated_round, estimated_round - 3, -1):
                try:
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
                    response = requests.get(f"{url}{round_num}", headers=headers, timeout=4)
                    data = response.json()
                    if data.get('returnValue') == 'success':
                        winning_numbers = [
                            int(data['drwtNo1']), int(data['drwtNo2']), int(data['drwtNo3']),
                            int(data['drwtNo4']), int(data['drwtNo5']), int(data['drwtNo6'])
                        ]
                        first_prize = int(data.get('firstWinamnt', 0))
                        return {
                            'round': round_num,
                            'winning_numbers': winning_numbers,
                            'bonus': int(data['bnusNo']),
                            'draw_date': data.get('drwNoDate', now.strftime('%Y-%m-%d')),
                            'first_prize': first_prize,
                            'source': 'dhlottery_api'
                        }
                except Exception:
                    continue
        except Exception as e:
            print(f"ℹ️ 동행복권 API 응답 지연: {e}")

    # 2차 백업: 네이버 모바일 검색 파싱
    print("🌐 네이버 검색을 통해 최신 로또 당첨 번호를 조회합니다...")
    try:
        req = urllib.request.Request(
            'https://m.search.naver.com/search.naver?query=%EB%A1%9C%EB%98%90',
            headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'}
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            html = response.read().decode('utf-8')

        # 회차 추출 (예: 1241회)
        round_match = re.search(r'([0-9]+)회\s*당첨번호', html)
        if not round_match:
            round_match = re.search(r'([0-9]+)회', html)
        round_num = int(round_match.group(1)) if round_match else 0

        # 당첨 번호 6개 추출
        win_idx = html.find('winning_number')
        bonus_idx = html.find('bonus_number')
        
        winning_numbers = []
        if win_idx != -1 and bonus_idx != -1:
            win_section = html[win_idx:bonus_idx]
            balls = re.findall(r'<span class="ball[^>]*>([0-9]+)</span>', win_section)
            winning_numbers = [int(b) for b in balls[:6]]

        # 보너스 번호 추출
        bonus = 0
        if bonus_idx != -1:
            bonus_section = html[bonus_idx:bonus_idx + 400]
            bonus_match = re.search(r'<span class="ball[^>]*>([0-9]+)</span>', bonus_section)
            if bonus_match:
                bonus = int(bonus_match.group(1))

        # 1등 당첨금 추출
        first_prize = 0
        prize_match = re.search(r'1등\s*당첨금\s*<strong[^>]*>([0-9,]+)</strong>원', html)
        if prize_match:
            first_prize = int(prize_match.group(1).replace(',', ''))

        # 추첨일 추출
        date_match = re.search(r'([0-9]{4}\.[0-9]{2}\.[0-9]{2})', html)
        draw_date = date_match.group(1).replace('.', '-') if date_match else datetime.now().strftime('%Y-%m-%d')

        if round_num > 0 and len(winning_numbers) == 6 and bonus > 0:
            return {
                'round': round_num,
                'winning_numbers': winning_numbers,
                'bonus': bonus,
                'draw_date': draw_date,
                'first_prize': first_prize,
                'source': 'naver_search'
            }
    except Exception as e:
        print(f"⚠️ 네이버 검색 파싱 오류: {e}")

    # 3차 백업: 다음(Daum) 검색 파싱
    print("🌐 다음(Daum) 검색을 통해 최신 로또 당첨 번호를 조회합니다...")
    try:
        req = urllib.request.Request(
            'https://m.search.daum.net/search?w=tot&q=%EB%A1%9C%EB%98%90',
            headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)'}
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            html = response.read().decode('utf-8')

        round_match = re.search(r'([0-9]+)회', html)
        round_num = int(round_match.group(1)) if round_match else 0
        balls = [int(n) for n in re.findall(r'<span class="lot_num[^>]*>([0-9]+)</span>', html)]
        if len(balls) >= 7:
            return {
                'round': round_num,
                'winning_numbers': balls[:6],
                'bonus': balls[6],
                'draw_date': datetime.now().strftime('%Y-%m-%d'),
                'first_prize': 0,
                'source': 'daum_search'
            }
    except Exception as e:
        print(f"⚠️ 다음 검색 파싱 오류: {e}")

    raise Exception("최신 로또 당첨 번호를 가져올 수 없습니다. 잠시 후 다시 시도해주세요.")


def get_purchased_lotto_from_file(target_round: int = None) -> dict:
    """
    data/purchased_lotto.json 파일에서 구매 내역을 불러옵니다.
    target_round가 지정되면 해당 회차를 반환하고,
    지정되지 않으면 가장 최신 구매 내역을 반환합니다.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(base_dir, "data", "purchased_lotto.json")
    
    if not os.path.exists(file_path):
        print(f"ℹ️ 로컬 구매 내역 파일이 없습니다: {file_path}")
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        history = data.get("history", [])
        if not history:
            return None

        if target_round:
            for item in reversed(history):
                if item.get("round") == target_round:
                    return item
        # 최신 구매 기록 반환
        return history[-1]
    except Exception as e:
        print(f"⚠️ 구매 내역 파일 읽기 실패: {e}")
        return None


def get_my_lotto_purchases_from_web(page) -> list:
    """
    동행복권 마이페이지에서 최근 로또 6/45 구매 내역을 크롤링합니다.
    (로컬 저장 파일이 없을 때의 백업 수단)
    """
    purchases = []
    try:
        print("🌐 동행복권 마이페이지 구매당첨내역 조회 중...")
        page.goto("https://www.dhlottery.co.kr/myPage.do?method=lottoBuyListView", timeout=60000)
        page.wait_for_load_state("domcontentloaded", timeout=30000)
        import time
        time.sleep(2)

        # 복권 유형 로또 6/45 선택
        try:
            page.select_option("select#lottoId", "LO40")
        except Exception:
            pass

        # 조회 기간 1주일 선택
        try:
            page.locator("#frm a:has-text('1주일'), #frm a:has-text('1주')").first.click(timeout=3000)
        except Exception:
            pass

        # 조회 버튼 클릭
        page.click("#submit_btn", force=True)
        time.sleep(2)

        # iframe 내부로 포커스 이동
        iframe_element = page.locator("iframe#lottoBuyList")
        if iframe_element.count() > 0:
            frame = page.frame_locator("iframe#lottoBuyList")
            rows = frame.locator("table.tbl_data_col tbody tr").all()
            for row in rows:
                try:
                    txt = row.inner_text(timeout=2000)
                    m_round = re.search(r'(\d+)', row.locator("td").nth(2).inner_text())
                    if m_round:
                        purchases.append({
                            'round': int(m_round.group(1)),
                            'raw_text': txt
                        })
                except Exception:
                    continue
    except Exception as e:
        print(f"⚠️ 마이페이지 웹 조회 실패: {e}")

    return purchases


def check_single_game(my_numbers: list, winning_numbers: list, bonus: int, first_prize: int = 0) -> dict:
    """
    내 번호 6개와 당첨 번호를 대조하여 등수 및 일치 번호를 산출합니다.
    """
    my_set = set(my_numbers)
    win_set = set(winning_numbers)
    
    matched_set = my_set & win_set
    matched_numbers = sorted(list(matched_set))
    match_count = len(matched_numbers)
    has_bonus = bonus in my_set
    
    rank = None
    prize_amount = 0
    
    if match_count == 6:
        rank = "1등"
        prize_amount = first_prize if first_prize > 0 else 2000000000
    elif match_count == 5 and has_bonus:
        rank = "2등"
        prize_amount = 50000000
    elif match_count == 5:
        rank = "3등"
        prize_amount = 1500000
    elif match_count == 4:
        rank = "4등"
        prize_amount = 50000
    elif match_count == 3:
        rank = "5등"
        prize_amount = 5000

    return {
        'rank': rank,
        'match_count': match_count,
        'matched_numbers': matched_numbers,
        'has_bonus': has_bonus,
        'prize_amount': prize_amount
    }


def run_result_check(playwright: Playwright = None):
    """
    로또 당첨 결과 확인 메인 로직
    """
    print("=" * 60)
    print("🎰 로또 6/45 당첨 결과 확인 및 자동 매칭 시작")
    print("=" * 60)
    
    # 1. 최신 당첨 번호 조회
    try:
        winning_info = get_latest_lotto_winning_numbers()
        target_round = winning_info['round']
        win_nums = winning_info['winning_numbers']
        bonus = winning_info['bonus']
        draw_date = winning_info['draw_date']
        first_prize = winning_info.get('first_prize', 0)
        
        print(f"🎯 최신 회차: {target_round}회 ({winning_info['source']})")
        print(f"   당첨 번호: {' '.join([f'{n:02d}' for n in sorted(win_nums)])} + 보너스: {bonus:02d}")
        print(f"   추첨 일자: {draw_date}")
        if first_prize > 0:
            print(f"   1등 당첨금: {first_prize:,}원")
    except Exception as e:
        print(f"❌ 당첨 번호 조회 실패: {e}")
        return

    # 2. 내 구매 내역 로드 (1차: data/purchased_lotto.json)
    purchase_data = get_purchased_lotto_from_file(target_round)
    
    # 만약 파일에 해당 회차가 없으면 웹에서 확인 시도
    if not purchase_data and playwright:
        print(f"ℹ️ {target_round}회 로컬 기록 없음. 브라우저로 마이페이지 조회를 시도합니다...")
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        try:
            from login import login
            login(page)
            get_my_lotto_purchases_from_web(page)
        except Exception as web_err:
            print(f"⚠️ 마이페이지 웹 조회 예외: {web_err}")
        finally:
            context.close()
            browser.close()

    # 구매 내역이 아예 없는 경우
    if not purchase_data:
        print(f"\n⚠️ {target_round}회에 구매한 번호 내역을 찾지 못했습니다.")
        # 당첨 번호 안내만 전송
        notify_lotto_result(
            round_num=target_round,
            winning_numbers=win_nums,
            bonus=bonus,
            prizes={},
            game_details=[],
            draw_date=draw_date,
            total_prize=0
        )
        return

    # 3. 게임별 매칭 분석
    raw_games = purchase_data.get("games", [])
    print(f"\n📋 {target_round}회 구매 번호 대조 중... ({len(raw_games)}게임)")
    
    prizes = {'1등': 0, '2등': 0, '3등': 0, '4등': 0, '5등': 0}
    total_prize = 0
    game_details = []
    
    slot_names = ['A', 'B', 'C', 'D', 'E']
    for idx, item in enumerate(raw_games):
        slot_char = item.get('slot', slot_names[idx] if idx < len(slot_names) else str(idx + 1))
        tag = item.get('tag') or item.get('name') or f"게임 {slot_char}"
        numbers = item.get('numbers', [])
        
        match_info = check_single_game(numbers, win_nums, bonus, first_prize)
        rank = match_info['rank']
        prize_amt = match_info['prize_amount']
        
        if rank:
            prizes[rank] += 1
            total_prize += prize_amt
            print(f"  [{slot_char}] {tag}: 🎉 {rank} 당첨! (일치: {match_info['match_count']}개, {prize_amt:,}원)")
        else:
            print(f"  [{slot_char}] {tag}: 낙첨 (일치: {match_info['match_count']}개)")

        game_details.append({
            'slot': slot_char,
            'tag': tag,
            'numbers': numbers,
            'matched_numbers': match_info['matched_numbers'],
            'has_bonus': match_info['has_bonus'],
            'rank': rank,
            'match_count': match_info['match_count'],
            'prize_amount': prize_amt
        })

    # 4. 텔레그램 상세 리포트 전송
    print("\n📬 텔레그램 결과 리포트 전송 중...")
    notify_lotto_result(
        round_num=target_round,
        winning_numbers=win_nums,
        bonus=bonus,
        prizes=prizes,
        game_details=game_details,
        draw_date=draw_date,
        total_prize=total_prize
    )
    print("✅ 텔레그램 결과 리포트 전송 완료!")
    print("=" * 60)


if __name__ == "__main__":
    run_result_check()
