"""
설정 파싱 및 검증 테스트.
"""
import pytest

from config import (
    ALLOWED_CHARGE_AMOUNTS,
    LOTTO645_MAX_GAMES,
    PER_720_PURCHASE_AMOUNT,
    Settings,
    env_bool,
    env_int,
    env_number_sets,
)

# ---------------------------------------------------------------- 파서


def test_env_int_parses_commas(monkeypatch):
    monkeypatch.setenv("X_AMOUNT", " 12,345 ")
    assert env_int("X_AMOUNT", 0) == 12345


def test_env_int_falls_back_on_invalid(monkeypatch):
    monkeypatch.setenv("X_AMOUNT", "not-a-number")
    assert env_int("X_AMOUNT", 777) == 777


def test_env_int_falls_back_on_empty(monkeypatch):
    monkeypatch.setenv("X_AMOUNT", "   ")
    assert env_int("X_AMOUNT", 5) == 5


def test_env_int_missing_key_uses_default(monkeypatch):
    monkeypatch.delenv("X_MISSING", raising=False)
    assert env_int("X_MISSING", 42) == 42


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "Y"])
def test_env_bool_truthy(monkeypatch, value):
    monkeypatch.setenv("X_FLAG", value)
    assert env_bool("X_FLAG", False) is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe"])
def test_env_bool_falsy(monkeypatch, value):
    monkeypatch.setenv("X_FLAG", value)
    assert env_bool("X_FLAG", True) is False


def test_env_number_sets_valid(monkeypatch):
    monkeypatch.setenv("X_NUMS", "[[6,5,4,3,2,1],[7,8,9,10,11,12]]")
    result = env_number_sets("X_NUMS")
    assert result == [[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]]


def test_env_number_sets_rejects_malformed(monkeypatch):
    # 잘못된 JSON
    monkeypatch.setenv("X_NUMS", "not json")
    assert env_number_sets("X_NUMS") == []

    # 6개가 아님
    monkeypatch.setenv("X_NUMS", "[[1,2,3]]")
    assert env_number_sets("X_NUMS") == []

    # 중복 번호
    monkeypatch.setenv("X_NUMS", "[[1,1,2,3,4,5]]")
    assert env_number_sets("X_NUMS") == []

    # 범위 밖
    monkeypatch.setenv("X_NUMS", "[[1,2,3,4,5,46]]")
    assert env_number_sets("X_NUMS") == []


def test_env_number_sets_empty(monkeypatch):
    monkeypatch.delenv("X_NUMS", raising=False)
    assert env_number_sets("X_NUMS") == []


# ---------------------------------------------------------------- 파생 값


def test_total_games_and_cost():
    settings = Settings(
        user_id="u",
        passwd="p",
        auto_games=1,
        manual_numbers=[[1, 2, 3, 4, 5, 6]],
        strategy_games=2,
    )
    assert settings.lotto645_total_games == 4
    assert settings.lotto645_cost == 4000


def test_required_balance_includes_both_games():
    settings = Settings(
        user_id="u",
        passwd="p",
        strategy_games=3,
        enable_lotto720=True,
        lotto720_amount=10000,
    )
    # 3게임 3,000원 + 720+ 10,000원 = 13,000원
    assert settings.required_balance == 13000


def test_required_balance_respects_floor():
    settings = Settings(
        user_id="u",
        passwd="p",
        strategy_games=1,
        enable_lotto720=False,
        min_balance_floor=10000,
    )
    # 1,000원이 필요하지만 하한이 10,000원
    assert settings.required_balance == 10000


def test_required_balance_excludes_disabled_720():
    settings = Settings(
        user_id="u",
        passwd="p",
        strategy_games=5,
        enable_lotto720=False,
        min_balance_floor=0,
    )
    assert settings.required_balance == 5000


def test_lotto720_purchase_count():
    settings = Settings(lotto720_amount=15000)
    assert settings.lotto720_purchase_count == 3


# ---------------------------------------------------------------- 검증


def test_validate_requires_credentials():
    errors = Settings().validate()
    assert any("USER_ID" in e for e in errors)
    assert any("PASSWD" in e for e in errors)


def test_validate_rejects_too_many_games():
    settings = Settings(
        user_id="u",
        passwd="p",
        auto_games=3,
        strategy_games=4,
    )
    errors = settings.validate()
    assert any("한도" in e for e in errors)


def test_validate_accepts_max_games():
    settings = Settings(
        user_id="u",
        passwd="p",
        strategy_games=LOTTO645_MAX_GAMES,
        lotto720_amount=PER_720_PURCHASE_AMOUNT,
        charge_amount=10000,
    )
    assert settings.validate() == []


def test_validate_rejects_bad_720_amount():
    settings = Settings(user_id="u", passwd="p", lotto720_amount=7000)
    errors = settings.validate()
    assert any("5,000원 단위" in e for e in errors)


def test_validate_rejects_zero_720_amount():
    settings = Settings(user_id="u", passwd="p", lotto720_amount=0)
    errors = settings.validate()
    assert any("0보다 커야" in e for e in errors)


def test_validate_rejects_bad_charge_amount():
    settings = Settings(user_id="u", passwd="p", charge_amount=7000)
    errors = settings.validate()
    assert any("CHARGE_AMOUNT" in e for e in errors)


@pytest.mark.parametrize("amount", ALLOWED_CHARGE_AMOUNTS)
def test_validate_accepts_allowed_charge_amounts(amount):
    settings = Settings(user_id="u", passwd="p", charge_amount=amount)
    assert settings.validate() == []


def test_summary_excludes_secrets():
    settings = Settings(
        user_id="myid",
        passwd="secret-password",
        charge_pin="123456",
        telegram_bot_token="token-value",
    )
    summary = settings.summary()
    assert "secret-password" not in summary
    assert "123456" not in summary
    assert "token-value" not in summary
    assert "myid" not in summary
