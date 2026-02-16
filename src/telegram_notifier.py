#!/usr/bin/env python3
"""
텔레그램 알림 모듈
"""
import os
import requests
from typing import Optional

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
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': parse_mode
        }
        response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
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


def notify_lotto645_purchase(auto_games: int, manual_games: int, success: bool, error_msg: str = None, numbers: list = None):
    """로또 6/45 구매 알림"""
    total_games = auto_games + manual_games
    total_amount = total_games * 1000
    
    if success:
        message = "🎱 <b>로또 6/45 구매 완료</b>\n\n"
        if auto_games > 0:
            message += f"자동: {auto_games}게임\n"
        if manual_games > 0:
            message += f"수동: {manual_games}게임\n"
        message += f"\n총 금액: {total_amount:,}원"
        
        # 구매한 번호 추가
        if numbers and len(numbers) > 0:
            message += "\n\n<b>구매 번호:</b>\n"
            for i, nums in enumerate(numbers, 1):
                sorted_nums = sorted(nums)
                message += f"{i}. " + " ".join([f"{n:02d}" for n in sorted_nums]) + "\n"
    else:
        message = "❌ <b>로또 6/45 구매 실패</b>\n\n"
        if error_msg:
            message += f"오류: {error_msg}"
    
    send_telegram_message(message)


def notify_lotto720_purchase(success: bool, error_msg: str = None, numbers: str = None, total_amount: int = None):
    """연금복권 720+ 구매 알림"""
    if success:
        message = "🎟️ <b>연금복권 720+ 구매 완료</b>\n\n"
        message += f"금액: {total_amount or 5000:,}원"
        if numbers:
            message += f"\n\n<b>구매 번호:</b>\n{numbers}"
    else:
        message = "❌ <b>연금복권 720+ 구매 실패</b>\n\n"
        if error_msg:
            message += f"오류: {error_msg}"
    
    send_telegram_message(message)


def notify_lotto_result(round_num: int, winning_numbers: list, bonus: int, prizes: dict):
    """로또 당첨 결과 알림
    
    Args:
        round_num: 회차
        winning_numbers: 당첨 번호 리스트 [1,2,3,4,5,6]
        bonus: 보너스 번호
        prizes: 당첨 내역 {'1등': 금액, '2등': 금액, ...}
    """
    message = f"🎰 <b>로또 {round_num}회 추첨 결과</b>\n\n"
    
    # 당첨 번호
    message += "<b>당첨 번호:</b>\n"
    message += " ".join([f"{n:02d}" for n in sorted(winning_numbers)])
    message += f" + <b>{bonus:02d}</b> (보너스)\n\n"
    
    # 당첨 내역
    if prizes and any(prizes.values()):
        message += "<b>🎉 당첨 내역:</b>\n"
        for rank, amount in prizes.items():
            if amount > 0:
                message += f"{rank}: {amount:,}원\n"
    else:
        message += "아쉽게도 당첨되지 않았습니다.\n"
        message += "다음 기회에 도전하세요! 💪"
    
    send_telegram_message(message)


def notify_winning_results(lotto645: dict = None, lotto720: dict = None, my_prizes: dict = None):
    """
    로또 645 + 연금복권 720 당첨번호 및 구매 복권 당첨여부 통합 알림
    
    Args:
        lotto645: {'round', 'winning_numbers', 'bonus', 'draw_date'}
        lotto720: {'round', 'winning_numbers', 'draw_date'} (optional)
        my_prizes: {'lotto645': {'1등': 1, ...}, 'lotto720': '당첨내역'} (optional)
    """
    message = "🎰 <b>매주 당첨 결과</b>\n\n"
    
    if lotto645:
        message += f"🎱 <b>로또 6/45 {lotto645['round']}회</b>\n"
        message += f"당첨번호: {' '.join([f'{n:02d}' for n in sorted(lotto645['winning_numbers'])])}"
        message += f" + {lotto645['bonus']:02d}(보너스)\n"
        message += f"추첨일: {lotto645.get('draw_date', '')}\n\n"
        
        if my_prizes and my_prizes.get('lotto645'):
            prizes = my_prizes['lotto645']
            if any(prizes.values()):
                message += "🏆 <b>내 당첨:</b>\n"
                for rank, count in prizes.items():
                    if count > 0:
                        message += f"  {rank}: {count}건\n"
            else:
                message += "내 복권: 당첨 없음\n"
        elif my_prizes and 'lotto645' in my_prizes:
            message += "내 복권: 당첨 없음\n"
        message += "\n"
    
    if lotto720:
        message += f"🎟️ <b>연금복권 720+ {lotto720.get('round', '')}회</b>\n"
        if lotto720.get('winning_numbers'):
            message += f"당첨번호: {' '.join([f'{n:02d}' for n in sorted(lotto720['winning_numbers'])])}\n"
        message += f"추첨일: {lotto720.get('draw_date', '')}\n\n"
        if my_prizes and my_prizes.get('lotto720'):
            message += f"내 당첨: {my_prizes['lotto720']}\n"
    
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
