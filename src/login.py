#!/usr/bin/env python3
"""
동행복권 로그인.

브라우저 폼 로그인을 우선 시도하고, 사이트의 보안 로그인 스크립트가
headless 환경에서 동작하지 않으면 RSA 보안 로그인 API를 사용해 세션을 만든 뒤
그 쿠키를 Playwright 컨텍스트로 옮기는 2단계 전략을 사용합니다.

현재 동행복권 로그인 프로토콜:
1. /user.do?method=login 으로 세션 준비
2. /login/selectRsaModulus.do 에서 RSA 공개키 조회
3. ID/비밀번호를 PKCS#1 v1.5 로 암호화
4. /login/securityLoginCheck.do 로 제출
5. 발급된 JSESSIONID/WMONID 쿠키를 게임 브라우저에 적용

프로토콜 비교 참고:
https://github.com/techinpark/lottery-bot/blob/main/auth.py
(구현은 이 프로젝트 구조에 맞게 재작성했습니다.)
"""
from __future__ import annotations

import binascii
import json
import re
import time
from html import unescape

import requests
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from applog import get_logger
from config import debug_path, env_bool, env_str, load_environment

log = get_logger(__name__)

LOGIN_URLS = (
    "https://www.dhlottery.co.kr/login",
    "https://www.dhlottery.co.kr/user.do?method=login",
)
MAIN_URL = "https://www.dhlottery.co.kr/main"
MYPAGE_URL = "https://www.dhlottery.co.kr/mypage/home"
RSA_KEY_URL = "https://www.dhlottery.co.kr/login/selectRsaModulus.do"
SECURITY_LOGIN_URL = "https://www.dhlottery.co.kr/login/securityLoginCheck.do"

HTTP_TIMEOUT = 30
HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

LOGIN_INDICATORS = (
    "text=/로그아웃/",
    "text=/마이페이지/",
    "[href*='logout']",
    "[href*='mypage']",
)

ERROR_SELECTORS = (
    ".error_msg",
    ".alert",
    "[class*='error']",
    "[class*='alert']",
    "#loginError",
    "#errorMessage",
)

load_environment()


def get_credentials(user_id: str | None = None, passwd: str | None = None) -> tuple[str, str]:
    """주입값 또는 환경변수에서 자격증명을 호출 시점에 읽습니다."""
    load_environment()
    resolved_id = user_id if user_id else env_str("USER_ID")
    resolved_pw = passwd if passwd else env_str("PASSWD")
    return resolved_id, resolved_pw


def _capture_debug(page: Page, name: str, include_html: bool = False) -> None:
    """DEBUG가 켜진 호출부에서만 사용하는 디버그 산출물 저장 헬퍼."""
    try:
        page.screenshot(path=debug_path(f"{name}.png"))
        if include_html:
            with open(debug_path(f"{name}.html"), "w", encoding="utf-8") as fp:
                fp.write(page.content())
        log.debug("디버그 산출물 저장: debug/%s", name)
    except Exception as exc:
        log.debug("디버그 저장 실패(%s): %s", name, exc)


def _find_error_message(page: Page) -> str | None:
    """화면에 표시된 구체적인 로그인 오류를 찾습니다."""
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


def _looks_logged_in_url(url: str) -> bool:
    lowered = (url or "").lower()
    return bool(lowered) and "/login" not in lowered and "method=login" not in lowered


def _verify_logged_in(page: Page) -> bool:
    """URL과 로그인 전용 UI 지표로 인증 상태를 확인합니다."""
    if not _looks_logged_in_url(page.url):
        return False

    # 마이페이지 URL 자체는 인증 성공의 강한 지표입니다.
    if "/mypage/" in page.url:
        return True

    for indicator in LOGIN_INDICATORS:
        try:
            element = page.locator(indicator)
            if element.count() > 0 and element.first.is_visible(timeout=1200):
                log.debug("로그인 확인 지표 발견: %s", indicator)
                return True
        except Exception:
            continue
    return False


def _open_login_page(page: Page) -> str:
    """신·구 로그인 URL을 순서대로 시도하고 실제 사용한 URL을 반환합니다."""
    errors = []
    for url in LOGIN_URLS:
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_selector("#inpUserId", state="visible", timeout=15000)
            log.debug("로그인 페이지 진입: %s", page.url)
            return url
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}")
            log.debug("로그인 URL 시도 실패(%s): %s", url, exc)
    raise RuntimeError(f"로그인 페이지를 열 수 없습니다: {errors}")


def _login_via_browser(
    page: Page,
    user_id: str,
    passwd: str,
    want_debug: bool,
) -> None:
    """
    사이트의 브라우저 JavaScript를 이용해 로그인합니다.

    버튼 click만 사용하던 기존 방식과 달리 Enter 제출을 우선 사용합니다.
    일부 버전의 사이트는 비밀번호 필드 Enter에서만 보안 로그인 핸들러를
    정상 연결하는 사례가 있기 때문입니다.
    """
    _open_login_page(page)

    id_field = page.locator("#inpUserId")
    pw_field = page.locator("#inpUserPswdEncn")
    id_field.fill(user_id)
    pw_field.fill(passwd)

    if want_debug:
        _capture_debug(page, "login_browser_01_before")

    start_url = page.url

    # Enter를 우선 시도해 폼의 submit/security handler를 직접 실행합니다.
    pw_field.press("Enter")
    log.info("브라우저 로그인 제출 후 대기 중...")

    try:
        page.wait_for_url(
            lambda url: _looks_logged_in_url(url),
            timeout=20000,
            wait_until="domcontentloaded",
        )
    except PlaywrightTimeoutError:
        # Enter가 핸들러에 연결되지 않은 페이지를 위한 버튼 fallback.
        if page.url == start_url or not _looks_logged_in_url(page.url):
            button = page.locator("#btnLogin")
            if button.count() > 0:
                log.info("Enter 제출 후 이동 없음 — 로그인 버튼 fallback")
                button.first.click(timeout=5000)
                try:
                    page.wait_for_url(
                        lambda url: _looks_logged_in_url(url),
                        timeout=20000,
                        wait_until="domcontentloaded",
                    )
                except PlaywrightTimeoutError:
                    pass

    time.sleep(2)

    if want_debug:
        _capture_debug(page, "login_browser_02_after", include_html=True)

    if not _looks_logged_in_url(page.url):
        error_message = _find_error_message(page)
        if error_message:
            raise RuntimeError(f"브라우저 로그인 거부: {error_message}")
        raise RuntimeError(
            "브라우저 보안 로그인 스크립트가 페이지 이동을 완료하지 못했습니다."
        )

    # 메인 이동 후 인증 UI 확인
    page.goto(MAIN_URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(1)
    if not _verify_logged_in(page):
        raise RuntimeError("브라우저 로그인 후 인증 상태를 확인할 수 없습니다.")


def _rsa_encrypt(value: str, modulus_hex: str, exponent_hex: str) -> str:
    """PKCS#1 v1.5 RSA 암호문을 16진수 문자열로 반환합니다."""
    try:
        from Crypto.Cipher import PKCS1_v1_5
        from Crypto.PublicKey import RSA
    except ImportError as exc:
        raise RuntimeError(
            "RSA 로그인에 필요한 pycryptodome이 설치되지 않았습니다."
        ) from exc

    key = RSA.construct((int(modulus_hex, 16), int(exponent_hex, 16)))
    cipher = PKCS1_v1_5.new(key)
    encrypted = cipher.encrypt(value.encode("utf-8"))
    return binascii.hexlify(encrypted).decode("ascii")


def _extract_rsa_key(payload: dict) -> tuple[str, str]:
    """신·구 RSA 공개키 응답 구조를 모두 지원합니다."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    modulus = data.get("rsaModulus")
    exponent = data.get("publicExponent")
    if not modulus or not exponent:
        raise RuntimeError("RSA 공개키 응답에 rsaModulus/publicExponent가 없습니다.")
    return str(modulus), str(exponent)


def _extract_http_error(text: str) -> str | None:
    """응답에서 비밀값 없이 사용자에게 보여줄 로그인 오류 문구를 추출합니다."""
    if not text:
        return None

    # JSON 응답
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            for key in ("message", "msg", "errorMessage", "resultMsg"):
                value = payload.get(key)
                if value:
                    return str(value)[:300]
    except ValueError:
        pass

    # JavaScript alert('...')
    alert_match = re.search(r"alert\s*\(\s*['\"]([^'\"]+)", text, re.IGNORECASE)
    if alert_match:
        return unescape(alert_match.group(1).strip())[:300]

    # HTML 태그 제거 후 로그인 관련 문장만 추림
    plain = unescape(re.sub(r"<[^>]+>", " ", text))
    plain = re.sub(r"\s+", " ", plain).strip()
    markers = ("비밀번호", "아이디", "로그인", "인증", "잠김", "오류")
    if any(marker in plain for marker in markers):
        for sentence in re.split(r"[.!?。]", plain):
            if any(marker in sentence for marker in markers):
                return sentence.strip()[:300]
    return None


def _request_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": HTTP_USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://www.dhlottery.co.kr",
        "Referer": referer,
    }


def _playwright_cookies(session: requests.Session) -> list[dict]:
    """requests 쿠키를 Playwright add_cookies 형식으로 변환합니다."""
    converted = []
    for cookie in session.cookies:
        domain = cookie.domain or ".dhlottery.co.kr"
        item = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": domain,
            "path": cookie.path or "/",
            "secure": bool(cookie.secure),
            "httpOnly": bool(cookie.has_nonstandard_attr("HttpOnly")),
        }
        if cookie.expires and cookie.expires > 0:
            item["expires"] = float(cookie.expires)
        converted.append(item)
    return converted


def _login_via_http_rsa(
    page: Page,
    user_id: str,
    passwd: str,
    want_debug: bool,
) -> None:
    """RSA 보안 로그인 API로 세션을 만들고 Playwright에 쿠키를 이식합니다."""
    log.info("RSA 보안 로그인 fallback 시작")

    session = requests.Session()
    login_referer = LOGIN_URLS[1]
    base_headers = _request_headers(login_referer)

    try:
        # 1. 세션/보안 쿠키 준비
        session.get(
            "https://www.dhlottery.co.kr/",
            headers=_request_headers("https://www.dhlottery.co.kr/"),
            timeout=HTTP_TIMEOUT,
        ).raise_for_status()
        session.get(
            login_referer,
            headers=base_headers,
            timeout=HTTP_TIMEOUT,
        ).raise_for_status()

        # 2. RSA 공개키
        key_headers = dict(base_headers)
        key_headers.update(
            {
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        key_response = session.get(
            RSA_KEY_URL,
            headers=key_headers,
            timeout=HTTP_TIMEOUT,
        )
        key_response.raise_for_status()
        try:
            key_payload = key_response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"RSA 공개키 응답이 JSON이 아닙니다 (HTTP {key_response.status_code})."
            ) from exc
        modulus, exponent = _extract_rsa_key(key_payload)

        # 3. 자격증명 암호화 및 제출
        form = {
            "userId": _rsa_encrypt(user_id, modulus, exponent),
            "userPswdEncn": _rsa_encrypt(passwd, modulus, exponent),
            "inpUserId": user_id,
        }
        login_headers = dict(base_headers)
        login_headers["Content-Type"] = "application/x-www-form-urlencoded"
        response = session.post(
            SECURITY_LOGIN_URL,
            headers=login_headers,
            data=form,
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()

        response_error = _extract_http_error(response.text)

        # 4. 인증이 필요한 마이페이지로 검증
        verify_response = session.get(
            MYPAGE_URL,
            headers=_request_headers(MAIN_URL),
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
        )
        verify_response.raise_for_status()

        verified_url = verify_response.url.lower()
        verified_text = verify_response.text
        logged_in = (
            "/login" not in verified_url
            and "method=login" not in verified_url
            and (
                "로그아웃" in verified_text
                or "예치금" in verified_text
                or "/mypage/" in verified_url
            )
        )

        if not logged_in:
            verify_error = _extract_http_error(verified_text)
            reason = verify_error or response_error
            if reason:
                raise RuntimeError(f"RSA 로그인 거부: {reason}")
            raise RuntimeError(
                "RSA 로그인 응답은 수신했지만 인증된 마이페이지 세션이 만들어지지 않았습니다. "
                "GitHub Secret의 USER_ID/PASSWD 또는 계정 잠금 상태를 확인하세요."
            )

        cookies = _playwright_cookies(session)
        if not cookies:
            raise RuntimeError("RSA 로그인 후 브라우저에 전달할 세션 쿠키가 없습니다.")

        # 5. Playwright 컨텍스트에 인증 쿠키 이식
        page.context.clear_cookies()
        page.context.add_cookies(cookies)
        page.goto(MYPAGE_URL, timeout=60000, wait_until="domcontentloaded")
        time.sleep(2)

        if want_debug:
            _capture_debug(page, "login_rsa_01_after", include_html=True)

        if not _verify_logged_in(page):
            raise RuntimeError("RSA 쿠키를 적용했지만 Playwright 인증 상태를 확인할 수 없습니다.")

        log.info("RSA 보안 로그인 성공")
    finally:
        session.close()


def login(
    page: Page,
    max_retries: int = 3,
    user_id: str | None = None,
    passwd: str | None = None,
    debug: bool | None = None,
) -> None:
    """
    동행복권에 로그인합니다.

    브라우저 폼 로그인 → RSA 보안 API fallback 순으로 시도합니다.
    각 전략은 max_retries 범위에서 반복하지만, 잘못된 비밀번호로 무의미한
    과다 요청이 발생하지 않도록 기본 3회를 넘지 않습니다.
    """
    resolved_id, resolved_pw = get_credentials(user_id, passwd)
    if not resolved_id or not resolved_pw:
        raise ValueError("USER_ID 또는 PASSWD가 설정되지 않았습니다.")

    want_debug = env_bool("DEBUG", False) if debug is None else debug
    last_error: Exception | None = None

    # 1. 브라우저 로그인은 한 번만 시도합니다. 반복해도 같은 JS 실패가 재현되기 때문입니다.
    try:
        log.info("브라우저 로그인 시작")
        _login_via_browser(page, resolved_id, resolved_pw, want_debug)
        log.info("브라우저 로그인 성공")
        return
    except Exception as exc:
        last_error = exc
        log.warning("브라우저 로그인 실패: %s", exc)

    # 2. 현재 사이트의 RSA 보안 로그인 API fallback
    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                delay = min(2 * attempt, 6)
                log.info("RSA 로그인 재시도 %s/%s (%s초 후)", attempt, max_retries, delay)
                time.sleep(delay)
            _login_via_http_rsa(page, resolved_id, resolved_pw, want_debug)
            return
        except Exception as exc:
            last_error = exc
            log.warning("RSA 로그인 시도 %s/%s 실패: %s", attempt, max_retries, exc)

            # 자격증명/계정 관련 명시적 거부는 반복하지 않습니다.
            message = str(exc)
            if any(
                marker in message
                for marker in ("비밀번호", "아이디", "계정 잠금", "로그인 거부")
            ):
                break

    if want_debug:
        _capture_debug(page, "login_final_failure", include_html=True)

    raise RuntimeError(f"로그인 실패 (브라우저 + RSA fallback): {last_error}")
