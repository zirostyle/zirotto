#!/usr/bin/env python3
"""
중앙 설정 모듈.

기존에는 CHARGE_AMOUNT, 최소 잔액, 충전 금액 화이트리스트 등이
여러 파일에 하드코딩되어 있었습니다. 이 모듈로 통합합니다.

.env 로딩도 이 모듈이 책임집니다. (기존에는 login.py import 부작용에 의존)
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 의존성 미설치 환경 대비
    def load_dotenv(dotenv_path=None, **_kwargs):
        """
        python-dotenv 가 없을 때의 최소 대체 구현.
        KEY=VALUE 형식만 파싱하며, 이미 설정된 환경변수는 덮어쓰지 않습니다.
        """
        if dotenv_path is None:
            return False
        path = Path(dotenv_path)
        if not path.exists():
            return False
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
        return True

# ---------------------------------------------------------------- 상수

PER_720_PURCHASE_AMOUNT = 5000
"""연금복권 720+ 온라인 1회 구매 단위 (원)."""

LOTTO645_PRICE_PER_GAME = 1000
"""로또 6/45 1게임 가격 (원)."""

LOTTO645_MAX_GAMES = 5
"""로또 6/45 1회 최대 게임 수."""

ALLOWED_CHARGE_AMOUNTS = (5000, 10000, 20000)
"""간편충전 드롭다운에서 선택 가능한 금액."""

DEBUG_DIR_NAME = "debug"
"""디버그 산출물(스크린샷/HTML) 디렉토리명."""


# ---------------------------------------------------------------- .env 로딩

_ENV_LOADED = False


def load_environment() -> Path | None:
    """
    .env 파일을 찾아 로드합니다. (멱등)

    우선순위:
      1. 프로젝트 루트 (이 파일의 상위 디렉토리)
      2. 현재 작업 디렉토리
      3. python-dotenv 기본 탐색 (상위 트리)

    Returns:
        로드한 .env 경로. 3번 fallback 이거나 못 찾으면 None.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return None

    _ENV_LOADED = True

    project_root = Path(__file__).resolve().parent.parent
    candidates = [project_root / ".env", Path.cwd() / ".env"]

    for candidate in candidates:
        if candidate.exists():
            load_dotenv(dotenv_path=candidate)
            return candidate

    load_dotenv()
    return None


# ---------------------------------------------------------------- 파서 헬퍼


def env_str(key: str, default: str = "") -> str:
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip()


def env_int(key: str, default: int) -> int:
    """콤마/공백을 허용하는 정수 파서. 실패 시 default."""
    raw = os.environ.get(key)
    if raw is None:
        return default
    cleaned = str(raw).replace(",", "").strip()
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except (TypeError, ValueError):
        return default


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on", "y")


def env_number_sets(key: str) -> list[list[int]]:
    """
    MANUAL_NUMBERS 같은 JSON 번호 배열을 파싱합니다.
    형식이 잘못되면 빈 리스트를 반환합니다 (예외를 던지지 않음).
    """
    raw = os.environ.get(key)
    if not raw or not str(raw).strip():
        return []
    try:
        parsed = json.loads(str(raw).strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    if not isinstance(parsed, list):
        return []

    result: list[list[int]] = []
    for item in parsed:
        if not isinstance(item, list) or len(item) != 6:
            continue
        try:
            nums = [int(n) for n in item]
        except (TypeError, ValueError):
            continue
        if len(set(nums)) != 6:
            continue
        if not all(1 <= n <= 45 for n in nums):
            continue
        result.append(sorted(nums))
    return result


# ---------------------------------------------------------------- 설정 객체


@dataclass
class Settings:
    """실행 시점의 전체 설정 스냅샷."""

    # 자격증명
    user_id: str = ""
    passwd: str = ""
    charge_pin: str = ""

    # 로또 6/45
    enable_lotto645: bool = True
    lotto645_enable_from: str = ""
    auto_games: int = 0
    manual_numbers: list[list[int]] = field(default_factory=list)

    # 번호 전략
    strategy_games: int = 0
    strategy_seed: int | None = None

    # 연금복권 720+
    enable_lotto720: bool = True
    lotto720_amount: int = PER_720_PURCHASE_AMOUNT

    # 충전
    charge_amount: int = 10000
    min_balance_floor: int = 10000

    # 운영 플래그
    dry_run: bool = False
    debug: bool = False

    # 알림
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ---------------- 파생 값

    @property
    def lotto645_total_games(self) -> int:
        """실제로 구매를 시도할 6/45 총 게임 수."""
        return self.auto_games + len(self.manual_numbers) + self.strategy_games

    @property
    def lotto645_cost(self) -> int:
        return self.lotto645_total_games * LOTTO645_PRICE_PER_GAME

    @property
    def lotto720_purchase_count(self) -> int:
        return self.lotto720_amount // PER_720_PURCHASE_AMOUNT

    @property
    def required_balance(self) -> int:
        """이번 회차 구매에 필요한 최소 구매가능 금액."""
        needed = self.lotto645_cost
        if self.enable_lotto720:
            needed += self.lotto720_amount
        return max(needed, self.min_balance_floor)

    def validate(self) -> list[str]:
        """설정 오류 목록을 반환합니다. 빈 리스트면 정상."""
        errors: list[str] = []

        if not self.user_id:
            errors.append("USER_ID 가 설정되지 않았습니다.")
        if not self.passwd:
            errors.append("PASSWD 가 설정되지 않았습니다.")

        total = self.lotto645_total_games
        if self.enable_lotto645 and total > LOTTO645_MAX_GAMES:
            errors.append(
                f"로또 6/45 총 게임 수가 {total}게임으로 한도({LOTTO645_MAX_GAMES})를 초과합니다. "
                f"(자동 {self.auto_games} + 수동 {len(self.manual_numbers)} + 전략 {self.strategy_games})"
            )

        if self.enable_lotto720:
            if self.lotto720_amount <= 0:
                errors.append("LOTTO720_AMOUNT 는 0보다 커야 합니다.")
            elif self.lotto720_amount % PER_720_PURCHASE_AMOUNT != 0:
                errors.append(
                    f"LOTTO720_AMOUNT 는 {PER_720_PURCHASE_AMOUNT:,}원 단위여야 합니다. "
                    f"(현재: {self.lotto720_amount:,})"
                )

        if self.charge_amount not in ALLOWED_CHARGE_AMOUNTS:
            errors.append(
                f"CHARGE_AMOUNT 는 {ALLOWED_CHARGE_AMOUNTS} 중 하나여야 합니다. "
                f"(현재: {self.charge_amount})"
            )

        return errors

    def summary(self) -> str:
        """로그용 요약 문자열 (비밀값 제외)."""
        lines = [
            f"6/45 활성: {self.enable_lotto645}",
            f"  자동: {self.auto_games}게임 / 수동: {len(self.manual_numbers)}게임 / 전략: {self.strategy_games}게임",
            f"  예상 비용: {self.lotto645_cost:,}원",
            f"720+ 활성: {self.enable_lotto720} (목표 {self.lotto720_amount:,}원, {self.lotto720_purchase_count}회)",
            f"필요 잔액: {self.required_balance:,}원 / 충전 단위: {self.charge_amount:,}원",
            f"DRY_RUN: {self.dry_run} / DEBUG: {self.debug}",
            f"텔레그램 설정됨: {bool(self.telegram_bot_token and self.telegram_chat_id)}",
        ]
        return "\n".join(lines)


def load_settings() -> Settings:
    """환경변수에서 Settings 를 구성합니다."""
    load_environment()

    return Settings(
        user_id=env_str("USER_ID"),
        passwd=env_str("PASSWD"),
        charge_pin=env_str("CHARGE_PIN"),
        enable_lotto645=env_bool("ENABLE_LOTTO645", True),
        lotto645_enable_from=env_str("LOTTO645_ENABLE_FROM"),
        auto_games=env_int("AUTO_GAMES", 0),
        manual_numbers=env_number_sets("MANUAL_NUMBERS"),
        strategy_games=env_int("STRATEGY_GAMES", 0),
        strategy_seed=(env_int("STRATEGY_SEED", -1) if os.environ.get("STRATEGY_SEED") else None),
        enable_lotto720=env_bool("ENABLE_LOTTO720", True),
        lotto720_amount=env_int("LOTTO720_AMOUNT", PER_720_PURCHASE_AMOUNT),
        charge_amount=env_int("CHARGE_AMOUNT", 10000),
        min_balance_floor=env_int("MIN_BALANCE_FLOOR", 10000),
        dry_run=env_bool("DRY_RUN", False),
        debug=env_bool("DEBUG", False),
        telegram_bot_token=env_str("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=env_str("TELEGRAM_CHAT_ID"),
    )


# ---------------------------------------------------------------- 디버그 산출물


def debug_dir() -> Path:
    """디버그 산출물 디렉토리를 생성하고 반환합니다."""
    project_root = Path(__file__).resolve().parent.parent
    target = project_root / DEBUG_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def debug_path(filename: str) -> str:
    """디버그 파일의 전체 경로 문자열."""
    return str(debug_dir() / filename)
