"""
테스트 공용 설정.

src/ 를 import 경로에 추가하고, 순수 로직 테스트를 위해
외부 의존성(requests, playwright)이 설치되지 않은 환경에서도
모듈을 import 할 수 있도록 최소 스텁을 주입합니다.

주의: 스텁은 '순수 로직 테스트' 목적입니다.
브라우저 자동화 동작 자체를 검증하지는 않습니다.
"""
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _ensure_requests_stub() -> None:
    try:
        import requests  # noqa: F401
        return
    except ImportError:
        pass

    module = types.ModuleType("requests")

    class RequestException(Exception):
        pass

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {}

    def _unavailable(*_args, **_kwargs):
        raise RequestException("requests 스텁: 네트워크 호출 불가")

    module.RequestException = RequestException
    module.Response = Response
    module.get = _unavailable
    module.post = _unavailable
    sys.modules["requests"] = module


def _ensure_playwright_stub() -> None:
    try:
        import playwright.sync_api  # noqa: F401
        return
    except ImportError:
        pass

    playwright_pkg = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")

    class _Placeholder:
        """실제 Playwright 타입 대신 사용되는 자리표시자."""

        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("Playwright 스텁은 인스턴스화할 수 없습니다.")

    class TimeoutError(Exception):  # noqa: A001 - Playwright API 이름 유지
        pass

    def sync_playwright(*_args, **_kwargs):
        raise RuntimeError("Playwright 스텁: 브라우저를 실행할 수 없습니다.")

    sync_api.Page = _Placeholder
    sync_api.Frame = _Placeholder
    sync_api.Playwright = _Placeholder
    sync_api.TimeoutError = TimeoutError
    sync_api.sync_playwright = sync_playwright

    playwright_pkg.sync_api = sync_api
    sys.modules["playwright"] = playwright_pkg
    sys.modules["playwright.sync_api"] = sync_api


_ensure_requests_stub()
_ensure_playwright_stub()
