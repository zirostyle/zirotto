#!/usr/bin/env python3
"""
커맨드라인에서 텔레그램 알림을 보내는 헬퍼 스크립트.

[중요]
이 스크립트는 telegram_notifier 를 직접 사용합니다.
과거에는 telegram_notifier 가 import 시점에 환경변수를 읽었기 때문에
.env 가 로드되지 않은 이 경로에서 알림이 전송되지 않았습니다.
현재는 config.load_environment() 가 호출 시점에 .env 를 로드하고,
미설정 시 경고 로그를 남기므로 조용한 실패가 발생하지 않습니다.

사용법:
    notify_telegram.py start
    notify_telegram.py complete
    notify_telegram.py error "에러 메시지"
"""
import sys

from applog import get_logger
from config import load_environment
from telegram_notifier import (
    is_configured,
    notify_complete,
    notify_error,
    notify_start,
)

log = get_logger(__name__)

USAGE = "Usage: notify_telegram.py [start|complete|error] [message]"


def main(argv: list) -> int:
    load_environment()

    if len(argv) < 2:
        log.error(USAGE)
        return 1

    command = argv[1].lower()

    if not is_configured():
        log.warning(
            "텔레그램이 설정되지 않아 '%s' 알림을 보내지 않습니다. "
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 를 확인하세요.",
            command,
        )
        # 알림 실패가 전체 워크플로우를 중단시키지 않도록 0 을 반환합니다.
        return 0

    if command == "start":
        sent = notify_start()
    elif command == "complete":
        sent = notify_complete()
    elif command == "error":
        error_msg = argv[2] if len(argv) > 2 else "Unknown error"
        sent = notify_error(error_msg)
    else:
        log.error("알 수 없는 명령: %s\n%s", command, USAGE)
        return 1

    if sent:
        log.info("'%s' 알림 전송 완료", command)
    else:
        log.warning("'%s' 알림 전송 실패", command)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
