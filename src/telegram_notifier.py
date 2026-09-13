import os
import re
try:
    import requests
except ImportError:
    requests = None
import urllib.request
import urllib.parse

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')


def send_telegram_message(message: str, parse_mode: str = 'HTML') -> bool:
    """
    텔레그램으로 메시지를 전송합니다.
    
    Args:
        message: 전송할 메시지
        parse_mode: 메시지 포맷 ('HTML' 또는 'Markdown')
    
    Returns:
        bool: 전송 성공 여부
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("\n" + "─" * 40)
        print("📱 [Telegram Message Preview]")
        print("─" * 40)
        # HTML 태그 제거하여 터미널에 깔끔히 출력
        clean_text = re.sub(r'<[^>]+>', '', message)
        print(clean_text)
        print("─" * 40 + "\n")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': parse_mode
        }
        if requests:
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        else:
            encoded = urllib.parse.urlencode(data).encode('utf-8')
            req = urllib.request.Request(url, data=encoded)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
    except Exception as e:
        print(f"⚠️ Telegram notification failed: {e}")
        return False


def notify_start():
    """구매 프로세스 시작 알림"""
    message = "🎰 <b>로또 자동 구매 시작</b>\n\n"
    message += "구매 프로세스를 시작합니다..."
    send_telegram_message(message)


def notify_balance(deposit: int, available: int):
    """잔액 확인 알림"""
    message = "💰 <b>예치금 확인</b>\n\n"
    message += f"예치금 잔액: {deposit:,}원\n"
    message += f"구매가능 금액: {available:,}원"
    send_telegram_message(message)


def notify_charge(amount: int, success: bool = True):
    """충전 알림"""
    if success:
        message = f"💳 <b>예치금 충전 완료</b>\n\n"
        message += f"충전 금액: {amount:,}원"
    else:
        message = f"❌ <b>예치금 충전 실패</b>\n\n"
        message += f"충전 시도 금액: {amount:,}원"
    send_telegram_message(message)


def notify_lotto645_purchase(
    auto_games: int,
    manual_games: int,
    success: bool,
    error_msg: str = None,
    numbers: list = None,
    round_num: int = None,
    is_cosmic: bool = True
):
    """로또 6/45 구매 알림"""
    total_games = auto_games + manual_games
    if numbers and total_games == 0:
        total_games = len(numbers)
    total_amount = total_games * 1000
    
    if success:
        round_header = f" ({round_num}회)" if round_num else ""
        if is_cosmic:
            message = f"🎱 <b>로또 6/45 우주의 기운 구매 완료!{round_header}</b>\n\n"
            message += f"🔮 <b>우주의 기운 5대 특화 조합</b>\n"
        else:
            message = f"🎱 <b>로또 6/45 구매 완료{round_header}</b>\n\n"
            if auto_games > 0:
                message += f"자동: {auto_games}게임\n"
            if manual_games > 0:
                message += f"수동: {manual_games}게임\n"
        message += f"💰 <b>총 금액:</b> {total_amount:,}원 ({total_games}게임)\n"
        
        # 구매한 번호 추가
        if numbers and len(numbers) > 0:
            message += "\n📋 <b>구매 번호 조합:</b>\n"
            slot_letters = ['A', 'B', 'C', 'D', 'E']
            for i, item in enumerate(numbers):
                slot_char = slot_letters[i] if i < len(slot_letters) else str(i + 1)
                
                # dict 형태 (cosmic lotto 결과)
                if isinstance(item, dict):
                    tag = item.get('tag') or item.get('name') or f"게임 {slot_char}"
                    nums = item.get('numbers', [])
                    sorted_nums = sorted(nums)
                    nums_str = "  ".join([f"{n:02d}" for n in sorted_nums])
                    message += f"<b>[{slot_char}] {tag}</b>\n"
                    message += f"👉 <code>{nums_str}</code>\n"
                # list 형태
                elif isinstance(item, (list, tuple)):
                    sorted_nums = sorted(item)
                    nums_str = "  ".join([f"{n:02d}" for n in sorted_nums])
                    message += f"<b>[{slot_char}]</b> <code>{nums_str}</code>\n"
                else:
                    message += f"• {item}\n"
            message += "\n🍀 <i>이번 주 1등 당첨을 우주가 응원합니다! ✨</i>"
    else:
        message = "❌ <b>로또 6/45 구매 실패</b>\n\n"
        if error_msg:
            message += f"오류: {error_msg}"
    
    send_telegram_message(message)


def notify_lotto720_purchase(
    success: bool,
    error_msg: str = None,
    numbers: str = None,
    amount: int = 5000,
    purchase_count: int = 1
):
    """연금복권 720+ 구매 알림"""
    if success:
        message = "🎟️ <b>연금복권 720+ 구매 완료</b>\n\n"
        message += f"금액: {amount:,}원"
        if purchase_count > 1:
            message += f"\n구매 횟수: {purchase_count}회"
        if numbers:
            message += f"\n\n<b>구매 번호:</b>\n{numbers}"
    else:
        message = "❌ <b>연금복권 720+ 구매 실패</b>\n\n"
        if error_msg:
            message += f"오류: {error_msg}"
    
    send_telegram_message(message)


def notify_lotto_result(
    round_num: int,
    winning_numbers: list,
    bonus: int,
    prizes: dict = None,
    game_details: list = None,
    draw_date: str = None,
    total_prize: int = 0
):
    """로또 당첨 결과 상세 리포트 알림
    
    Args:
        round_num: 회차
        winning_numbers: 당첨 번호 리스트 [1,2,3,4,5,6]
        bonus: 보너스 번호
        prizes: 당첨 내역 카운트 {'1등': 1, '5등': 2, ...}
        game_details: 게임별 매칭 상세 내역 리스트
        draw_date: 추첨일자 (YYYY-MM-DD)
        total_prize: 총 당첨 금액
    """
    date_str = f" ({draw_date})" if draw_date else ""
    message = f"🎰 <b>로또 {round_num}회 추첨 결과 리포트{date_str}</b>\n\n"
    
    # 당첨 번호
    sorted_win = sorted(winning_numbers)
    win_str = "  ".join([f"{n:02d}" for n in sorted_win])
    message += "🎯 <b>당첨 번호:</b>\n"
    message += f"👉 <code>{win_str}</code> + <b>{bonus:02d}</b> (보너스)\n\n"
    
    # 게임별 상세 매칭 결과가 있는 경우
    if game_details and len(game_details) > 0:
        message += "━━━━━━━━━━━━━━━━━━━━\n"
        message += "🎫 <b>내 번호 매칭 결과:</b>\n"
        for item in game_details:
            slot = item.get('slot', '')
            tag = item.get('tag') or item.get('name') or f"게임 {slot}"
            nums = item.get('numbers', [])
            matched = item.get('matched_numbers', [])
            has_bonus = item.get('has_bonus', False)
            rank = item.get('rank')
            prize = item.get('prize_amount', 0)
            
            # 번호 표시
            nums_str = " ".join([f"{n:02d}" for n in sorted(nums)])
            message += f"\n<b>[{slot}] {tag}</b>\n"
            message += f"<code>{nums_str}</code>\n"
            
            # 매칭 결과
            matched_count = len(matched)
            matched_str = ", ".join([f"{n:02d}" for n in sorted(matched)]) if matched else "없음"
            bonus_str = " + 보너스 일치!" if has_bonus else ""
            
            if rank:
                prize_str = f" ({prize:,}원)" if prize > 0 else ""
                message += f"↳ 일치({matched_count}개: {matched_str}{bonus_str}) 👉 🎉 <b>{rank} 당첨!{prize_str}</b>\n"
            else:
                message += f"↳ 일치({matched_count}개: {matched_str}{bonus_str}) ➡️ <i>낙첨</i>\n"
        message += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # 종합 당첨 내역
    has_win = (prizes and any(prizes.values())) or total_prize > 0
    if has_win:
        message += "🏆 <b>당첨 요약:</b>\n"
        if prizes:
            for rank, count in prizes.items():
                if count > 0:
                    message += f"• <b>{rank}:</b> {count}회 당첨\n"
        if total_prize > 0:
            message += f"💰 <b>총 당첨금:</b> <b>{total_prize:,}원</b>\n"
        message += "\n🎉 <b>진심으로 축하드립니다! 우주의 기운이 통했습니다! 🥳</b>"
    else:
        message += "아쉽게도 이번 회차는 당첨되지 않았습니다.\n"
        message += "확률의 법칙에 따라 다음 회차 당첨 확률이 더욱 상승합니다! 💪"
    
    send_telegram_message(message)


def notify_complete():
    """전체 프로세스 완료 알림"""
    message = "✅ <b>로또 구매 완료</b>\n\n"
    message += "모든 구매 작업이 성공적으로 완료되었습니다!"
    send_telegram_message(message)


def notify_error(error_msg: str):
    """오류 알림"""
    message = "🚨 <b>오류 발생</b>\n\n"
    message += f"<code>{error_msg}</code>"
    send_telegram_message(message)
