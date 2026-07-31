#!/usr/bin/env python3
"""
공통 로깅 설정.

기존 코드는 전부 print() 를 사용했기 때문에 레벨/타임스탬프가 없어
GitHub Actions 로그에서 원인 추적이 어려웠습니다.
이 모듈은 표준 logging 을 최소 설정으로 감싸 동일한 사용 편의성을 제공합니다.

사용법:
    from applog import get_logger
    log = get_logger(__name__)
    log.info("메시지")
"""
import logging
import os
import sys

_CONFIGURED = False

_LEVEL_MAP = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def _resolve_level() -> int:
    raw = str(os.environ.get("LOG_LEVEL", "")).strip().upper()
    if raw in _LEVEL_MAP:
        return _LEVEL_MAP[raw]
    # DEBUG=1 이면 자동으로 DEBUG 레벨
    if str(os.environ.get("DEBUG", "")).strip().lower() in ("1", "true", "yes", "on"):
        return logging.DEBUG
    return logging.INFO


def configure(force: bool = False) -> None:
    """루트 로거를 1회 설정합니다."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    level = _resolve_level()
    root = logging.getLogger()
    root.setLevel(level)

    # 기존 핸들러 제거 (중복 출력 방지)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)

    # 서드파티 소음 억제
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str = "zirotto") -> logging.Logger:
    """설정이 보장된 로거를 반환합니다."""
    configure()
    # __main__ 으로 실행될 때 이름이 불명확해지는 것을 방지
    if name in ("__main__", "", None):
        name = "zirotto"
    return logging.getLogger(name)


def section(log: logging.Logger, title: str) -> None:
    """가독성을 위한 구분선 출력."""
    log.info("=" * 56)
    log.info(title)
    log.info("=" * 56)
