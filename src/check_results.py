#!/usr/bin/env python3
"""
로또 당첨 결과 확인.

동행복권 공개 JSON 엔드포인트에서 당첨번호를 조회하고,
마이페이지 구매내역과 대조하여 게임별 일치 번호/등수를 계산합니다.

[수정 이력]
- 회차를 날짜 계산으로만 추정하던 방식 → 실제 API 응답으로 최신 회차를 확정
- bare except 로 HTTP/JSON 오류를 은폐하던 부분 → 명시적 예외 + 로깅
- 당첨 결과를 '등수: 장수' 로 집계하던 값을 금액처럼 표시했던 버그 수정
  (이제 게임별 상세 정보를 그대로 알림에 전달)
"""
import datetime
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

import requests
from playwright.sync_api import Playwright, sync_playwright

from applog import get_logger, section
from config import debug_path, load_settings
from login import login
from telegram_notifier import notify_lotto_result

log = get_logger(__name__)

LOTTO_API = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={}"
PURCHASE_HISTORY_URL = "https://www.dhlottery.co.kr/mypage/LottoWinHistList.do"

FIRST_DRAW_DATE = datetime.date(2002, 12, 7)
API_TIMEOUT = 10

# 최신 회차 탐색 시 위/아래로 살펴볼 최대 범위
SEARCH_DOWN_LIMIT = 8
SEARCH_UP_LIMIT = 8


# ---------------------------------------------------------------- 당첨번호 조회


@dataclass
class DrawResult:
    """한 회차의 추첨 결과."""

    round_num: int
    winning_numbers: list[int]
    bonus: int
    draw_date: str


def _fetch_round(round_num: int) -> DrawResult | None:
    """
    특정 회차를 조회합니다. 존재하지 않으면 None.
    네트워크/파싱 오류는 로그를 남기고 None 을 반환합니다.
    """
    if round_num < 1:
        return None

    url = LOTTO_API.format(round_num)
    try:
        response = requests.get(url, timeout=API_TIMEOUT)
    except requests.RequestException as exc:
        log.warning("%s회 조회 실패 (네트워크): %s", round_num, exc)
        return None

    if response.status_code != 200:
        log.warning("%s회 조회 실패 (HTTP %s)", round_num, response.status_code)
        return None

    try:
        data = response.json()
    except ValueError as exc:
        log.warning("%s회 응답 파싱 실패: %s", round_num, exc)
        return None

    if data.get("returnValue") != "success":
        # 아직 추첨되지 않은 회차 — 정상적인 경우
        log.debug("%s회는 아직 추첨되지 않았습니다.", round_num)
        return None

    try:
        numbers = [
            int(data["drwtNo1"]),
            int(data["drwtNo2"]),
            int(data["drwtNo3"]),
            int(data["drwtNo4"]),
            int(data["drwtNo5"]),
            int(data["drwtNo6"]),
        ]
        bonus = int(data["bnusNo"])
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("%s회 응답 형식 오류: %s", round_num, exc)
        return None

    return DrawResult(
        round_num=int(data.get("drwNo", round_num)),
        winning_numbers=sorted(numbers),
        bonus=bonus,
        draw_date=str(data.get("drwNoDate", "")),
    )


def estimate_round(today: datetime.date | None = None) -> int:
    """날짜 기준으로 회차를 추정합니다 (탐색 시작점으로만 사용)."""
    today = today or datetime.date.today()
    weeks = (today - FIRST_DRAW_DATE).days // 7
    return max(1, weeks + 1)


def get_latest_draw() -> DrawResult:
    """
    실제 API 응답으로 최신 추첨 회차를 확정합니다.

    날짜 추정치를 시작점으로 삼되, 추정이 틀려도
    아래로 내려가며 유효한 회차를 찾고, 그 뒤 위로 올라가며
    더 최신 회차가 있는지 확인합니다.
    """
    start = estimate_round()
    log.debug("회차 추정 시작점: %s", start)

    found: DrawResult | None = None

    # 1. 유효한 회차를 하나 찾는다 (추정치에서 아래로)
    for offset in range(0, SEARCH_DOWN_LIMIT + 1):
        candidate = _fetch_round(start - offset)
        if candidate:
            found = candidate
            break

    if not found:
        raise RuntimeError(
            f"최신 당첨번호를 가져올 수 없습니다. "
            f"(추정 {start}회 기준 아래로 {SEARCH_DOWN_LIMIT}회까지 탐색)"
        )

    # 2. 더 최신 회차가 있는지 위로 확인
    for _ in range(SEARCH_UP_LIMIT):
        nxt = _fetch_round(found.round_num + 1)
        if not nxt:
            break
        found = nxt

    log.info(
        "최신 회차 확정: %s회 (%s) — %s + 보너스 %02d",
        found.round_num,
        found.draw_date,
        " ".join(f"{n:02d}" for n in found.winning_numbers),
        found.bonus,
    )
    return found


# 하위 호환용 별칭 (기존 호출부 유지)
def get_latest_lotto_winning_numbers() -> dict:
    """기존 dict 형태 반환 (하위 호환)."""
    draw = get_latest_draw()
    return {
        "round": draw.round_num,
        "winning_numbers": draw.winning_numbers,
        "bonus": draw.bonus,
        "draw_date": draw.draw_date,
    }


# ---------------------------------------------------------------- 당첨 판정

RANK_BY_MATCH = {
    (6, False): 1,
    (5, True): 2,
    (5, False): 3,
    (4, False): 4,
    (4, True): 4,
    (3, False): 5,
    (3, True): 5,
}


@dataclass
class TicketResult:
    """한 게임의 당첨 판정 결과."""

    numbers: list[int]
    matched: list[int] = field(default_factory=list)
    match_count: int = 0
    bonus_matched: bool = False
    rank: int | None = None

    def as_dict(self) -> dict:
        return {
            "numbers": self.numbers,
            "matched": self.matched,
            "match_count": self.match_count,
            "bonus_matched": self.bonus_matched,
            "rank": self.rank,
        }


def evaluate_ticket(
    my_numbers: Sequence[int],
    winning_numbers: Sequence[int],
    bonus: int,
) -> TicketResult:
    """
    한 게임의 당첨 여부를 판정하고 일치 번호까지 반환합니다.
    """
    my_sorted = sorted(int(n) for n in my_numbers)
    winning_set = {int(n) for n in winning_numbers}

    matched = sorted(n for n in my_sorted if n in winning_set)
    match_count = len(matched)
    bonus_matched = int(bonus) in set(my_sorted)

    rank = RANK_BY_MATCH.get((match_count, bonus_matched))
    # 6개 일치는 보너스 여부와 무관하게 1등
    if match_count == 6:
        rank = 1

    return TicketResult(
        numbers=my_sorted,
        matched=matched,
        match_count=match_count,
        bonus_matched=bonus_matched,
        rank=rank,
    )


def check_winning(my_numbers: list, winning_numbers: list, bonus: int) -> tuple:
    """
    하위 호환용: (등수문자열 또는 None, 일치개수) 반환.
    신규 코드는 evaluate_ticket() 을 사용하세요.
    """
    result = evaluate_ticket(my_numbers, winning_numbers, bonus)
    label = f"{result.rank}등" if result.rank else None
    return (label, result.match_count)


# ---------------------------------------------------------------- 구매내역 조회


def _normalize_number_set(nums: Sequence[int]) -> list[int] | None:
    """1~45 범위의 서로 다른 6개 번호만 유효한 세트로 인정합니다."""
    filtered = [int(n) for n in nums if 1 <= int(n) <= 45]
    if len(filtered) < 6:
        return None
    candidate = filtered[:6]
    if len(set(candidate)) != 6:
        return None
    return sorted(candidate)


def extract_number_sets(text: str) -> list[list[int]]:
    """텍스트에서 로또 번호 6개 세트들을 추출합니다."""
    results: list[list[int]] = []
    seen = set()
    for line in (text or "").splitlines():
        nums = [int(n) for n in re.findall(r"\b\d{1,2}\b", line)]
        normalized = _normalize_number_set(nums)
        if not normalized:
            continue
        key = tuple(normalized)
        if key in seen:
            continue
        seen.add(key)
        results.append(normalized)
    return results


@dataclass
class PurchaseRecord:
    """마이페이지에서 읽은 한 회차의 구매 내역."""

    round_num: int
    numbers: list[list[int]]
    date: str = ""


def get_my_lotto_purchases(page, debug: bool = False) -> list[PurchaseRecord]:
    """
    마이페이지에서 최근 로또 구매 내역을 조회합니다.

    실패 시 빈 리스트를 반환하지만, 반드시 경고 로그를 남깁니다.
    (기존에는 조용히 [] 를 반환해 '구매 내역 없음' 으로 오보고되었습니다)
    """
    log.info("구매 내역 조회 중...")
    try:
        page.goto(PURCHASE_HISTORY_URL, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception as exc:
        log.warning("구매 내역 페이지 이동 실패: %s", exc)
        return []

    if debug:
        try:
            page.screenshot(path=debug_path("history.png"))
            with open(debug_path("history.html"), "w", encoding="utf-8") as fp:
                fp.write(page.content())
            log.debug("구매 내역 디버그 산출물 저장 완료")
        except Exception as exc:
            log.debug("구매 내역 디버그 저장 실패: %s", exc)

    records: list[PurchaseRecord] = []

    try:
        rows = page.locator("table tbody tr").all()
    except Exception as exc:
        log.warning("구매 내역 테이블을 읽을 수 없습니다: %s", exc)
        return []

    if not rows:
        log.warning("구매 내역 테이블에 행이 없습니다. (페이지 구조 변경 가능성)")
        return []

    for index, row in enumerate(rows[:10]):
        try:
            cells = row.locator("td")
            cell_count = cells.count()
            if cell_count == 0:
                continue

            round_text = cells.nth(0).inner_text(timeout=3000)
            round_match = re.search(r"(\d+)", round_text)
            if not round_match:
                continue
            round_num = int(round_match.group(1))

            date_text = ""
            if cell_count > 1:
                date_text = cells.nth(1).inner_text(timeout=3000).strip()

            numbers_text = ""
            if cell_count > 2:
                numbers_text = cells.nth(2).inner_text(timeout=3000)

            number_sets = extract_number_sets(numbers_text)
            if not number_sets:
                log.debug("%s행(%s회): 번호를 추출하지 못했습니다.", index, round_num)
                continue

            records.append(
                PurchaseRecord(round_num=round_num, numbers=number_sets, date=date_text)
            )
        except Exception as exc:
            log.debug("구매 내역 %s행 파싱 실패: %s", index, exc)
            continue

    if not records:
        log.warning(
            "구매 내역을 파싱하지 못했습니다. 테이블 행은 %s개 발견되었으나 "
            "번호 추출에 모두 실패했습니다. (셀렉터/구조 변경 가능성)",
            len(rows),
        )
    else:
        log.info("구매 내역 %s개 회차 확인", len(records))

    return records


# ---------------------------------------------------------------- 결과 알림


def build_and_notify(
    draw: DrawResult,
    purchases: Sequence[PurchaseRecord],
    purchase_lookup_failed: bool = False,
) -> list[TicketResult]:
    """
    해당 회차 구매내역을 대조하여 알림을 전송하고 결과 목록을 반환합니다.
    """
    target = next((p for p in purchases if p.round_num == draw.round_num), None)

    if not target:
        if purchase_lookup_failed:
            reason = (
                "구매 내역을 조회할 수 없었습니다. "
                "마이페이지에서 직접 확인해주세요."
            )
        else:
            reason = f"{draw.round_num}회 구매 내역이 없습니다."
        log.warning(reason)
        notify_lotto_result(
            draw.round_num,
            draw.winning_numbers,
            draw.bonus,
            tickets=None,
            draw_date=draw.draw_date,
            no_purchase_reason=reason,
        )
        return []

    results = [
        evaluate_ticket(nums, draw.winning_numbers, draw.bonus) for nums in target.numbers
    ]

    log.info("%s회 구매 번호 %s게임 대조 완료", draw.round_num, len(results))
    for i, result in enumerate(results, 1):
        matched_text = " ".join(f"{n:02d}" for n in result.matched) or "-"
        rank_text = f"{result.rank}등 당첨!" if result.rank else "미당첨"
        log.info(
            "  %s. %s | 일치 %s개 (%s)%s | %s",
            i,
            " ".join(f"{n:02d}" for n in result.numbers),
            result.match_count,
            matched_text,
            " +보너스" if result.bonus_matched else "",
            rank_text,
        )

    notify_lotto_result(
        draw.round_num,
        draw.winning_numbers,
        draw.bonus,
        tickets=[r.as_dict() for r in results],
        draw_date=draw.draw_date,
    )

    winners = [r for r in results if r.rank]
    if winners:
        summary: dict[int, int] = {}
        for r in winners:
            summary[r.rank] = summary.get(r.rank, 0) + 1
        log.info("당첨 요약: %s", ", ".join(f"{k}등 {v}장" for k, v in sorted(summary.items())))
    else:
        log.info("당첨 내역 없음")

    return results


# ---------------------------------------------------------------- 실행


def run(playwright: Playwright) -> None:
    """당첨 결과 확인 메인 함수."""
    settings = load_settings()
    section(log, "로또 당첨 결과 확인")

    try:
        draw = get_latest_draw()
    except Exception as exc:
        log.error("당첨 번호 조회 실패: %s", exc)
        return

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
        purchases = get_my_lotto_purchases(page, debug=settings.debug)
        build_and_notify(draw, purchases, purchase_lookup_failed=not purchases)
    except Exception as exc:
        log.exception("당첨 확인 중 오류: %s", exc)
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
