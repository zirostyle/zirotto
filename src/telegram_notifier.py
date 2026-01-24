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


def notify_charge(amount: int, success: bool):
    """충전 알림"""
    if success:
        message = f"💳 <b>예치금 충전 완료</b>\n\n"
        message += f"충전 금액: {amount:,}원"
    else:
        message = f"❌ <b>예치금 충전 실패</b>\n\n"
        message += f"충전 시도 금액: {amount:,}원"
    send_telegram_message(message)


def notify_lotto645_purchase(auto_games: int, manual_games: int, success: bool, error_msg: str = None):
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
    else:
        message = "❌ <b>로또 6/45 구매 실패</b>\n\n"
        if error_msg:
            message += f"오류: {error_msg}"
    
    send_telegram_message(message)


def notify_lotto720_purchase(success: bool, error_msg: str = None):
    """연금복권 720+ 구매 알림"""
    if success:
        message = "🎟️ <b>연금복권 720+ 구매 완료</b>\n\n"
        message += "금액: 5,000원"
    else:
        message = "❌ <b>연금복권 720+ 구매 실패</b>\n\n"
        if error_msg:
            message += f"오류: {error_msg}"
    
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
