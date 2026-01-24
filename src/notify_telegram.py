#!/usr/bin/env python3
"""
커맨드라인에서 텔레그램 알림을 보내는 헬퍼 스크립트
"""
import sys
from telegram_notifier import notify_start, notify_complete, notify_error

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: notify_telegram.py [start|complete|error]")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "start":
        notify_start()
    elif command == "complete":
        notify_complete()
    elif command == "error":
        error_msg = sys.argv[2] if len(sys.argv) > 2 else "Unknown error"
        notify_error(error_msg)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
