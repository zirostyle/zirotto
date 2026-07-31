"""로그인 프로토콜의 순수 로직 회귀 테스트."""
from dataclasses import dataclass

import pytest

from login import (
    _extract_http_error,
    _extract_rsa_key,
    _looks_logged_in_url,
    _playwright_cookies,
)


def test_extract_rsa_key_nested_payload():
    payload = {
        "data": {
            "rsaModulus": "abcdef",
            "publicExponent": "010001",
        }
    }
    assert _extract_rsa_key(payload) == ("abcdef", "010001")


def test_extract_rsa_key_flat_payload():
    payload = {"rsaModulus": "1234", "publicExponent": "03"}
    assert _extract_rsa_key(payload) == ("1234", "03")


def test_extract_rsa_key_rejects_missing_values():
    with pytest.raises(RuntimeError, match="rsaModulus"):
        _extract_rsa_key({"data": {}})


def test_extract_http_error_json():
    assert _extract_http_error('{"message":"비밀번호가 올바르지 않습니다"}') == (
        "비밀번호가 올바르지 않습니다"
    )


def test_extract_http_error_javascript_alert():
    text = "<script>alert('아이디 또는 비밀번호를 확인하세요.');</script>"
    assert _extract_http_error(text) == "아이디 또는 비밀번호를 확인하세요."


def test_extract_http_error_html():
    text = "<html><body><div>로그인 인증 오류가 발생했습니다.</div></body></html>"
    assert _extract_http_error(text) == "로그인 인증 오류가 발생했습니다"


def test_extract_http_error_unrelated_html_returns_none():
    assert _extract_http_error("<html><body>정상 페이지</body></html>") is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.dhlottery.co.kr/main", True),
        ("https://www.dhlottery.co.kr/mypage/home", True),
        ("https://www.dhlottery.co.kr/login", False),
        ("https://www.dhlottery.co.kr/user.do?method=login", False),
        ("", False),
    ],
)
def test_looks_logged_in_url(url, expected):
    assert _looks_logged_in_url(url) is expected


@dataclass
class FakeCookie:
    name: str
    value: str
    domain: str = ".dhlottery.co.kr"
    path: str = "/"
    secure: bool = True
    expires: int | None = None
    http_only: bool = False

    def has_nonstandard_attr(self, name):
        return name == "HttpOnly" and self.http_only


class FakeJar:
    def __init__(self, cookies):
        self._cookies = cookies

    def __iter__(self):
        return iter(self._cookies)


class FakeSession:
    def __init__(self, cookies):
        self.cookies = FakeJar(cookies)


def test_playwright_cookie_conversion():
    session = FakeSession(
        [
            FakeCookie(
                name="JSESSIONID",
                value="session-value",
                secure=True,
                expires=2_000_000_000,
                http_only=True,
            ),
            FakeCookie(name="WMONID", value="wmon-value", secure=False),
        ]
    )

    converted = _playwright_cookies(session)

    assert len(converted) == 2
    assert converted[0]["name"] == "JSESSIONID"
    assert converted[0]["value"] == "session-value"
    assert converted[0]["domain"] == ".dhlottery.co.kr"
    assert converted[0]["httpOnly"] is True
    assert converted[0]["expires"] == 2_000_000_000.0
    assert "expires" not in converted[1]


def test_playwright_cookie_uses_default_domain_and_path():
    cookie = FakeCookie(name="X", value="Y", domain="", path="")
    converted = _playwright_cookies(FakeSession([cookie]))
    assert converted[0]["domain"] == ".dhlottery.co.kr"
    assert converted[0]["path"] == "/"
