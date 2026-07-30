#!/usr/bin/env python3
"""
동행복권 로그인.

[수정 이력]
- .env 로딩 책임을 config.load_environment() 로 이전
- 자격증명을 모듈 전역이 아니라 호출 시점에 읽도록 변경 (주입 가능)
- 디버그 스크린샷/HTML 을 무조건 생성하던 부분을 DEBUG 플래그로 게이팅하고
  debug/ 디렉토리로 격리 (계정 ID·페이지 전체 HTML 유출 위험 완화)
- bare except 제거
"""
import time

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from applog import get_logger
from config import debug_path, env_bool, env_str, load_environment

log = get_logger(__name__)

LOGIN_URL = "https://www.dhlottery.co.kr/login"
MAIN_URL = "https://www.dhlottery.co.kr/main"

LOGIN_INDICATORS = (
    "text=/로그아웃/",
    "text=/마이페이지/",
    "[href*='logout']",
    "[href*='mypage']",
    "#gnb",
)

ERROR_SELECTORS = (
    ".error_msg",
    ".alert",
    "[class*='error']",
    "[class*='alert']",
)

# 하위 호환: 기존 코드가 login.load_environment 를 참조할 수 있음
load_environment()


def get_credentials(user_id: str | None = None, passwd: str | None = None) -> tuple:
    """
    자격증명을 반환합니다. 인자로 주입하면 환경변수보다 우선합니다.
    (모듈 전역 캐시가 아니라 호출 시점에 읽습니다)
    """
    load_environment()
    resolved_id = user_id if user_id else env_str("USER_ID")
    resolved_pw = passwd if passwd else env_str("PASSWD")
    return resolved_id, resolved_pw


def _capture_debug(page: Page, name: str, include_html: bool = False) -> None:
    """DEBUG 가 켜져 있을 때만 디버그 산출물을 debug/ 에 저장합니다."""
    try:
        page.screenshot(path=debug_path(f"{name}.png"))
        if include_html:
            with open(debug_path(f"{name}.html"), "w", encoding="utf-8") as fp:
                fp.write(page.content())
        log.debug("디버그 산출물 저장: debug/%s", name)
    except Exception as exc:
        log.debug("디버그 저장 실패(%s): %s", name, exc)


def _find_error_message(page: Page) -> str | None:
    for selector in ERROR_SELECTORS:
        try:
            element = page.locator(selector)
            if element.count() == 0:
                continue
            text = element.first.inner_text(timeout=2000).strip()
            if text:
                return text
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    return None


def _verify_logged_in(page: Page) -> bool:
    for indicator in LOGIN_INDICATORS:
        try:
            if page.locator(indicator).count() > 0:
                log.debug("로그인 확인 지표 발견: %s", indicator)
                return True
        except Exception:
            continue
    return False


def login(
    page: Page,
    max_retries: int = 3,
    user_id: str | None = None,
    passwd: str | None = None,
    debug: bool | None = None,
) -> None:
    """
    동행복권 사이트에 로그인합니다.

    Args:
        page: Playwright Page 객체 (호출자가 생성하여 주입)
        max_retries: 최대 재시도 횟수
        user_id, passwd: 주입할 자격증명 (없으면 환경변수 사용)
        debug: 디버그 산출물 생성 여부 (없으면 DEBUG 환경변수)

    Raises:
        ValueError: 자격증명이 없을 경우
        RuntimeError: 로그인 실패 시
    """
    resolved_id, resolved_pw = get_credentials(user_id, passwd)
    if not resolved_id or not resolved_pw:
        raise ValueError("USER_ID 또는 PASSWD 가 설정되지 않았습니다.")

    want_debug = env_bool("DEBUG", False) if debug is None else debug

    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                log.info("로그인 재시도 %s/%s", attempt, max_retries - 1)
                time.sleep(5)

            log.info("로그인 시작")

            try:
                page.goto(LOGIN_URL, timeout=60000, wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                log.warning("로그인 페이지 로드 타임아웃, load 상태로 재시도")
                time.sleep(3)
                page.goto(LOGIN_URL, timeout=60000, wait_until="load")

            page.wait_for_selector("#inpUserId", state="visible", timeout=20000)

            page.locator("#inpUserId").fill(resolved_id)
            page.locator("#inpUserPswdEncn").fill(resolved_pw)

            if want_debug:
                _capture_debug(page, "login_01_before")

            page.click("#btnLogin")

            log.info("로그인 처리 대기 중...")
            try:
                page.wait_for_load_state("networkidle", timeout=45000)
            except PlaywrightTimeoutError:
                log.warning("networkidle 타임아웃, domcontentloaded 로 계속 진행")
                page.wait_for_load_state("domcontentloaded", timeout=10000)

            if want_debug:
                _capture_debug(page, "login_02_after")

            current_url = page.url
            log.info("로그인 후 URL: %s", current_url)

            if "/login" in current_url:
                error_msg = _find_error_message(page)
                if want_debug:
                    _capture_debug(page, "login_03_failed", include_html=True)

                if error_msg:
                    raise RuntimeError(f"로그인 실패: {error_msg}")
                raise RuntimeError(
                    "로그인 실패: 로그인 페이지에서 벗어나지 못했습니다. "
                    "아이디/비밀번호를 확인하세요."
                )

            time.sleep(2)

            if not _verify_logged_in(page):
                if want_debug:
                    _capture_debug(page, "login_04_unverified", include_html=True)
                raise RuntimeError("로그인 검증 실패: 로그인 상태를 확인할 수 없습니다.")

            log.info("로그인 성공")
            return

        except Exception as exc:
            last_error = exc
            log.warning("로그인 시도 실패: %s", exc)
            if attempt >= max_retries - 1:
                log.error("모든 로그인 시도 실패")

    raise RuntimeError(f"로그인 실패 (최대 재시도 초과): {last_error}")
