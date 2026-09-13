#!/usr/bin/env python3
"""
로또 6/45 및 연금복권 720+ 당첨 결과 자동 확인 및 상세 리포트 스크립트

1. 동행복권 API 및 네이버 포털 검색 크롤링을 통해 최신 당첨 번호를 안정적으로 조회
   - 로또 6/45: 당첨번호 6개 + 보너스 번호
   - 연금복권 720+: 1등 조 및 6자리 번호 + 보너스 6자리 번호
2. data/purchased_lotto.json 및 data/purchased_pension720.json에서 구매 내역 로드
3. 1:1 대조 분석을 통해 등수(1등~7등/낙첨), 일치 번호, 당첨금(일시금 및 월 연금액) 산출
4. 텔레그램으로 상세한 매칭 리포트 알림 발송
"""

import os
import re
import json
import sys
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

from telegram_notifier import notify_lotto_result, notify_lotto720_result


# ==============================================================================
# 로또 6/45 관련 로직
# ==============================================================================

def get_latest_lotto_winning_numbers() -> dict:
    """
    최신 회차 로또 6/45 당첨 번호를 가져옵니다.
    1차: 동행복권 공식 API
    2차(백업): 네이버 포털 검색 크롤링 (해외 IP / GitHub Actions 차단 완벽 대응)
    3차(백업): 다음(Daum) 모바일 검색
    """
    # 1차 시도: 동행복권 API
    if requests:
        try:
            url = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo="
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

        round_match = re.search(r'([0-9]+)회\s*당첨번호', html)
        if not round_match:
            round_match = re.search(r'([0-9]+)회', html)
        round_num = int(round_match.group(1)) if round_match else 0

        win_idx = html.find('winning_number')
        bonus_idx = html.find('bonus_number')
        
        winning_numbers = []
        if win_idx != -1 and bonus_idx != -1:
            win_section = html[win_idx:bonus_idx]
            balls = re.findall(r'<span class="ball[^>]*>([0-9]+)</span>', win_section)
            winning_numbers = [int(b) for b in balls[:6]]

        bonus = 0
        if bonus_idx != -1:
            bonus_section = html[bonus_idx:bonus_idx + 400]
            bonus_match = re.search(r'<span class="ball[^>]*>([0-9]+)</span>', bonus_section)
            if bonus_match:
                bonus = int(bonus_match.group(1))

        first_prize = 0
        prize_match = re.search(r'1등\s*당첨금\s*<strong[^>]*>([0-9,]+)</strong>원', html)
        if prize_match:
            first_prize = int(prize_match.group(1).replace(',', ''))

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
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(base_dir, "data", "purchased_lotto.json")
    
    if not os.path.exists(file_path):
        print(f"ℹ️ 로컬 로또 구매 내역 파일이 없습니다: {file_path}")
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
        return history[-1]
    except Exception as e:
        print(f"⚠️ 로또 구매 내역 파일 읽기 실패: {e}")
        return None


def get_my_lotto_purchases_from_web(page) -> list:
    """
    동행복권 마이페이지에서 최근 로또 6/45 구매 내역을 크롤링합니다.
    """
    purchases = []
    try:
        print("🌐 동행복권 마이페이지 로또 구매내역 조회 중...")
        page.goto("https://www.dhlottery.co.kr/myPage.do?method=lottoBuyListView", timeout=60000)
        page.wait_for_load_state("domcontentloaded", timeout=30000)
        import time
        time.sleep(2)

        try:
            page.select_option("select#lottoId", "LO40")
        except Exception:
            pass

        try:
            page.locator("#frm a:has-text('1주일'), #frm a:has-text('1주')").first.click(timeout=3000)
        except Exception:
            pass

        page.click("#submit_btn", force=True)
        time.sleep(2)

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


def run_lotto645_check(playwright: Playwright = None):
    """
    로또 6/45 당첨 결과 확인 및 구매 번호 대조 리포트 발송
    """
    print("\n" + "=" * 60)
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

    # 2. 내 구매 내역 로드
    purchase_data = get_purchased_lotto_from_file(target_round)
    
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

    if not purchase_data:
        print(f"\n⚠️ {target_round}회에 구매한 번호 내역을 찾지 못했습니다.")
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
    print("\n📬 텔레그램 로또645 결과 리포트 전송 중...")
    notify_lotto_result(
        round_num=target_round,
        winning_numbers=win_nums,
        bonus=bonus,
        prizes=prizes,
        game_details=game_details,
        draw_date=draw_date,
        total_prize=total_prize
    )
    print("✅ 텔레그램 로또645 결과 리포트 전송 완료!")
    print("=" * 60)


# ==============================================================================
# 연금복권 720+ 관련 로직
# ==============================================================================

def get_latest_pension720_winning_numbers() -> dict:
    """
    네이버 모바일 검색을 통해 최신 연금복권 720+ 당첨 번호(1등 조+6자리, 보너스 6자리)를 크롤링합니다.
    """
    print("🌐 네이버 검색을 통해 최신 연금복권 720+ 당첨 번호를 조회합니다...")
    try:
        req = urllib.request.Request(
            'https://m.search.naver.com/search.naver?query=%EC%97%B0%EA%B8%88%EB%B3%B5%EA%B6%8C+%EB%8B%B9%EC%B2%A8%EB%B2%88%ED%98%B8',
            headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')

        # 회차 및 추첨일 (예: 332회차 (2026.09.10.))
        m_round = re.search(r'([0-9]+)회차\s*\(([0-9]{4}\.[0-9]{2}\.[0-9]{2})', html)
        if m_round:
            round_num = int(m_round.group(1))
            draw_date = m_round.group(2).replace('.', '-')
        else:
            m_r = re.search(r'([0-9]+)회', html)
            round_num = int(m_r.group(1)) if m_r else 0
            m_d = re.search(r'([0-9]{4}\.[0-9]{2}\.[0-9]{2})', html)
            draw_date = m_d.group(1).replace('.', '-') if m_d else datetime.now().strftime('%Y-%m-%d')

        # 1등 추출 (winning_number)
        win_grp = None
        win_num = ""
        w_match = re.search(r'<div class="winning_number">([\s\S]*?)</div>', html)
        if w_match:
            balls = re.findall(r'<span class="ball[^"]*">([0-9])</span>', w_match.group(1))
            if len(balls) == 7:
                win_grp = int(balls[0])
                win_num = "".join(balls[1:])

        # Fallback 1등 (테이블에서)
        if not win_num:
            t_match = re.search(
                r'<td class="sub_title">1등</td>\s*<td class="sub_title">([1-5])조</td>\s*'
                r'<td class="type_bold">([0-9])</td>\s*<td class="type_bold">([0-9])</td>\s*'
                r'<td class="type_bold">([0-9])</td>\s*<td class="type_bold">([0-9])</td>\s*'
                r'<td class="type_bold">([0-9])</td>\s*<td class="type_bold">([0-9])</td>',
                html
            )
            if t_match:
                win_grp = int(t_match.group(1))
                win_num = "".join(t_match.groups()[1:])

        # 보너스 추출 (테이블에서)
        bonus_num = ""
        b_match = re.search(
            r'<td class="sub_title">보너스</td>\s*<td class="sub_title">[^<]*</td>\s*'
            r'<td class="type_bold">([0-9])</td>\s*<td class="type_bold">([0-9])</td>\s*'
            r'<td class="type_bold">([0-9])</td>\s*<td class="type_bold">([0-9])</td>\s*'
            r'<td class="type_bold">([0-9])</td>\s*<td class="type_bold">([0-9])</td>',
            html
        )
        if b_match:
            bonus_num = "".join(b_match.groups())

        if round_num > 0 and win_grp and len(win_num) == 6 and len(bonus_num) == 6:
            return {
                'round': round_num,
                'draw_date': draw_date,
                'win_group': win_grp,
                'win_number': win_num,
                'bonus_number': bonus_num,
                'source': 'naver_search'
            }
    except Exception as e:
        print(f"⚠️ 네이버 연금복권 검색 파싱 오류: {e}")

    raise Exception("최신 연금복권 720+ 당첨 번호를 가져올 수 없습니다.")


def get_purchased_pension720_from_file(target_round: int = None) -> dict:
    """
    data/purchased_pension720.json 파일에서 구매 내역을 불러옵니다.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(base_dir, "data", "purchased_pension720.json")

    if not os.path.exists(file_path):
        print(f"ℹ️ 로컬 연금복권 구매 내역 파일이 없습니다: {file_path}")
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
        return history[-1]
    except Exception as e:
        print(f"⚠️ 연금복권 구매 내역 파일 읽기 실패: {e}")
        return None


def check_pension720_winning(tickets: list, win_info: dict) -> dict:
    """
    내 연금복권 티켓들과 당첨 번호를 대조하여 등수 및 당첨금을 계산합니다.
    """
    win_grp = win_info['win_group']
    win_num = str(win_info['win_number']).zfill(6)
    bonus_num = str(win_info.get('bonus_number', '')).zfill(6) if win_info.get('bonus_number') else ''

    ticket_results = []
    prizes = {'1등': 0, '2등': 0, '보너스': 0, '3등': 0, '4등': 0, '5등': 0, '6등': 0, '7등': 0}
    total_lump_sum = 0
    monthly_pension_list = []

    for t in tickets:
        grp_str = t.get('group', '') if isinstance(t, dict) else str(t)
        num_str = str(t.get('number', '')).zfill(6) if isinstance(t, dict) else ""
        if not num_str and isinstance(t, str):
            m = re.search(r'([1-5])조\s*(\d{6})', t)
            if m:
                grp_str = f"{m.group(1)}조"
                num_str = m.group(2)

        try:
            grp_int = int(re.sub(r'[^0-9]', '', grp_str))
        except Exception:
            grp_int = 0

        rank = None
        pension = None
        lump_sum = 0
        prize_desc = '낙첨'

        # 1등: 조 + 6자리 일치
        if grp_int == win_grp and num_str == win_num:
            rank = '1등'
            pension = '월 700만원 x 20년'
            prize_desc = '월 700만원 x 20년'
            monthly_pension_list.append('월 700만원 x 20년')
        # 2등: 다른 조 + 6자리 일치
        elif grp_int != win_grp and num_str == win_num:
            rank = '2등'
            pension = '월 100만원 x 10년'
            prize_desc = '월 100만원 x 10년'
            monthly_pension_list.append('월 100만원 x 10년')
        # 보너스: 각조 + 보너스 6자리 일치
        elif bonus_num and num_str == bonus_num:
            rank = '보너스'
            pension = '월 100만원 x 10년'
            prize_desc = '월 100만원 x 10년'
            monthly_pension_list.append('월 100만원 x 10년')
        # 3등: 끝 5자리 일치
        elif num_str[-5:] == win_num[-5:]:
            rank = '3등'
            lump_sum = 1000000
            prize_desc = '100만원'
        # 4등: 끝 4자리 일치
        elif num_str[-4:] == win_num[-4:]:
            rank = '4등'
            lump_sum = 100000
            prize_desc = '10만원'
        # 5등: 끝 3자리 일치
        elif num_str[-3:] == win_num[-3:]:
            rank = '5등'
            lump_sum = 50000
            prize_desc = '5만원'
        # 6등: 끝 2자리 일치
        elif num_str[-2:] == win_num[-2:]:
            rank = '6등'
            lump_sum = 5000
            prize_desc = '5,000원'
        # 7등: 끝 1자리 일치
        elif num_str[-1:] == win_num[-1:]:
            rank = '7등'
            lump_sum = 1000
            prize_desc = '1,000원'

        if rank:
            prizes[rank] += 1
            total_lump_sum += lump_sum

        ticket_results.append({
            'group': grp_str,
            'number': num_str,
            'rank': rank,
            'pension': pension,
            'lump_sum': lump_sum,
            'prize_desc': prize_desc
        })

    pension_parts = []
    if prizes['1등'] > 0:
        pension_parts.append(f"월 {prizes['1등'] * 700:,}만원 x 20년 (1등 {prizes['1등']}매)")
    if prizes['2등'] > 0:
        pension_parts.append(f"월 {prizes['2등'] * 100:,}만원 x 10년 (2등 {prizes['2등']}매)")
    if prizes['보너스'] > 0:
        pension_parts.append(f"월 {prizes['보너스'] * 100:,}만원 x 10년 (보너스 {prizes['보너스']}매)")

    monthly_pension_str = " + ".join(pension_parts) if pension_parts else None

    return {
        'ticket_results': ticket_results,
        'prizes': prizes,
        'monthly_pension': monthly_pension_str,
        'total_lump_sum': total_lump_sum
    }



def run_pension720_check(playwright: Playwright = None):
    """
    연금복권 720+ 최신 당첨 결과 확인 및 구매 내역 대조 리포트 발송
    """
    print("\n" + "=" * 60)
    print("🎟️ 연금복권 720+ 당첨 결과 확인 및 자동 매칭 시작")
    print("=" * 60)

    try:
        win_info = get_latest_pension720_winning_numbers()
        target_round = win_info['round']
        draw_date = win_info['draw_date']
        win_grp = win_info['win_group']
        win_num = win_info['win_number']
        bonus_num = win_info['bonus_number']

        print(f"🎯 최신 회차: {target_round}회 ({win_info['source']})")
        print(f"   1등 번호: {win_grp}조 {' '.join(list(win_num))}")
        print(f"   보너스 번호: 각조 {' '.join(list(bonus_num))}")
        print(f"   추첨 일자: {draw_date}")
    except Exception as e:
        print(f"❌ 연금복권 당첨 번호 조회 실패: {e}")
        return

    # 구매 내역 로드
    purchase_data = get_purchased_pension720_from_file(target_round)
    tickets = purchase_data.get('tickets', []) if purchase_data else []

    if not tickets:
        print(f"\n⚠️ {target_round}회 연금복권 구매 번호 내역을 찾지 못했습니다.")
        notify_lotto720_result(
            round_num=target_round,
            draw_date=draw_date,
            win_group=win_grp,
            win_number=win_num,
            bonus_number=bonus_num,
            ticket_results=[],
            prizes={},
            monthly_pension=None,
            total_lump_sum=0
        )
        return

    print(f"\n📋 {target_round}회 구매 복권 대조 중... ({len(tickets)}매)")
    match_result = check_pension720_winning(tickets, win_info)

    for tr in match_result['ticket_results']:
        if tr['rank']:
            print(f"  [{tr['group']}] {tr['number']}: 🎉 {tr['rank']} 당첨! ({tr['prize_desc']})")
        else:
            print(f"  [{tr['group']}] {tr['number']}: 낙첨")

    print("\n📬 텔레그램 연금복권 결과 리포트 전송 중...")
    notify_lotto720_result(
        round_num=target_round,
        draw_date=draw_date,
        win_group=win_grp,
        win_number=win_num,
        bonus_number=bonus_num,
        ticket_results=match_result['ticket_results'],
        prizes=match_result['prizes'],
        monthly_pension=match_result['monthly_pension'],
        total_lump_sum=match_result['total_lump_sum']
    )
    print("✅ 텔레그램 연금복권 결과 리포트 전송 완료!")
    print("=" * 60)


# ==============================================================================
# 통합 결과 디스패처
# ==============================================================================

def run_result_check(playwright: Playwright = None, check_type: str = "auto"):
    """
    당첨 결과 확인 및 알림 통합 디스패처
    check_type:
      - 'auto': 요일에 따라 목/금은 연금복권, 토/일은 로또645, 그 외(월요일 등)는 둘 다 실행
      - 'all': 로또 645 & 연금복권 720+ 둘 다 실행
      - 'lotto645': 로또 645만 실행
      - 'pension720': 연금복권 720+만 실행
    """
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    weekday = now_kst.weekday()  # 월=0, 목=3, 금=4, 토=5, 일=6

    if check_type == "auto":
        if weekday in (3, 4):
            run_pension720_check(playwright)
        elif weekday in (5, 6):
            run_lotto645_check(playwright)
        else:
            run_pension720_check(playwright)
            run_lotto645_check(playwright)
    elif check_type == "pension720":
        run_pension720_check(playwright)
    elif check_type == "lotto645":
        run_lotto645_check(playwright)
    else:  # 'all'
        run_pension720_check(playwright)
        run_lotto645_check(playwright)


if __name__ == "__main__":
    check_mode = "auto"
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower().strip()
        if "pension" in arg or "720" in arg:
            check_mode = "pension720"
        elif "645" in arg or "lotto" in arg:
            check_mode = "lotto645"
        elif "all" in arg:
            check_mode = "all"
    run_result_check(check_type=check_mode)
