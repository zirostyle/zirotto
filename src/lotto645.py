#!/usr/bin/env python3
"""
로또 6/45 자동 구매.

[수정 이력]
- 성공 판정 엄격화: 기존에는 마이페이지 구매내역 테이블에 행이 하나라도 있으면
  '오늘 날짜가 없어도' 성공으로 간주했습니다("그래도 최근 내역이 있으면 일단 성공").
  → 지난주 구매 기록이 이번 주 신규 구매로 오보고되었습니다.
  이제 오늘 날짜 확인 또는 명시적 완료 신호가 있어야 성공으로 판정합니다.
- 전략 번호(number_strategy) 를 수동 번호 경로로 주입할 수 있도록 확장
- 텔레그램 알림을 오케스트레이터로 이관 (중복/모순 알림 방지)
- print → logging, 디버그 산출물 DEBUG 게이팅 + debug/ 격리
- bare except 제거
"""
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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
    LOTTO645_MAX_GAMES,
    LOTTO645_PRICE_PER_GAME,
    debug_path,
    env_bool,
    load_settings,
)
from login import login

log = get_logger(__name__)

GAME_URL = "https://ol.dhlottery.co.kr/olotto/game/game645.do"
HISTORY_URL = "https://www.dhlottery.co.kr/mypage/LottoWinHistList.do"

KST = timezone(timedelta(hours=9))
WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")

NUMBER_SET_SELECTORS = (
    "#article table tbody tr",
    "#numView tbody tr",
    ".tbl_data_col tbody tr",
    ".tbl_data_col tr",
    ".select_num",
    ".num_box",
    ".list_my_number li",
    ".list_my_number tr",
)

BLOCKING_OVERLAY_SELECTORS = (
    "#pause_layer_pop_02",
    "#ele_pause_layer_pop02",
    ".pause_layer_pop",
    ".pause_bg",
)


# ---------------------------------------------------------------- 번호 파싱


def _normalize_number_set(nums: Sequence[int]) -> list[int] | None:
    """1~45 범위의 서로 다른 6개 번호만 유효 세트로 인정."""
    filtered = [int(n) for n in nums if 1 <= int(n) <= 45]
    if len(filtered) < 6:
        return None
    candidate = filtered[:6]
    if len(set(candidate)) != 6:
        return None
    return sorted(candidate)


def extract_number_sets_from_text(text: str) -> list[list[int]]:
    """문자열에서 번호 6개 세트들을 추출."""
    results: list[list[int]] = []
    for line in (text or "").splitlines():
        nums = [int(n) for n in re.findall(r"\b\d{1,2}\b", line)]
        normalized = _normalize_number_set(nums)
        if normalized:
            results.append(normalized)
    return results


def unique_number_sets(number_sets: Sequence[Sequence[int]]) -> list[list[int]]:
    """정렬 기준으로 중복 제거."""
    unique: list[list[int]] = []
    seen = set()
    for nums in number_sets:
        normalized = _normalize_number_set(nums)
        if not normalized:
            continue
        key = tuple(normalized)
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


def _extract_from_selectors(page: Page, selectors: Sequence[str], limit: int = 30) -> list[list[int]]:
    found: list[list[int]] = []
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), limit)
            for i in range(count):
                text = locator.nth(i).inner_text(timeout=1500).strip()
                found.extend(extract_number_sets_from_text(text))
        except Exception as exc:
            log.debug("번호 추출 실패 (%s): %s", selector, exc)
            continue
    return unique_number_sets(found)


def _extract_number_sets_dom(page: Page, max_sets: int = 20) -> list[list[int]]:
    """DOM 직접 스캔 fallback."""
    try:
        raw = page.evaluate(
            """
            (maxSets) => {
                const selectors = [
                    "#article table tbody tr",
                    "#numView tbody tr",
                    ".tbl_data_col tbody tr",
                    ".select_num",
                    ".num_box",
                    ".list_my_number li",
                    "[class*='num']",
                    "[class*='ball']"
                ];
                const seen = new Set();
                const output = [];
                const normalize = (arr) => {
                    const filtered = arr
                        .map(Number)
                        .filter(v => Number.isInteger(v) && v >= 1 && v <= 45);
                    if (filtered.length < 6) return null;
                    const six = filtered.slice(0, 6);
                    if (new Set(six).size !== 6) return null;
                    const key = [...six].sort((a, b) => a - b).join(",");
                    if (seen.has(key)) return null;
                    seen.add(key);
                    return six;
                };
                const collect = (el) => {
                    const direct = Array.from(el.querySelectorAll("span,em,strong,li,td,div,p"))
                        .map(n => (n.textContent || "").trim())
                        .filter(t => /^\\d{1,2}$/.test(t))
                        .map(Number);
                    const a = normalize(direct);
                    if (a) return a;
                    const txt = (el.textContent || "").replace(/\\s+/g, " ");
                    const matches = txt.match(/\\b([1-9]|[1-3]\\d|4[0-5])\\b/g) || [];
                    return normalize(matches.map(Number));
                };
                for (const selector of selectors) {
                    for (const node of Array.from(document.querySelectorAll(selector))) {
                        const picked = collect(node);
                        if (picked) {
                            output.push(picked);
                            if (output.length >= maxSets) return output;
                        }
                    }
                }
                return output;
            }
            """,
            max_sets,
        )
    except Exception as exc:
        log.debug("DOM 번호 스캔 실패: %s", exc)
        return []

    if not isinstance(raw, list):
        return []
    return unique_number_sets([item for item in raw if isinstance(item, list)])


# ---------------------------------------------------------------- 구매 가능 시간


def check_purchase_window(now: datetime | None = None) -> None:
    """
    구매 가능 시간인지 확인합니다. 불가하면 예외를 던집니다.

    - 일요일 전일 구매 불가
    - 토요일 20:00 이후 구매 불가 (추첨 시간)
    """
    now = now or datetime.now(KST)
    weekday = now.weekday()  # 0=월 ... 6=일

    log.info(
        "현재 시간: %s (KST, %s요일)",
        now.strftime("%Y-%m-%d %H:%M:%S"),
        WEEKDAY_KO[weekday],
    )

    if weekday == 6:
        raise RuntimeError("구매 불가: 일요일에는 로또를 구매할 수 없습니다.")

    if weekday == 5 and now.hour >= 20:
        raise RuntimeError("구매 불가: 추첨 시간(토요일 20:00 이후)에는 구매할 수 없습니다.")

    log.info("구매 가능 시간입니다.")


# ---------------------------------------------------------------- 결과 타입


@dataclass
class Lotto645Result:
    """로또 6/45 구매 결과."""

    success: bool = False
    games: int = 0
    total_cost: int = 0
    numbers: list[list[int]] = field(default_factory=list)
    limit_exceeded: bool = False
    skipped: bool = False
    skip_reason: str = ""
    verified_by: str = ""

    def get(self, key, default=None):
        return getattr(self, key, default)


# ---------------------------------------------------------------- 구매 절차


def _remove_blocking_overlays(page: Page) -> None:
    """클릭을 가로채는 안내 레이어를 숨깁니다."""
    try:
        page.evaluate(
            """
            (selectors) => {
                selectors.forEach(selector => {
                    document.querySelectorAll(selector).forEach(el => {
                        el.style.display = 'none';
                        el.style.visibility = 'hidden';
                        el.style.pointerEvents = 'none';
                    });
                });
            }
            """,
            list(BLOCKING_OVERLAY_SELECTORS),
        )
    except Exception as exc:
        log.debug("오버레이 제거 실패: %s", exc)


def _dismiss_alert_popup(page: Page) -> None:
    try:
        popup = page.locator("#popupLayerAlert")
        if popup.count() > 0 and popup.first.is_visible(timeout=2000):
            popup.get_by_role("button", name="확인").click(force=True, timeout=5000)
            log.debug("안내 팝업 닫음")
    except PlaywrightTimeoutError:
        pass
    except Exception as exc:
        log.debug("팝업 처리 생략: %s", exc)


def _select_manual_games(page: Page, games: Sequence[Sequence[int]]) -> None:
    """수동 번호를 마킹하고 각 게임을 확정합니다."""
    for index, game in enumerate(games, 1):
        numbers = sorted(int(n) for n in game)
        log.info("수동 게임 %s: %s", index, " ".join(f"{n:02d}" for n in numbers))
        for number in numbers:
            page.click(f'label[for="check645num{number}"]', force=True)
            time.sleep(0.1)
        page.click("#btnSelectNum")
        time.sleep(1)


def _select_auto_games(page: Page, count: int, want_debug: bool) -> None:
    """자동 번호로 count 게임을 선택합니다."""
    log.info("자동 번호 선택: %s게임", count)

    if want_debug:
        try:
            page.screenshot(path=debug_path("645_before_auto.png"))
        except Exception as exc:
            log.debug("스크린샷 저장 실패: %s", exc)

    auto_selectors = (
        "#num2",
        "input#num2",
        "input[name='num2']",
        "label[for='num2']",
        ".select_auto",
    )
    clicked = False
    for selector in auto_selectors:
        try:
            element = page.locator(selector)
            if element.count() == 0:
                continue
            element.first.click(timeout=5000, force=True)
            log.debug("자동 버튼 클릭: %s", selector)
            clicked = True
            break
        except Exception as exc:
            log.debug("자동 버튼 실패 (%s): %s", selector, exc)

    if not clicked:
        log.warning("자동 버튼을 찾지 못했습니다. 기본 선택 상태로 진행합니다.")

    time.sleep(1)

    try:
        page.select_option("#amoundApply", str(count))
    except Exception:
        fallbacks = ("select#amoundApply", "select[name*='amound']", "select[name*='amount']")
        selected = False
        for selector in fallbacks:
            try:
                page.locator(selector).first.select_option(str(count))
                selected = True
                break
            except Exception:
                continue
        if not selected:
            log.warning("게임 수 선택 요소를 찾지 못했습니다.")

    time.sleep(1)

    try:
        page.click("#btnSelectNum")
    except Exception:
        for keyword in ("선택완료", "선택 완료", "완료", "확인"):
            try:
                page.locator(f"button:has-text('{keyword}')").first.click(timeout=3000, force=True)
                break
            except Exception:
                continue
        else:
            raise RuntimeError("선택 완료 버튼을 찾을 수 없습니다.")

    time.sleep(2)
    log.info("자동 %s게임 선택 완료", count)


def _verify_payment_amount(page: Page, expected: int) -> bool:
    """표시된 결제 금액이 예상과 일치하는지 확인합니다."""
    try:
        text = page.locator("#payAmt").inner_text(timeout=5000).strip()
    except Exception as exc:
        log.warning("결제 금액을 읽을 수 없습니다: %s", exc)
        return False

    displayed = int(re.sub(r"[^0-9]", "", text) or "0")
    if displayed != expected:
        log.error("결제 금액 불일치 (예상 %s, 표시 %s)", f"{expected:,}", f"{displayed:,}")
        return False

    log.info("결제 금액 확인: %s원", f"{displayed:,}")
    return True


def _detect_success_signal(page: Page) -> str:
    """
    구매 완료를 나타내는 화면 신호를 찾습니다.
    발견하면 근거 문자열, 없으면 빈 문자열.
    """
    indicators = (
        "text=/구매.*완료/",
        "text=/구매.*성공/",
        ".complete",
        "#successMessage",
    )
    for selector in indicators:
        try:
            if page.locator(selector).first.is_visible(timeout=2000):
                return f"화면 완료 메시지({selector})"
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    try:
        url = page.url.lower()
        if "confirm" in url or "complete" in url:
            return f"완료 페이지 이동({page.url})"
    except Exception:
        pass

    return ""


def _verify_in_history(page: Page, want_debug: bool) -> tuple:
    """
    마이페이지 구매내역에서 '오늘' 구매를 확인합니다.

    [수정] 기존에는 테이블에 행이 있기만 하면 성공으로 간주했습니다.
    이제 오늘 날짜가 실제로 포함되어야 확인으로 인정합니다.

    Returns:
        (오늘_구매_확인됨: bool, 추출된_번호: List[List[int]], 근거: str)
    """
    log.info("마이페이지 구매내역 검증 중...")

    try:
        page.goto(HISTORY_URL, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=20000)
        time.sleep(2)
    except Exception as exc:
        log.warning("구매내역 페이지 이동 실패: %s", exc)
        return (False, [], "")

    if want_debug:
        try:
            page.screenshot(path=debug_path("645_history.png"))
            with open(debug_path("645_history.html"), "w", encoding="utf-8") as fp:
                fp.write(page.content())
        except Exception as exc:
            log.debug("구매내역 디버그 저장 실패: %s", exc)

    try:
        first_row = page.locator("table tbody tr").first
        if first_row.count() == 0:
            log.warning("구매내역 테이블에 행이 없습니다.")
            return (False, [], "")
        row_text = first_row.inner_text(timeout=5000)
    except Exception as exc:
        log.warning("구매내역 첫 행을 읽을 수 없습니다: %s", exc)
        return (False, [], "")

    log.debug("구매내역 첫 행: %s", row_text[:200].replace("\n", " | "))

    today = datetime.now(KST)
    today_formats = (
        today.strftime("%Y-%m-%d"),
        today.strftime("%Y.%m.%d"),
        today.strftime("%Y/%m/%d"),
    )

    today_found = any(fmt in row_text for fmt in today_formats)

    numbers = extract_number_sets_from_text(row_text)

    if not today_found:
        log.warning(
            "구매내역 최신 행에 오늘 날짜(%s)가 없습니다. "
            "이번 회차 신규 구매로 확정할 수 없습니다.",
            today_formats[0],
        )
        return (False, numbers, "")

    log.info("오늘 구매 내역 확인됨")

    # 상세 번호 추출 시도
    try:
        detail_btn = first_row.locator("a, button, .btn").first
        if detail_btn.count() > 0:
            detail_btn.click(timeout=3000)
            time.sleep(2)
            detail = _extract_from_selectors(
                page, (".win_num", ".num", "[class*='number']", "table tbody tr", "ul li"), limit=60
            )
            if not detail:
                detail = _extract_number_sets_dom(page, max_sets=10)
            if detail:
                numbers = unique_number_sets(list(numbers) + detail)
    except Exception as exc:
        log.debug("상세 번호 추출 실패: %s", exc)

    return (True, numbers, f"마이페이지 구매내역({today_formats[0]})")


def purchase_lotto645(
    page: Page,
    auto_games: int = 0,
    manual_numbers: Sequence[Sequence[int]] | None = None,
    debug: bool | None = None,
    dry_run: bool = False,
) -> Lotto645Result:
    """
    로또 6/45 를 구매합니다 (이미 로그인된 페이지 사용).

    Args:
        page: 로그인된 Page
        auto_games: 자동 구매 게임 수
        manual_numbers: 수동/전략 번호 목록 (예: [[1,2,3,4,5,6], ...])
        debug: 디버그 산출물 생성 여부
        dry_run: 구매 버튼 클릭 직전까지만 진행

    Returns:
        Lotto645Result
    """
    want_debug = env_bool("DEBUG", False) if debug is None else debug
    manual = unique_number_sets(manual_numbers or [])

    total_games = auto_games + len(manual)
    if total_games == 0:
        log.warning("구매할 게임이 없습니다.")
        return Lotto645Result(success=False, skipped=True, skip_reason="구매할 게임 없음")

    if total_games > LOTTO645_MAX_GAMES:
        raise ValueError(
            f"총 게임 수 {total_games}개가 한도({LOTTO645_MAX_GAMES})를 초과합니다."
        )

    check_purchase_window()

    expected_cost = total_games * LOTTO645_PRICE_PER_GAME

    # 게임 페이지 이동 (재시도)
    log.info("로또 6/45 페이지 이동 중...")
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            if attempt > 0:
                log.info("페이지 이동 재시도 %s/2", attempt)
                time.sleep(10)
            page.goto(GAME_URL, timeout=90000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except PlaywrightTimeoutError:
                log.debug("networkidle 타임아웃, 계속 진행")
            time.sleep(2)
            log.info("페이지 로드 완료")
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            log.warning("페이지 로드 실패: %s", str(exc)[:120])

    if last_error is not None:
        raise RuntimeError(f"로또 6/45 페이지 로드 실패: {last_error}")

    _remove_blocking_overlays(page)
    _dismiss_alert_popup(page)

    # 번호 선택
    if manual:
        log.info("수동/전략 번호 선택 (%s게임)", len(manual))
        _select_manual_games(page, manual)

    if auto_games > 0:
        _select_auto_games(page, auto_games, want_debug)

    # 결제 금액 검증
    time.sleep(1)
    if not _verify_payment_amount(page, expected_cost):
        return Lotto645Result(
            success=False, skipped=True, skip_reason="결제 금액 불일치로 구매 중단"
        )

    # 구매 전 화면에서 번호 확보
    screen_numbers = _extract_from_selectors(page, NUMBER_SET_SELECTORS, limit=30)
    if not screen_numbers:
        screen_numbers = _extract_number_sets_dom(page, max_sets=max(total_games, 10))
    if manual:
        screen_numbers = unique_number_sets(list(manual) + list(screen_numbers))
    if screen_numbers:
        log.info("구매 전 화면 번호 %s세트 확보", len(screen_numbers))

    if dry_run:
        log.warning("DRY_RUN: 구매 버튼 클릭 직전에 중단합니다. (실제 구매 안 됨)")
        return Lotto645Result(
            success=False,
            games=0,
            total_cost=0,
            numbers=screen_numbers,
            skipped=True,
            skip_reason="dry_run",
        )

    # 구매 실행
    log.info("구매 버튼 클릭")
    page.click("#btnBuy")
    log.info("구매 확인 팝업 처리")
    page.click("#popupLayerConfirm input[value='확인']")

    log.info("구매 처리 대기 중...")
    time.sleep(5)

    # 한도 초과 팝업
    limit_exceeded = False
    try:
        limit_popup = page.locator("#recommend720Plus")
        if limit_popup.count() > 0 and limit_popup.first.is_visible(timeout=2000):
            limit_exceeded = True
            log.warning("주간 구매 한도 초과 팝업 감지")
            try:
                content = limit_popup.locator(".cont1").inner_text(timeout=2000)
                log.warning("팝업 내용: %s", content.strip()[:200])
            except Exception:
                pass
    except PlaywrightTimeoutError:
        pass
    except Exception as exc:
        log.debug("한도 팝업 확인 생략: %s", exc)

    screen_signal = _detect_success_signal(page)
    if screen_signal:
        log.info("구매 완료 신호: %s", screen_signal)
    elif want_debug:
        try:
            page.screenshot(path=debug_path("645_after_purchase.png"))
            with open(debug_path("645_after_purchase.html"), "w", encoding="utf-8") as fp:
                fp.write(page.content())
            log.warning("완료 신호 없음 → 디버그 산출물 저장")
        except Exception as exc:
            log.debug("디버그 저장 실패: %s", exc)

    # 마이페이지 검증 (권위 있는 확인)
    time.sleep(3)
    today_confirmed, history_numbers, history_evidence = _verify_in_history(page, want_debug)

    final_numbers = unique_number_sets(list(history_numbers) + list(screen_numbers))

    # 성공 판정: 오늘 구매내역 확인 또는 명시적 화면 완료 신호
    success = today_confirmed or bool(screen_signal)

    evidence_parts = [part for part in (history_evidence, screen_signal) if part]

    if success:
        log.info(
            "로또 6/45 구매 완료 (%s게임, %s원) | 근거: %s",
            total_games,
            f"{expected_cost:,}",
            " + ".join(evidence_parts),
        )
        if limit_exceeded:
            log.info("참고: 한도 초과 팝업이 표시되었으나 구매는 완료되었습니다.")
        return Lotto645Result(
            success=True,
            games=total_games,
            total_cost=expected_cost,
            numbers=final_numbers,
            limit_exceeded=limit_exceeded,
            verified_by=" + ".join(evidence_parts),
        )

    if limit_exceeded:
        log.warning("주간 구매 한도 초과로 구매되지 않았습니다.")
        return Lotto645Result(
            success=False,
            games=0,
            total_cost=0,
            numbers=[],
            limit_exceeded=True,
            skip_reason="주간 구매 한도 초과",
        )

    log.error(
        "구매 완료를 확인할 수 없습니다. "
        "마이페이지에서 직접 확인하세요: %s",
        HISTORY_URL,
    )
    return Lotto645Result(
        success=False,
        games=0,
        total_cost=0,
        numbers=final_numbers,
        skip_reason="구매 완료 미확인",
    )


# ---------------------------------------------------------------- 독립 실행


def parse_arguments() -> tuple:
    """
    커맨드라인 인자 파싱.

    사용법:
      lotto645.py 3000            → 자동 3게임
      lotto645.py 1 2 3 4 5 6     → 수동 1게임
      (인자 없음)                  → .env 설정 사용
    """
    settings = load_settings()

    args = sys.argv[1:]
    if not args:
        return settings.auto_games, settings.manual_numbers

    if len(args) == 1:
        try:
            amount = int(args[0].replace(",", ""))
        except ValueError:
            log.error("금액 형식이 잘못되었습니다: %s", args[0])
            sys.exit(1)

        valid = [i * LOTTO645_PRICE_PER_GAME for i in range(1, LOTTO645_MAX_GAMES + 1)]
        if amount not in valid:
            log.error("잘못된 금액 %s. 허용: %s", amount, valid)
            sys.exit(1)
        return amount // LOTTO645_PRICE_PER_GAME, []

    if len(args) == 6:
        try:
            numbers = [int(a) for a in args]
        except ValueError:
            log.error("번호는 모두 숫자여야 합니다: %s", args)
            sys.exit(1)
        if not all(1 <= n <= 45 for n in numbers):
            log.error("번호는 1~45 범위여야 합니다: %s", numbers)
            sys.exit(1)
        if len(set(numbers)) != 6:
            log.error("번호가 중복되었습니다: %s", numbers)
            sys.exit(1)
        return 0, [sorted(numbers)]

    log.error(
        "사용법:\n"
        "  lotto645.py [금액]              # 자동 (1000~5000, 1000 단위)\n"
        "  lotto645.py N1 N2 N3 N4 N5 N6   # 수동 (1~45, 중복 없음)"
    )
    sys.exit(1)


def run(playwright: Playwright, auto_games: int, manual_numbers: list) -> None:
    """독립 실행용."""
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
        purchase_lotto645(
            page,
            auto_games,
            manual_numbers,
            debug=settings.debug,
            dry_run=settings.dry_run,
        )
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    parsed_auto, parsed_manual = parse_arguments()
    with sync_playwright() as playwright:
        run(playwright, parsed_auto, parsed_manual)
