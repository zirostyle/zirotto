#!/usr/bin/env python3
"""
연금복권 720+ 자동 구매.

================================================================
[재작성 이유 — 기존 구현의 확인된 결함]
================================================================

1. FrameLocator 에는 .evaluate() 메서드가 없습니다.
   기존 _get_frame() 은 iframe 이 있으면 page.frame_locator("#ifrm_tab") 을
   반환했는데, 이는 FrameLocator 객체입니다.
   그런데 _click_keyword() 와 _dump_interactive_labels() 는
   target.evaluate(...) 를 호출합니다.
   → 데스크톱(iframe) 경로에서 모든 fallback 이 AttributeError 로 즉사.
   즉 "버튼을 못 찾으면 키워드로 찾는다"는 안전망이 아예 동작하지 않았습니다.

   수정: iframe 의 ElementHandle.content_frame() 으로 실제 Frame 객체를
   얻습니다. Frame 은 locator() 와 evaluate() 를 모두 지원합니다.

2. 셀렉터 이중 스코핑.
   기존 코드는 number_target = frame.locator("#popup4") 로 스코프를 좁힌 뒤
   _click_first(number_target, ["#popup4 .btn_wht.xsmall[onclick*='doAuto']", ...])
   를 호출했습니다. 이는 "#popup4 안에서 다시 #popup4 를 찾아라"가 되어
   절대 매칭되지 않습니다.
   → 가장 정확했을 셀렉터가 항상 실패하고 뒤쪽 광범위 셀렉터로 넘어갔습니다.

   수정: 스코프를 좁히지 않고 프레임 기준 절대 셀렉터를 사용합니다.

3. _navigate_to_lotto720() 의 for 루프가 첫 iteration 에서
   else: return frame 으로 즉시 반환됩니다.
   → 두 번째 데스크톱 URL 은 절대 시도되지 않고,
     그 뒤의 print("모바일 리다이렉트 감지...") 는 도달 불가 코드였습니다.

4. dialog 실패 판정 키워드가 과도하게 넓었습니다.
   "없습니다", "선택해" 같은 부분 문자열은 정상 안내 메시지에도 등장할 수 있어
   성공한 구매를 실패로 처리할 수 있었습니다.

5. 반환값이 games=5, numbers="자동 선택" 로 하드코딩되어
   실제 구매한 조/번호를 알 수 없었습니다.

================================================================
[검증 한계 — 반드시 인지할 것]
================================================================
이 파일의 수정은 코드 자체의 결함(위 1~5)을 제거한 것입니다.
동행복권 실제 페이지의 DOM 구조는 이 개발 환경에서 접근할 수 없어
셀렉터가 현재 사이트와 일치하는지는 검증하지 못했습니다.

그래서 실패 시 진단 정보를 대폭 강화했습니다:
DEBUG=1 로 실행하면 프레임 HTML, 스크린샷, 클릭 가능한 요소 전체 목록
(id/class/onclick 포함)을 debug/ 에 저장합니다.
셀렉터가 바뀌었다면 다음 실행 로그에서 정확히 무엇이 바뀌었는지 확인 가능합니다.
"""
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Union

from playwright.sync_api import (
    Frame,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from applog import get_logger
from config import PER_720_PURCHASE_AMOUNT, debug_path, env_bool, env_int, load_settings
from login import login

log = get_logger(__name__)

# Page 와 Frame 둘 다 locator() / evaluate() 를 지원합니다.
GameContext = Union[Page, Frame]  # noqa: UP007 - 런타임 isinstance 용도로 Union 유지

DESKTOP_URLS = (
    "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72",
    "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72&kind=1",
)

MOBILE_URLS = (
    "https://el.dhlottery.co.kr/game_mobile/pension720/game.jsp",
    "https://m.dhlottery.co.kr/game_mobile/pension720/game.jsp",
)

IFRAME_SELECTOR = "#ifrm_tab"

# 구매 결과 문구 / 금액 / 잔액 셀렉터
SALE_MESSAGE_SELECTORS = (".saleRetMsg", "#saleRetMsg", "[class*='saleRetMsg']")
PRICE_SELECTORS = (
    ".lotto720_price.lpcurpay",
    ".lotto720_price",
    ".lpcurpay",
    "#buyAmount",
)
BALANCE_SELECTORS = (
    "#curdeposit",
    "#crntEntrsAmt",
    ".lpdeposit",
    "[id*='EntrsAmt']",
    "[class*='deposit']",
)

# 실패로 확정할 수 있는 명확한 문구만 사용 (과도하게 넓은 패턴 제거)
DEFINITE_FAILURE_PATTERNS = (
    r"구매\s*가?\s*실패",
    r"구매에\s*실패",
    r"결제\s*.{0,6}실패",
    r"잔액\s*.{0,4}부족",
    r"예치금\s*.{0,4}부족",
    r"서비스\s*.{0,4}점검",
    r"판매\s*.{0,4}중지",
    r"구매\s*가능한\s*티켓이\s*없습니다",
    r"구매\s*불가",
)

SUCCESS_PATTERNS = (
    r"구매\s*가?\s*완료",
    r"부분적으로\s*완료",
    r"정상\s*.{0,4}처리",
)

# "조 + 6자리" 형태의 연금복권 번호
TICKET_PATTERN = re.compile(r"([1-5])\s*조\s*[^\d]{0,4}(\d{6})")


# ---------------------------------------------------------------- 유틸


def _normalize(text: str) -> str:
    """공백 제거 후 비교하기 쉬운 형태로 변환."""
    return re.sub(r"\s+", "", text or "")


def _matches_any(text: str, patterns: Sequence[str]) -> str | None:
    """패턴 중 하나라도 매칭되면 그 패턴을 반환."""
    if not text:
        return None
    compact = re.sub(r"\s+", " ", text)
    for pattern in patterns:
        if re.search(pattern, compact):
            return pattern
    return None


def _parse_int(text: str) -> int:
    digits = re.sub(r"[^0-9]", "", text or "")
    return int(digits) if digits else 0


# ---------------------------------------------------------------- 프레임 해석


def _resolve_game_context(page: Page) -> GameContext:
    """
    게임 화면의 컨텍스트(Page 또는 Frame)를 반환합니다.

    [핵심 수정]
    기존에는 page.frame_locator() 로 FrameLocator 를 반환했으나
    FrameLocator 에는 evaluate() 가 없어 진단/fallback 코드가 전부 죽었습니다.
    여기서는 ElementHandle.content_frame() 으로 실제 Frame 을 얻습니다.
    Frame 은 locator() 와 evaluate() 를 모두 지원합니다.
    """
    try:
        if page.locator(IFRAME_SELECTOR).count() == 0:
            log.debug("iframe(%s) 없음 → 페이지 직접 사용", IFRAME_SELECTOR)
            return page

        handle = page.query_selector(IFRAME_SELECTOR)
        if handle is None:
            log.debug("iframe 핸들을 얻지 못함 → 페이지 직접 사용")
            return page

        frame = handle.content_frame()
        if frame is None:
            log.warning("iframe content_frame() 이 None 입니다 → 페이지 직접 사용")
            return page

        log.debug("iframe Frame 확보: url=%s", frame.url)
        return frame
    except Exception as exc:
        log.warning("프레임 해석 실패(%s) → 페이지 직접 사용", exc)
        return page


def _wait_context_ready(ctx: GameContext, timeout: int = 15000) -> None:
    try:
        ctx.locator("body").first.wait_for(state="attached", timeout=timeout)
    except PlaywrightTimeoutError:
        log.warning("게임 컨텍스트 body 대기 타임아웃")


# ---------------------------------------------------------------- 진단


def dump_diagnostics(page: Page, ctx: GameContext, label: str, want_debug: bool) -> None:
    """
    실패 원인 규명을 위한 진단 정보를 저장/출력합니다.

    셀렉터가 사이트 변경으로 깨졌을 때, 다음 실행 로그만 보고
    무엇이 바뀌었는지 알 수 있도록 클릭 가능한 요소 전체를 나열합니다.
    """
    log.warning("=== 진단 정보 (%s) ===", label)
    log.warning("페이지 URL: %s", page.url)
    if isinstance(ctx, Frame):
        log.warning("프레임 URL: %s", ctx.url)

    # 클릭 가능한 요소 목록 (Frame/Page 모두 evaluate 지원)
    try:
        rows = ctx.evaluate(
            """
            () => {
                const nodes = Array.from(document.querySelectorAll(
                    "button,a,input[type='button'],input[type='submit'],label,[onclick]"
                ));
                const norm = (s) => (s || "").replace(/\\s+/g, " ").trim();
                return nodes.slice(0, 150).map(n => {
                    const text = norm(n.textContent) || norm(n.value);
                    const id = n.id || "";
                    const cls = (typeof n.className === "string") ? n.className : "";
                    const onclick = n.getAttribute("onclick") || "";
                    const visible = !!(n.offsetWidth || n.offsetHeight || n.getClientRects().length);
                    return { text, id, cls, onclick, visible };
                }).filter(r => r.text || r.id || r.onclick);
            }
            """
        )
        log.warning("클릭 가능 요소 %s개:", len(rows))
        for row in rows[:60]:
            log.warning(
                "  [%s] text='%s' id='%s' class='%s' onclick='%s'",
                "보임" if row.get("visible") else "숨김",
                str(row.get("text", ""))[:40],
                str(row.get("id", ""))[:30],
                str(row.get("cls", ""))[:40],
                str(row.get("onclick", ""))[:60],
            )
    except Exception as exc:
        log.warning("요소 목록 수집 실패: %s", exc)

    if not want_debug:
        log.warning("DEBUG=1 로 실행하면 HTML/스크린샷도 저장됩니다.")
        return

    try:
        page.screenshot(path=debug_path(f"720_{label}.png"), full_page=True)
    except Exception as exc:
        log.debug("스크린샷 저장 실패: %s", exc)

    try:
        content = ctx.content() if hasattr(ctx, "content") else page.content()
        with open(debug_path(f"720_{label}.html"), "w", encoding="utf-8") as fp:
            fp.write(content)
        log.warning("HTML 저장: debug/720_%s.html", label)
    except Exception as exc:
        log.debug("HTML 저장 실패: %s", exc)


# ---------------------------------------------------------------- 클릭 헬퍼


def _click_first(
    ctx: GameContext,
    selectors: Sequence[str],
    label: str,
    timeout: int = 5000,
    force: bool = True,
) -> str:
    """
    여러 셀렉터를 순차 시도하여 첫 클릭 가능한 요소를 클릭합니다.

    [수정] 기존에는 스코프된 로케이터에 절대 셀렉터를 넘겨 매칭 실패가 있었습니다.
    이 함수는 항상 프레임/페이지 기준(ctx)으로만 호출해야 합니다.
    """
    attempted = []
    for selector in selectors:
        try:
            element = ctx.locator(selector)
            count = element.count()
            if count == 0:
                attempted.append(f"{selector}(0개)")
                continue
            element.first.click(timeout=timeout, force=force)
            log.debug("%s 클릭 성공: %s", label, selector)
            return selector
        except PlaywrightTimeoutError:
            attempted.append(f"{selector}(타임아웃)")
        except Exception as exc:
            attempted.append(f"{selector}({type(exc).__name__})")

    raise RuntimeError(f"{label} 요소를 찾지 못했습니다. 시도: {attempted}")


def _click_by_keyword(ctx: GameContext, keywords: Sequence[str], label: str) -> str:
    """
    키워드 기반 클릭 (DOM 직접 탐색 포함).

    [수정] ctx 가 Frame 이므로 evaluate() 가 정상 동작합니다.
    기존에는 FrameLocator 라서 이 함수 자체가 AttributeError 로 실패했습니다.
    """
    # 1. Playwright 텍스트 셀렉터
    for keyword in keywords:
        for template in (
            "a:has-text('{}')",
            "button:has-text('{}')",
            "input[value*='{}']",
            "label:has-text('{}')",
            "[title*='{}']",
        ):
            selector = template.format(keyword)
            try:
                element = ctx.locator(selector)
                if element.count() == 0:
                    continue
                element.first.click(timeout=3000, force=True)
                log.debug("%s 키워드 클릭 성공: %s", label, selector)
                return selector
            except Exception:
                continue

    # 2. DOM 직접 탐색 (onclick 속성까지 검사)
    for keyword in keywords:
        try:
            clicked = ctx.evaluate(
                """
                (keyword) => {
                    const nodes = Array.from(document.querySelectorAll(
                        "button,a,label,input,span,div,[onclick]"
                    ));
                    const norm = (s) => (s || "").replace(/\\s+/g, " ").trim().toLowerCase();
                    const needle = keyword.toLowerCase();
                    for (const n of nodes) {
                        const blob = [
                            norm(n.textContent),
                            norm(n.value),
                            norm(n.getAttribute("title")),
                            norm(n.getAttribute("onclick"))
                        ].join(" ");
                        if (!blob.includes(needle)) continue;
                        try { n.click(); return true; } catch (e) {}
                    }
                    return false;
                }
                """,
                keyword,
            )
            if clicked:
                log.debug("%s DOM 키워드 클릭 성공: %s", label, keyword)
                return f"dom:{keyword}"
        except Exception as exc:
            log.debug("DOM 키워드 클릭 실패(%s): %s", keyword, exc)

    raise RuntimeError(f"{label} 키워드 클릭 실패: {list(keywords)}")


def _try_click(ctx: GameContext, selectors: Sequence[str], label: str) -> bool:
    """실패해도 예외를 던지지 않는 선택적 클릭."""
    try:
        _click_first(ctx, selectors, label, timeout=3000)
        return True
    except Exception as exc:
        log.debug("%s (선택적) 클릭 생략: %s", label, exc)
        return False


# ---------------------------------------------------------------- 화면 읽기


def _read_text(ctx: GameContext, selectors: Sequence[str], timeout: int = 2000) -> str:
    for selector in selectors:
        try:
            element = ctx.locator(selector)
            if element.count() == 0:
                continue
            text = (element.first.inner_text(timeout=timeout) or "").strip()
            if text:
                return text
        except Exception:
            continue
    return ""


def _read_amount(ctx: GameContext) -> int:
    """결제 금액 표시를 읽습니다. 못 읽으면 0."""
    text = _read_text(ctx, PRICE_SELECTORS)
    return _parse_int(text)


def _read_balance(ctx: GameContext) -> int:
    """화면 내 잔액을 읽습니다. 못 읽으면 -1."""
    for selector in BALANCE_SELECTORS:
        try:
            element = ctx.locator(selector)
            if element.count() == 0:
                continue
            first = element.first

            value = first.get_attribute("value")
            if value:
                amount = _parse_int(value)
                if amount > 0:
                    return amount

            text = (first.inner_text(timeout=1500) or "").strip()
            amount = _parse_int(text)
            if amount > 0:
                return amount
        except Exception:
            continue
    return -1


def _read_sale_message(ctx: GameContext) -> str:
    return _read_text(ctx, SALE_MESSAGE_SELECTORS, timeout=1500)


def _extract_tickets(ctx: GameContext) -> list[str]:
    """
    구매한 티켓(조 + 6자리 번호)을 추출합니다.

    [수정] 기존에는 numbers="자동 선택" 으로 하드코딩되어
    실제로 무슨 번호를 샀는지 알 수 없었습니다.
    """
    tickets: list[str] = []
    seen = set()

    candidate_selectors = (
        "#popup1",
        ".saleRetMsg",
        ".lotto720_result",
        "[class*='result']",
        "body",
    )

    for selector in candidate_selectors:
        try:
            element = ctx.locator(selector)
            if element.count() == 0:
                continue
            text = element.first.inner_text(timeout=2000) or ""
        except Exception:
            continue

        for group, digits in TICKET_PATTERN.findall(text):
            label = f"{group}조 {digits}"
            if label in seen:
                continue
            seen.add(label)
            tickets.append(label)

        if tickets:
            break

    return tickets


# ---------------------------------------------------------------- 네비게이션


def _navigate_to_game(page: Page, want_debug: bool) -> GameContext:
    """
    720+ 게임 화면으로 이동하고 게임 컨텍스트를 반환합니다.

    [수정] 기존 루프는 첫 iteration 에서 무조건 return 하여
    두 번째 데스크톱 URL 을 시도하지 못했고, 뒤쪽에 도달 불가 코드가 있었습니다.
    """
    last_url = ""

    # 1. 데스크톱 URL 순차 시도
    for index, url in enumerate(DESKTOP_URLS, 1):
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except PlaywrightTimeoutError:
                log.debug("networkidle 타임아웃 (계속 진행)")
            time.sleep(2)
        except Exception as exc:
            log.warning("데스크톱 URL %s 이동 실패: %s", index, exc)
            continue

        last_url = page.url
        log.info("현재 URL (데스크톱 시도 %s): %s", index, last_url)

        if "m.dhlottery.co.kr" in last_url or "game_mobile" in last_url:
            log.info("모바일로 리다이렉트됨 → 모바일 경로로 전환")
            break

        ctx = _resolve_game_context(page)
        _wait_context_ready(ctx)
        return ctx

    # 2. 모바일 경로 — 메인에서 720 바로구매 버튼
    mobile_entry_selectors = (
        "#pt720ImdtPrchs",
        "#btnMoPtgmPrchs",
        ".btnBuyPt720",
        "a:has-text('연금복권720+')",
        "button:has-text('연금복권720+')",
    )
    if _try_click(page, mobile_entry_selectors, "모바일 720 바로구매"):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            time.sleep(2)
            if "pension720" in page.url:
                log.info("모바일 720 구매 페이지 진입: %s", page.url)
                ctx = _resolve_game_context(page)
                _wait_context_ready(ctx)
                return ctx
        except Exception as exc:
            log.debug("모바일 진입 후 대기 실패: %s", exc)

    # 3. 모바일 URL 직접 진입
    for url in MOBILE_URLS:
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except PlaywrightTimeoutError:
                pass
            time.sleep(2)
            if "pension720" in page.url:
                log.info("모바일 720 URL 직접 진입 성공: %s", page.url)
                ctx = _resolve_game_context(page)
                _wait_context_ready(ctx)
                return ctx
            last_url = page.url
        except Exception as exc:
            log.debug("모바일 URL 진입 실패(%s): %s", url, exc)
            continue

    dump_diagnostics(page, page, "navigate_failed", want_debug)
    raise RuntimeError(f"연금복권 720+ 게임 화면 진입 실패 (마지막 URL: {last_url})")


# ---------------------------------------------------------------- 단일 구매


@dataclass
class PurchaseAttempt:
    """1회(5,000원) 구매 시도의 결과."""

    attempted: bool = False
    success_signal: bool = False
    total_cost: int = 0
    tickets: list[str] = field(default_factory=list)
    balance_before: int = -1
    balance_after: int = -1
    dialogs: list[str] = field(default_factory=list)
    sale_message: str = ""
    failure_reason: str = ""


def _purchase_once(page: Page, want_debug: bool, dry_run: bool = False) -> PurchaseAttempt:
    """연금복권 720+ 를 1회(5,000원) 구매합니다."""
    attempt = PurchaseAttempt()

    ctx = _navigate_to_game(page, want_debug)

    # 세션 확인
    try:
        user_field = ctx.locator("input[name='USER_ID']")
        if user_field.count() > 0:
            value = user_field.first.get_attribute("value")
            if not value:
                raise RuntimeError("게임 페이지에서 로그인 세션이 확인되지 않습니다 (USER_ID 빈 값).")
    except RuntimeError:
        raise
    except Exception as exc:
        log.debug("세션 확인 생략: %s", exc)

    # 잔여 팝업 정리
    _try_click(
        ctx,
        (
            "#popupLayerAlert button:has-text('확인')",
            "#popupLayerAlert input[value='확인']",
            "#popupLayerAlert a:has-text('확인')",
        ),
        "알림 팝업 닫기",
    )
    _try_click(
        ctx,
        (
            "#popup1 a:has-text('닫기')",
            "#popup1 a:has-text('확인')",
            "#popup1 .btn_lgray.medium",
        ),
        "이전 결과 팝업 닫기",
    )

    attempt.balance_before = _read_balance(ctx)
    if attempt.balance_before >= 0:
        log.info("구매 전 화면 잔액: %s원", f"{attempt.balance_before:,}")

    # dialog 수집 (alert 등)
    def _on_dialog(dialog):
        try:
            attempt.dialogs.append(dialog.message or "")
            dialog.accept()
        except Exception as exc:
            log.debug("dialog 처리 실패: %s", exc)

    page.on("dialog", _on_dialog)

    try:
        # 1) 번호 선택 팝업 열기 (모바일에서 필요, 데스크톱에서는 없을 수 있음)
        _try_click(
            ctx,
            (
                "a:has-text('번호 선택하기')",
                "button:has-text('번호 선택하기')",
                "[onclick*='selNumberPopup']",
            ),
            "번호 선택 팝업 열기",
        )
        time.sleep(1)

        # 2) 자동번호
        # [수정] 스코프를 좁히지 않고 프레임 기준 절대 셀렉터 사용
        auto_selectors = (
            "#popup4 a[onclick*='doAuto']",
            "#popup4 .btn_wht.xsmall[onclick*='doAuto']",
            "a[onclick*='doAuto']",
            "button[onclick*='doAuto']",
            ".lotto720_btn_auto_number",
            "a:has-text('자동번호')",
            "button:has-text('자동번호')",
        )
        try:
            _click_first(ctx, auto_selectors, "자동번호 버튼")
        except Exception as exc:
            log.warning("자동번호 셀렉터 실패, 키워드 fallback 시도: %s", exc)
            dump_diagnostics(page, ctx, "auto_button_failed", want_debug)
            _click_by_keyword(ctx, ("자동번호", "자동선택", "자동"), "자동번호 버튼")
        time.sleep(1)

        # 3) 선택완료
        verify_selectors = (
            "#popup4 a[onclick*='doVerify']",
            "a[onclick*='doVerify']",
            "button[onclick*='doVerify']",
            ".lotto720_btn_confirm_number",
            "a:has-text('선택완료')",
            "button:has-text('선택완료')",
        )
        try:
            _click_first(ctx, verify_selectors, "선택완료 버튼")
        except Exception as exc:
            log.warning("선택완료 셀렉터 실패, 키워드 fallback 시도: %s", exc)
            dump_diagnostics(page, ctx, "verify_button_failed", want_debug)
            _click_by_keyword(ctx, ("선택완료", "선택 완료", "완료"), "선택완료 버튼")
        time.sleep(1)

        # 4) 금액 검증
        displayed = _read_amount(ctx)
        if displayed == 0:
            log.warning("결제 금액 표시를 읽지 못했습니다. 절차를 계속 진행합니다.")
        elif displayed != PER_720_PURCHASE_AMOUNT:
            dump_diagnostics(page, ctx, "amount_mismatch", want_debug)
            raise RuntimeError(
                f"결제 금액 불일치 (예상 {PER_720_PURCHASE_AMOUNT:,}원, 표시 {displayed:,}원)"
            )
        else:
            log.info("결제 금액 확인: %s원", f"{displayed:,}")

        if dry_run:
            log.warning("DRY_RUN: 구매 버튼 클릭 직전에 중단합니다. (실제 구매 안 됨)")
            attempt.failure_reason = "dry_run"
            return attempt

        # 5) 구매하기
        attempt.attempted = True
        buy_selectors = (
            "a[onclick*='doOrder']",
            "button[onclick*='doOrder']",
            "a:has-text('구매하기')",
            "button:has-text('구매하기')",
            ".lotto720_btn_buy",
            "[name='btnBuy']",
        )
        try:
            _click_first(ctx, buy_selectors, "구매하기 버튼")
        except Exception as exc:
            log.warning("구매하기 셀렉터 실패, 키워드 fallback 시도: %s", exc)
            dump_diagnostics(page, ctx, "buy_button_failed", want_debug)
            _click_by_keyword(ctx, ("구매하기", "구매"), "구매하기 버튼")
        time.sleep(1)

        # 6) 최종 확인 팝업 (window.confirm 은 add_init_script 로 자동 수락됨)
        _try_click(
            ctx,
            (
                "#lotto720_popup_confirm a.btn_blue",
                "#lotto720_popup_confirm a:has-text('확인')",
                "#popupLayerConfirm input[value='확인']",
                "button:has-text('확인')",
                "input[value='확인']",
            ),
            "최종 확인 버튼",
        )

        # 7) 결과 문구 대기
        for _ in range(10):
            time.sleep(1)
            attempt.sale_message = _read_sale_message(ctx)
            if attempt.sale_message:
                break

        attempt.balance_after = _read_balance(ctx)
        if attempt.balance_after >= 0:
            log.info("구매 후 화면 잔액: %s원", f"{attempt.balance_after:,}")

        if attempt.sale_message:
            log.info("구매 결과 문구: %s", attempt.sale_message)
        if attempt.dialogs:
            log.info("감지된 dialog: %s", attempt.dialogs)

        # 8) 실패 판정 — 명확한 문구만 사용
        for message in attempt.dialogs:
            hit = _matches_any(message, DEFINITE_FAILURE_PATTERNS)
            if hit:
                attempt.failure_reason = f"dialog 실패 문구: {message}"
                dump_diagnostics(page, ctx, "dialog_failure", want_debug)
                raise RuntimeError(attempt.failure_reason)

        hit = _matches_any(attempt.sale_message, DEFINITE_FAILURE_PATTERNS)
        if hit:
            attempt.failure_reason = f"결과 실패 문구: {attempt.sale_message}"
            dump_diagnostics(page, ctx, "sale_failure", want_debug)
            raise RuntimeError(attempt.failure_reason)

        # 9) 성공 신호 판정
        signals = []
        if _matches_any(attempt.sale_message, SUCCESS_PATTERNS):
            signals.append("결과 문구")
        if any(_matches_any(m, SUCCESS_PATTERNS) for m in attempt.dialogs):
            signals.append("dialog 문구")
        if (
            attempt.balance_before >= 0
            and attempt.balance_after >= 0
            and (attempt.balance_before - attempt.balance_after) >= PER_720_PURCHASE_AMOUNT
        ):
            signals.append("화면 잔액 차감")

        attempt.success_signal = bool(signals)
        if signals:
            log.info("성공 신호: %s", ", ".join(signals))
        else:
            log.warning(
                "구매 완료 신호를 화면에서 확인하지 못했습니다. "
                "상위 로직의 예치금 차감 검증으로 최종 판정합니다."
            )
            dump_diagnostics(page, ctx, "no_success_signal", want_debug)

        attempt.tickets = _extract_tickets(ctx)
        if attempt.tickets:
            log.info("구매 티켓: %s", ", ".join(attempt.tickets))

        attempt.total_cost = PER_720_PURCHASE_AMOUNT
        return attempt

    finally:
        try:
            page.remove_listener("dialog", _on_dialog)
        except Exception as exc:
            log.debug("dialog 리스너 해제 실패: %s", exc)


# ---------------------------------------------------------------- 반복 구매


@dataclass
class Lotto720Result:
    """연금복권 720+ 전체 구매 결과."""

    total_cost: int = 0
    purchase_count: int = 0
    success_signals: int = 0
    tickets: list[str] = field(default_factory=list)
    attempts: list[PurchaseAttempt] = field(default_factory=list)

    # 하위 호환용 dict 접근
    def get(self, key, default=None):
        return getattr(self, key, default)


def _install_confirm_patch(page: Page) -> None:
    """
    doOrder() 내부의 window.confirm 을 자동 수락합니다.
    init script 는 이후 생성되는 모든 document/frame 에 적용됩니다.
    """
    page.add_init_script(
        """
        (() => {
            if (window.__lotto720ConfirmPatched) return;
            window.__lotto720ConfirmPatched = true;
            window.__lotto720Confirms = [];
            const original = window.confirm;
            window.confirm = function(message) {
                try { window.__lotto720Confirms.push(String(message || "")); } catch (e) {}
                return true;
            };
            window.__lotto720OrigConfirm = original;
        })();
        """
    )


def purchase_lotto720(
    page: Page,
    target_amount: int | None = None,
    debug: bool | None = None,
    dry_run: bool = False,
) -> Lotto720Result:
    """
    연금복권 720+ 를 목표 금액까지 5,000원 단위로 반복 구매합니다.

    Args:
        page: 로그인된 Page
        target_amount: 목표 금액 (5,000원 단위). None 이면 LOTTO720_AMOUNT
        debug: 디버그 산출물 생성 여부
        dry_run: 실제 구매 없이 직전까지만 진행

    Returns:
        Lotto720Result
    """
    want_debug = env_bool("DEBUG", False) if debug is None else debug

    amount = target_amount if target_amount is not None else env_int(
        "LOTTO720_AMOUNT", PER_720_PURCHASE_AMOUNT
    )

    if amount <= 0:
        raise ValueError("LOTTO720_AMOUNT 는 0보다 커야 합니다.")
    if amount % PER_720_PURCHASE_AMOUNT != 0:
        raise ValueError(
            f"LOTTO720_AMOUNT 는 {PER_720_PURCHASE_AMOUNT:,}원 단위여야 합니다. (입력: {amount:,}원)"
        )

    count = amount // PER_720_PURCHASE_AMOUNT
    _install_confirm_patch(page)

    result = Lotto720Result()

    log.info("연금복권 720+ 구매 시작 (목표 %s원, %s회)", f"{amount:,}", count)

    for index in range(1, count + 1):
        log.info("[%s/%s] 구매 진행", index, count)
        attempt = _purchase_once(page, want_debug=want_debug, dry_run=dry_run)
        result.attempts.append(attempt)
        result.total_cost += attempt.total_cost
        if attempt.total_cost > 0:
            result.purchase_count += 1
        if attempt.success_signal:
            result.success_signals += 1
        for ticket in attempt.tickets:
            if ticket not in result.tickets:
                result.tickets.append(ticket)
        time.sleep(1)

    log.info(
        "구매 절차 완료 (누적 %s원, 성공 신호 %s/%s)",
        f"{result.total_cost:,}",
        result.success_signals,
        count,
    )
    return result


def run(playwright: Playwright) -> None:
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
        purchase_lotto720(
            page,
            settings.lotto720_amount,
            debug=settings.debug,
            dry_run=settings.dry_run,
        )
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
