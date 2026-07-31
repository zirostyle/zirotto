#!/usr/bin/env python3
"""연금복권 720+ 최신 구매 회차의 공식 당첨 판정을 Telegram으로 알립니다.

로그인된 Playwright 브라우저 컨텍스트의 APIRequestContext를 사용해
동행복권 마이페이지 원장과 상세 구매내역을 조회합니다. 당첨 등수와 금액은
직접 추정하지 않고 동행복권이 확정한 값을 그대로 사용합니다.
"""
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from datetime import time as dt_time

from playwright.sync_api import Page, Playwright, sync_playwright

from applog import get_logger, section
from config import load_settings
from login import login
from telegram_notifier import notify_error, notify_lotto720_result

log = get_logger(__name__)

KST = timezone(timedelta(hours=9))
LEDGER_URL = "https://www.dhlottery.co.kr/mypage/selectMyLotteryledger.do"
DETAIL_URL = "https://www.dhlottery.co.kr/mypage/lottery720select.do"
REQUEST_TIMEOUT_MS = 30_000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class Lotto720TicketResult:
    """동행복권이 판정한 720+ 한 장의 결과."""

    group: int | None
    number: str
    rank: int | None = None

    def as_dict(self) -> dict:
        return {"group": self.group, "number": self.number, "rank": self.rank}


@dataclass
class Lotto720DrawResult:
    """마이페이지에서 조회한 한 회차의 720+ 구매 및 당첨 결과."""

    round_num: int
    purchase_date: str = ""
    draw_date: str = ""
    prize_amount: int = 0
    tickets: list[Lotto720TicketResult] = field(default_factory=list)


def _parse_int(value, default: int = 0) -> int:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return int(digits) if digits else default


def _parse_round(value) -> int:
    round_num = _parse_int(value)
    if round_num < 1:
        raise RuntimeError(f"720+ 회차를 해석할 수 없습니다: {value!r}")
    return round_num


def _parse_ticket_info(value: str) -> tuple[int | None, str]:
    """`1:123456`, `1조 123456` 등 사이트 표기를 정규화합니다."""
    text = str(value or "").strip()
    match = re.search(r"([1-5])\s*(?:조|:)\s*([0-9]{6})", text)
    if match:
        return int(match.group(1)), match.group(2)

    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) >= 7 and digits[0] in "12345":
        return int(digits[0]), digits[-6:]
    if len(digits) >= 6:
        return None, digits[-6:]
    return None, text or "번호 확인 불가"


def _parse_rank(value) -> int | None:
    rank = _parse_int(value)
    return rank if 1 <= rank <= 7 else None


def _date_prefix(value) -> date | None:
    match = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", str(value or ""))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _current_week_monday(today: date) -> date:
    return today - timedelta(days=today.weekday())


def _request_json(page: Page, url: str, params: dict) -> dict:
    response = page.context.request.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT_MS,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.dhlottery.co.kr/mypage/home",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    if not response.ok:
        raise RuntimeError(f"720+ 마이페이지 API 오류: HTTP {response.status}")
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError("720+ 마이페이지 응답이 JSON이 아닙니다.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("720+ 마이페이지 응답 형식이 올바르지 않습니다.")
    return payload


def get_latest_lotto720_result(
    page: Page,
    today: date | None = None,
    now: datetime | None = None,
) -> Lotto720DrawResult:
    """이번 주 720+ 구매내역과 동행복권의 공식 당첨 판정을 조회합니다."""
    now_kst = (now or datetime.now(KST)).astimezone(KST)
    today = today or now_kst.date()
    search_start = today - timedelta(days=35)

    payload = _request_json(
        page,
        LEDGER_URL,
        {
            "srchStrDt": search_start.isoformat(),
            "srchEndDt": today.isoformat(),
            "ltGdsCd": "LP72",
            "pageNum": 1,
            "recordCountPerPage": 100,
        },
    )
    data = payload.get("data", payload)
    items = data.get("list", []) if isinstance(data, dict) else []
    if not items:
        raise RuntimeError("최근 35일 내 연금복권 720+ 구매내역이 없습니다.")

    this_monday = _current_week_monday(today)
    expected_draw_date = this_monday + timedelta(days=3)
    draw_at = datetime.combine(expected_draw_date, dt_time(19, 5), tzinfo=KST)
    if today < expected_draw_date or (
        today == now_kst.date() and now_kst < draw_at
    ):
        raise RuntimeError(
            "이번 주 720+는 아직 추첨 전입니다. "
            f"정기 추첨: {draw_at.strftime('%Y-%m-%d %H:%M KST')}"
        )
    current_week_items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        purchased_on = _date_prefix(item.get("eltOrdrDt"))
        if purchased_on and this_monday <= purchased_on <= today:
            current_week_items.append(item)

    if not current_week_items:
        latest_date = str(items[0].get("eltOrdrDt") or "")
        raise RuntimeError(
            f"이번 주 720+ 구매내역이 없습니다. 최근 구매일: {latest_date or '확인 불가'}"
        )

    target_round = max(
        _parse_round(item.get("ltEpsdView") or item.get("ltEpsd"))
        for item in current_week_items
    )
    round_items = [
        item
        for item in current_week_items
        if _parse_round(item.get("ltEpsdView") or item.get("ltEpsd"))
        == target_round
    ]

    tickets = []
    prize_amount = 0
    purchase_dates = []
    draw_dates = []
    seen_orders = set()

    for item in round_items:
        reflected_date = str(item.get("epsdRflDt") or "")
        reflected_on = _date_prefix(reflected_date)
        if reflected_on != expected_draw_date:
            raise RuntimeError(
                f"720+ {target_round}회 결과가 아직 공식 반영되지 않았습니다. "
                f"예상 추첨일: {expected_draw_date}, 반영일: {reflected_date or '없음'}"
            )

        order_no = item.get("ntslOrdrNo")
        if not order_no or order_no in seen_orders:
            if not order_no:
                raise RuntimeError(
                    f"720+ {target_round}회 상세조회 주문번호가 없습니다."
                )
            continue
        seen_orders.add(order_no)

        detail_payload = _request_json(page, DETAIL_URL, {"ntslOrdrNo": order_no})
        detail_data = detail_payload.get("data", detail_payload)
        detail_items = (
            detail_data.get("list", []) if isinstance(detail_data, dict) else []
        )
        if not detail_items:
            raise RuntimeError(
                f"720+ {target_round}회 주문 {order_no}의 구매번호 상세내역이 없습니다."
            )

        for detail in detail_items:
            group, number = _parse_ticket_info(detail.get("ltGmInfoCn", ""))
            tickets.append(
                Lotto720TicketResult(
                    group=group,
                    number=number,
                    rank=_parse_rank(detail.get("wnRnk")),
                )
            )

        prize_amount += _parse_int(item.get("ltWnAmt"))
        purchase_dates.append(str(item.get("eltOrdrDt") or ""))
        draw_dates.append(reflected_date)

    if not tickets:
        raise RuntimeError(f"720+ {target_round}회 구매번호를 한 장도 확인하지 못했습니다.")

    result = Lotto720DrawResult(
        round_num=target_round,
        purchase_date=", ".join(sorted(set(filter(None, purchase_dates)))),
        draw_date=", ".join(sorted(set(filter(None, draw_dates)))),
        prize_amount=prize_amount,
        tickets=tickets,
    )
    log.info(
        "720+ %s회 결과 조회: %s장, 당첨금 %s원",
        result.round_num,
        len(result.tickets),
        f"{result.prize_amount:,}",
    )
    return result


def run(playwright: Playwright) -> bool:
    """720+ 결과 확인 메인 함수."""
    settings = load_settings()
    section(log, "연금복권 720+ 당첨 결과 확인")

    browser = None
    context = None
    try:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=USER_AGENT,
        )
        page = context.new_page()
        login(
            page,
            user_id=settings.user_id,
            passwd=settings.passwd,
            debug=settings.debug,
        )
        result = get_latest_lotto720_result(page)
        sent = notify_lotto720_result(
            result.round_num,
            tickets=[ticket.as_dict() for ticket in result.tickets],
            prize_amount=result.prize_amount,
            purchase_date=result.purchase_date,
            draw_date=result.draw_date,
        )
        if not sent:
            raise RuntimeError("720+ 결과 Telegram 알림 전송에 실패했습니다.")
        return True
    except Exception as exc:
        log.exception("720+ 당첨 확인 중 오류: %s", exc)
        notify_error(f"720+ 당첨 결과 확인 실패: {type(exc).__name__}: {exc}")
        return False
    finally:
        if context is not None:
            context.close()
        if browser is not None:
            browser.close()


def main() -> int:
    with sync_playwright() as playwright:
        return 0 if run(playwright) else 1


if __name__ == "__main__":
    sys.exit(main())
