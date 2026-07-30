#!/usr/bin/env python3
"""
예치금 충전 (간편충전 + OCR 랜덤 키패드 PIN 입력).

[수정 이력]
- 미사용 import (re, Path, load_dotenv) 제거
- CHARGE_PIN 을 모듈 전역 캐시가 아니라 호출 시점에 읽음 (주입 가능)
- 디버그 스크린샷을 DEBUG 플래그로 게이팅하고 debug/ 로 격리
- 허용 금액 목록을 config.ALLOWED_CHARGE_AMOUNTS 로 이전
- print → logging, bare except 제거
"""
import io
import sys
import time

from playwright.sync_api import (
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from applog import get_logger
from config import (
    ALLOWED_CHARGE_AMOUNTS,
    debug_path,
    env_bool,
    env_str,
    load_settings,
)
from login import login

log = get_logger(__name__)

CHARGE_URL = "https://www.dhlottery.co.kr/mypage/mndpChrg"

KEYPAD_SELECTORS = (".nppfs-keypad", ".kpd-layer", "#keypad", ".keypad")

OCR_CONFIGS = (
    r"--oem 3 --psm 10 -c tessedit_char_whitelist=0123456789",  # 단일 문자
    r"--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789",   # 단일 라인
    r"--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789",   # 단일 단어
)


def _get_charge_pin(charge_pin: str | None = None) -> str:
    """호출 시점에 PIN 을 읽습니다. 인자 주입이 환경변수보다 우선."""
    if charge_pin:
        return charge_pin
    return env_str("CHARGE_PIN")


def _snap(page: Page, name: str, want_debug: bool, include_html: bool = False) -> None:
    if not want_debug:
        return
    try:
        page.screenshot(path=debug_path(f"charge_{name}.png"))
        if include_html:
            with open(debug_path(f"charge_{name}.html"), "w", encoding="utf-8") as fp:
                fp.write(page.content())
        log.debug("충전 디버그 산출물 저장: charge_%s", name)
    except Exception as exc:
        log.debug("충전 디버그 저장 실패(%s): %s", name, exc)


def parse_keypad(page: Page) -> dict[str, object]:
    """
    랜덤 키패드 이미지를 OCR로 분석하여 각 숫자의 위치를 파악합니다.

    Returns:
        {숫자(str): locator} 매핑 (0-9)

    Raises:
        RuntimeError: 키패드 버튼을 찾지 못했을 경우
    """
    import pytesseract
    from PIL import Image, ImageEnhance, ImageFilter

    keypad_selector = ".nppfs-keypad"
    page.wait_for_selector(keypad_selector, state="visible")

    buttons = page.locator("img.kpd-data")
    count = buttons.count()
    if count == 0:
        raise RuntimeError("키패드 버튼(img.kpd-data)을 찾을 수 없습니다.")

    button_positions = []
    for i in range(count):
        btn = buttons.nth(i)
        box = btn.bounding_box()
        if box and box["width"] > 0 and box["height"] > 0:
            button_positions.append(
                {
                    "element": btn,
                    "x": box["x"],
                    "y": box["y"],
                    "w": box["width"],
                    "h": box["height"],
                }
            )

    if not button_positions:
        raise RuntimeError("키패드 버튼의 위치 정보를 얻을 수 없습니다.")

    time.sleep(1)  # 렌더링/애니메이션 대기
    keypad_box = page.locator(keypad_selector).bounding_box()
    if not keypad_box or keypad_box["width"] == 0 or keypad_box["height"] == 0:
        raise RuntimeError(f"키패드 컨테이너 크기가 유효하지 않습니다: {keypad_box}")

    screenshot_bytes = page.screenshot(clip=keypad_box)
    keypad_img = Image.open(io.BytesIO(screenshot_bytes))

    number_map: dict[str, object] = {}
    button_positions.sort(key=lambda b: (b["y"], b["x"]))

    for btn_info in button_positions:
        lx = btn_info["x"] - keypad_box["x"]
        ly = btn_info["y"] - keypad_box["y"]
        button_img = keypad_img.crop((lx, ly, lx + btn_info["w"], ly + btn_info["h"]))

        gray = button_img.convert("L")
        enhanced = ImageEnhance.Contrast(gray).enhance(2.0)
        binary = enhanced.point(lambda p: 255 if p > 128 else 0)

        recognized = None
        for config in OCR_CONFIGS:
            result = pytesseract.image_to_string(binary, config=config).strip()
            if result.isdigit() and len(result) == 1:
                recognized = result
                break

        if not recognized:
            sharp = enhanced.filter(ImageFilter.SHARPEN)
            binary_sharp = sharp.point(lambda p: 255 if p > 128 else 0)
            for config in OCR_CONFIGS:
                result = pytesseract.image_to_string(binary_sharp, config=config).strip()
                if result.isdigit() and len(result) == 1:
                    recognized = result
                    break

        if recognized and recognized not in number_map:
            number_map[recognized] = btn_info["element"]

    log.info("키패드 숫자 인식: %s개 (%s)", len(number_map), "".join(sorted(number_map)))
    return number_map


def charge_deposit(
    page: Page,
    amount: int,
    charge_pin: str | None = None,
    debug: bool | None = None,
    dry_run: bool = False,
) -> bool:
    """
    [간편충전] 기능을 사용하여 예치금을 충전합니다.

    Args:
        page: 로그인된 Playwright Page 객체
        amount: 충전 금액 (config.ALLOWED_CHARGE_AMOUNTS 중 하나)
        charge_pin: 주입할 PIN (없으면 환경변수)
        debug: 디버그 산출물 생성 여부
        dry_run: True 면 PIN 입력 직전까지만 진행하고 중단

    Returns:
        bool: 충전 요청 성공 여부
    """
    want_debug = env_bool("DEBUG", False) if debug is None else debug

    pin = _get_charge_pin(charge_pin)
    if not pin:
        log.error("CHARGE_PIN 이 설정되지 않았습니다.")
        return False

    if amount not in ALLOWED_CHARGE_AMOUNTS:
        log.error(
            "잘못된 충전 금액 %s. 허용 값: %s",
            amount,
            ALLOWED_CHARGE_AMOUNTS,
        )
        return False

    log.info("충전 페이지로 이동 중... (%s원)", f"{amount:,}")
    page.goto(CHARGE_URL, timeout=30000, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except PlaywrightTimeoutError:
        log.debug("충전 페이지 networkidle 타임아웃")
    time.sleep(2)

    _snap(page, "01_initial", want_debug)

    # 간편충전 탭
    log.info("간편충전 탭 선택")
    tab_selectors = ("text=간편충전", "#tab2", ".tab:has-text('간편충전')")
    tab_clicked = False
    for selector in tab_selectors:
        try:
            page.click(selector, timeout=3000)
            tab_clicked = True
            log.debug("간편충전 탭 클릭: %s", selector)
            break
        except PlaywrightTimeoutError:
            continue
        except Exception as exc:
            log.debug("간편충전 탭 시도 실패 (%s): %s", selector, exc)
    if not tab_clicked:
        log.warning("간편충전 탭을 찾지 못했습니다. 현재 페이지로 계속 진행")

    time.sleep(2)
    _snap(page, "02_after_tab", want_debug)

    # 금액 선택
    label = f"{amount:,}원"
    log.info("충전 금액 선택: %s", label)
    try:
        page.select_option("select#EcAmt", label=label)
    except Exception as exc:
        log.error("충전 금액 선택 실패: %s", exc)
        _snap(page, "03_amount_failed", want_debug, include_html=True)
        return False

    time.sleep(1)
    _snap(page, "03_after_amount", want_debug)

    # 충전하기 버튼
    log.info("충전하기 버튼 클릭")
    charge_selectors = (
        "button:has-text('충전하기')",
        ".btn-rec01",
        "[onclick*='charge']",
        "[onclick*='Charge']",
        "button.btn",
    )
    charge_clicked = False
    for selector in charge_selectors:
        try:
            btn = page.locator(selector)
            if btn.count() == 0:
                continue
            btn.first.click(timeout=3000)
            charge_clicked = True
            log.debug("충전 버튼 클릭: %s", selector)
            break
        except PlaywrightTimeoutError:
            continue
        except Exception as exc:
            log.debug("충전 버튼 시도 실패 (%s): %s", selector, exc)

    if not charge_clicked:
        log.error("충전 버튼을 찾을 수 없습니다.")
        _snap(page, "04_no_button", want_debug, include_html=True)
        return False

    time.sleep(3)
    _snap(page, "04_after_button", want_debug)

    # PIN 키패드 대기
    log.info("PIN 키패드 대기 중...")
    keypad_found = False
    for selector in KEYPAD_SELECTORS:
        try:
            page.wait_for_selector(selector, state="visible", timeout=5000)
            keypad_found = True
            log.debug("키패드 발견: %s", selector)
            break
        except PlaywrightTimeoutError:
            log.debug("키패드 없음: %s", selector)

    if not keypad_found:
        log.error("키패드를 찾을 수 없습니다.")
        _snap(page, "05_no_keypad", want_debug, include_html=True)
        return False

    if dry_run:
        log.warning("DRY_RUN: PIN 입력 직전에 중단합니다. (실제 충전 안 됨)")
        return False

    # 키패드 OCR
    try:
        number_map = parse_keypad(page)
    except Exception as exc:
        log.error("키패드 분석 실패: %s", exc)
        _snap(page, "06_keypad_fail", want_debug)
        return False

    required_digits = set(pin)
    missing = required_digits - set(number_map)
    if missing:
        log.error(
            "PIN 에 필요한 숫자를 인식하지 못했습니다. 누락: %s (인식됨: %s)",
            "".join(sorted(missing)),
            "".join(sorted(number_map)),
        )
        _snap(page, "06_keypad_partial", want_debug)
        return False

    log.info("PIN 입력 중... (길이 %s)", len(pin))
    for digit in pin:
        try:
            number_map[digit].click()
        except Exception as exc:
            log.error("PIN 숫자 '%s' 클릭 실패: %s", digit, exc)
            return False
        time.sleep(0.3)

    log.info("충전 처리 대기 중...")
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except PlaywrightTimeoutError:
        log.debug("충전 후 networkidle 타임아웃")
    time.sleep(2)

    _snap(page, "07_complete", want_debug)
    log.info("충전 요청 완료")
    return True


def charge_balance(
    page: Page,
    amount: int,
    charge_pin: str | None = None,
    debug: bool | None = None,
    dry_run: bool = False,
) -> bool:
    """charge_deposit 의 별칭 (통합 스크립트에서 사용)."""
    return charge_deposit(
        page, amount, charge_pin=charge_pin, debug=debug, dry_run=dry_run
    )


def run(playwright: Playwright, amount: int) -> None:
    """독립 실행용."""
    from telegram_notifier import notify_charge

    settings = load_settings()

    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    try:
        login(page, debug=settings.debug)
        success = charge_deposit(
            page, amount, debug=settings.debug, dry_run=settings.dry_run
        )
        notify_charge(amount, success)
        if success:
            log.info("충전 완료")
        else:
            log.error("충전 실패")
    except Exception as exc:
        log.exception("충전 중 오류: %s", exc)
        notify_charge(amount, False, str(exc))
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    requested = 10000
    if len(sys.argv) > 1:
        try:
            requested = int(sys.argv[1].replace(",", ""))
        except ValueError:
            log.warning("금액 파싱 실패, 기본값 %s원 사용", requested)

    with sync_playwright() as playwright:
        run(playwright, requested)
