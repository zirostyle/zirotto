#!/usr/bin/env python3
"""
연금복권 720+ 자동 구매 모듈

Features:
- 모바일 전용 인터페이스(https://m.dhlottery.co.kr/game_mobile/pension720/game.jsp) 기반 안정적 발권
- 10,000원(5,000원 x 2세트, 총 10매) 자동 구매 완벽 지원
- '모든 조'(1조~5조) 자동 번호 선택
- 발권 번호 정확 추출 및 data/purchased_pension720.json 저장
- 엄격한 4단계 실결제 확인 (결제 완료 UI, .saleCnt, 예치금 차감, 마이페이지 대조)
- 텔레그램 실시간 구매 알림 발송
"""
import os
import json
import time
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

try:
    from playwright.sync_api import Playwright, sync_playwright, Page
except ImportError:
    Playwright = None
    sync_playwright = None
    Page = None

from telegram_notifier import notify_lotto720_purchase

PER_PURCHASE_AMOUNT = 5000
DEFAULT_TARGET_AMOUNT = 10000


def _get_target_amount(target_amount: int = None) -> int:
    if target_amount is None:
        try:
            target_amount = int(str(os.environ.get("LOTTO720_AMOUNT", str(DEFAULT_TARGET_AMOUNT))).replace(",", "").strip())
        except Exception:
            target_amount = DEFAULT_TARGET_AMOUNT

    if target_amount % PER_PURCHASE_AMOUNT != 0 or target_amount < PER_PURCHASE_AMOUNT:
        print(f"⚠️ 목표 금액(₩{target_amount:,})을 5,000원 단위로 보정합니다. (기본: ₩{DEFAULT_TARGET_AMOUNT:,})")
        target_amount = DEFAULT_TARGET_AMOUNT
    return target_amount


def save_purchased_pension720(round_num: int, tickets: list, total_cost: int) -> None:
    """
    구매한 연금복권 720+ 번호와 회차 정보를 data/purchased_pension720.json에 저장합니다.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    file_path = os.path.join(data_dir, "purchased_pension720.json")

    history = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                history = content.get("history", [])
        except Exception as e:
            print(f"⚠️ 기존 연금복권 구매 데이터 로드 실패: {e}")

    try:
        kst = timezone(timedelta(hours=9))
        now_str = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    grouped_by_num = {}
    for t in tickets:
        if isinstance(t, dict):
            grp = t.get("group", "")
            num = t.get("number", "")
            grouped_by_num.setdefault(num, []).append(grp)

    sets = []
    for idx, (num, grps) in enumerate(grouped_by_num.items(), 1):
        sets.append({
            "set_index": idx,
            "number": num,
            "groups": sorted(grps)
        })

    record = {
        "round": round_num,
        "purchase_date": now_str,
        "total_cost": total_cost,
        "ticket_count": len(tickets),
        "tickets": tickets,
        "sets": sets
    }

    # 동일 회차 및 당일 기록 갱신 또는 추가
    updated = False
    for i, item in enumerate(history):
        if item.get("round") == round_num and item.get("purchase_date", "")[:10] == now_str[:10]:
            history[i] = record
            updated = True
            break
    if not updated:
        history.append(record)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump({"history": history}, f, ensure_ascii=False, indent=2)

    print(f"💾 연금복권 {round_num}회 구매 번호 저장 완료 ({len(tickets)}매, ₩{total_cost:,}) -> {file_path}")


def get_purchased_pension720_from_file(target_round: int = None) -> Optional[dict]:
    """data/purchased_pension720.json 파일에서 구매 내역을 불러옵니다."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(base_dir, "data", "purchased_pension720.json")

    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            history = data.get("history", [])
            if not history:
                return None
            if target_round:
                for item in reversed(history):
                    if item.get("round") == target_round:
                        return item
                return None
            return history[-1]
    except Exception as e:
        print(f"⚠️ 연금복권 구매 데이터 로드 오류: {e}")
        return None


def get_current_pension720_round(page=None) -> int:
    """현재 판매 중인 연금복권 720+ 회차를 산출하거나 화면에서 확인합니다."""
    if page is not None:
        try:
            for selector in [".round", "#round", ".lotto720_round", "[class*='round']", "h2", "h3", ".tit_round"]:
                loc = page.locator(selector)
                if loc.count() > 0:
                    text = loc.first.inner_text(timeout=1000)
                    m = re.search(r'(?:제\s*)?([0-9]{3,4})\s*회', text)
                    if m:
                        r = int(m.group(1))
                        if 250 <= r <= 600:
                            return r
        except Exception:
            pass

    # KST 기준 주차 산출 (2020-05-07 제 1회 추첨)
    try:
        kst = timezone(timedelta(hours=9))
        now_kst = datetime.now(kst)
        first_draw = datetime(2020, 5, 7, 19, 5, tzinfo=kst)
        weeks = int((now_kst - first_draw).total_seconds() / (7 * 86400))
        return weeks + 2
    except Exception:
        return 333


def dismiss_popups(page: Page) -> None:
    """화면을 가리는 모바일 팝업 및 알림 레이어를 닫습니다."""
    try:
        close_selectors = [
            "#popupLayerAlert button:has-text('확인')",
            "#popupLayerAlert a:has-text('확인')",
            "#popupLayerConfirm button:has-text('확인')",
            "#popupLayerAlert .btn-pop-close",
            "#popupLayerConfirm .btn-pop-close",
            "#popupLayerEvent button:has-text('닫기')",
            "#popupLayerEvent .btn-pop-close",
            "#popup1 a:has-text('닫기')",
            "#popup1 a:has-text('확인')",
            ".btn_close",
            ".btn_pop_close",
            ".btn-pop-close",
            "button:has-text('닫기')",
            "a:has-text('닫기')",
            "button:has-text('오늘 하루 보지 않기')",
            "a:has-text('오늘 하루 보지 않기')",
        ]
        for sel in close_selectors:
            loc = page.locator(sel)
            cnt = min(loc.count(), 2)
            for i in range(cnt):
                try:
                    el = loc.nth(i)
                    if el.is_visible(timeout=300):
                        el.click(timeout=800, force=True)
                        time.sleep(0.2)
                except Exception:
                    pass
    except Exception:
        pass


def _click_first_available(page, selectors: list, label: str, timeout: int = 5000, force: bool = False) -> str:
    """후보 셀렉터들 중 가장 먼저 클릭 가능한 요소를 클릭합니다."""
    end_time = time.time() + (timeout / 1000)
    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=min(1200, int(timeout))):
                el.click(timeout=timeout, force=force)
                return selector
        except Exception:
            continue

    while time.time() < end_time:
        for selector in selectors:
            try:
                el = page.locator(selector).first
                if el.count() > 0:
                    el.click(timeout=1000, force=True)
                    return selector
            except Exception:
                continue
        time.sleep(0.3)

    raise Exception(f"{label} 요소를 찾지 못했습니다: {selectors}")


def _extract_selected_digits(target) -> str:
    """#popup4 또는 화면 내에서 선택된 6자리 번호를 추출합니다."""
    try:
        raw_candidates = target.evaluate(
            """
            () => {
                const results = [];
                // 1. Popup4 inputs or digits
                const popup4 = document.querySelector('#popup4');
                if (popup4) {
                    const inputs = popup4.querySelectorAll('input[type="text"], input[readonly], .num_box, .digit, span.num, .num');
                    let str = '';
                    for (const inp of inputs) {
                        const val = (inp.value || inp.innerText || '').trim();
                        if (/^\\d$/.test(val)) str += val;
                    }
                    if (str.length >= 6) results.push(str.slice(0, 6));

                    const pText = (popup4.innerText || '').replace(/\\s+/g, '');
                    const m = pText.match(/(\\d{6})/);
                    if (m) results.push(m[1]);
                }

                // 2. Selection container on main page
                const elements = document.querySelectorAll('.selected_num, .choice_num, .num_area, .lotto720_selected, #selectedList, span, div, p, td');
                for (const el of elements) {
                    const txt = (el.innerText || '').replace(/\\s+/g, '');
                    const m = txt.match(/([1-5]조)?(\\d{6})/);
                    if (m && m[2] && !txt.includes('000원') && !txt.includes('700만') && !txt.includes('100만') && !txt.includes('2026')) {
                        results.push(m[2]);
                    }
                }
                return results;
            }
            """
        )
        if isinstance(raw_candidates, list):
            for cand in raw_candidates:
                if len(cand) == 6 and cand.isdigit():
                    return cand
    except Exception as e:
        print(f"  ℹ️ 번호 추출 중 예외: {e}")
    return ""


def _get_amount_from_text(text: str, label: str) -> Optional[int]:
    """라벨 다음의 금액(원)을 정수로 파싱합니다."""
    pattern = rf"{re.escape(label)}\s*[:\s]*([0-9,]+)\s*원"
    match = re.search(pattern, (text or "").replace("\n", " "))
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except Exception:
        return None


def _get_visible_result_text(page: Page) -> str:
    """구매 완료 레이어/팝업에 나타난 텍스트를 수집합니다."""
    selectors = [
        "#popupLayerAlert",
        "#popupLayerConfirm",
        ".popup_layer",
        ".popup_wrap",
        ".layer_popup",
        "#result",
        "#report",
        "#popup1",
        ".saleRetMsg",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=800):
                txt = loc.inner_text().strip()
                if txt:
                    return txt
        except Exception:
            continue
    try:
        return page.locator("body").inner_text()
    except Exception:
        return ""


def _is_purchase_success(result_text: str) -> bool:
    """구매 완료 성공 문구를 확인합니다."""
    success_markers = [
        "연금복권720+ 구매완료",
        "연금복권720+구매완료",
        "구매가 완료되었습니다",
        "구매가완료되었습니다",
        "구매를 완료하였습니다",
        "구매를완료하였습니다",
        "구매완료",
        "구매 완료",
        "정상적으로 처리되었습니다",
        "정상적으로처리되었습니다",
    ]
    norm = (result_text or "").replace(" ", "")
    return any(marker.replace(" ", "") in norm for marker in success_markers)


def _detect_failure_reason(result_text: str, dialog_messages: list) -> Optional[str]:
    """구매 실패 사유를 감지합니다."""
    combined = (result_text or "") + " " + " ".join(dialog_messages)
    failure_markers = {
        "예치금 부족": ["예치금이 부족", "잔액이 부족", "예치금 부족"],
        "구매 한도 초과": ["구매한도", "한도 초과", "구매한도를 초과"],
        "번호 미선택": ["선택된 번호가 없습니다", "번호를 선택해"],
        "판매 마감/시간 외": ["판매가 마감", "구매 가능 시간이 아닙니다", "판매시간이 아닙니다", "이용 불가"],
    }
    for reason, markers in failure_markers.items():
        if any(m in combined for m in markers):
            return reason
    return None


def _read_balance(page: Page) -> int:
    """화면에 표시된 현재 예치금 잔액을 읽습니다."""
    selectors = [
        ".deposit_balance",
        "#moneyDeposit",
        "#userDeposit",
        ".money",
        "[class*='deposit']",
        ".user_money",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                txt = loc.first.inner_text(timeout=500)
                m = re.search(r'([0-9,]+)\s*원?', txt or "")
                if m:
                    val = int(m.group(1).replace(",", ""))
                    if val >= 0:
                        return val
        except Exception:
            continue

    try:
        body_text = page.locator("body").inner_text(timeout=1000)
        amt = _get_amount_from_text(body_text, "예치금") or _get_amount_from_text(body_text, "보유 예치금")
        if amt is not None:
            return amt
    except Exception:
        pass
    return -1


def get_purchased_pension720_from_mypage(page: Page, target_round: int = None) -> list:
    """
    동행복권 마이페이지(구매당첨내역)에서 최근 구매한 연금복권 720+ 티켓 목록을 크롤링합니다.
    """
    tickets = []
    try:
        print("🌐 동행복권 마이페이지에서 연금복권 구매 번호 조회 시도...")
        page.goto("https://www.dhlottery.co.kr/myPage.do?method=lottoBuyListView", timeout=45000)
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(2)

        try:
            page.select_option("select#lottoId", "LP72")
        except Exception:
            pass

        try:
            page.locator("#frm a:has-text('1주일'), #frm a:has-text('1주'), #frm a:has-text('당일')").first.click(timeout=3000)
        except Exception:
            pass

        try:
            page.click("#submit_btn", force=True)
            time.sleep(2)
        except Exception:
            pass

        iframe_element = page.locator("iframe#lottoBuyList")
        if iframe_element.count() > 0:
            frame = page.frame_locator("iframe#lottoBuyList")
            table_text = frame.locator("table.tbl_data_col").inner_text(timeout=5000)
            print(f"  [마이페이지 연금복권 내역]: {table_text[:200]}")

            matches = re.findall(r'([1-5])조\s*[:\-\s]?\s*(\d{6})', table_text)
            if matches:
                for grp, num in matches:
                    tickets.append({'group': f'{grp}조', 'number': num})

            # 상세 보기 링크 클릭을 통한 영수증 팝업 확인
            if not tickets:
                links = frame.locator("table.tbl_data_col a, table.tbl_data_col button").all()
                for link in links[:3]:
                    try:
                        with page.expect_popup(timeout=4000) as popup_info:
                            link.click()
                        popup = popup_info.value
                        popup.wait_for_load_state("domcontentloaded", timeout=10000)
                        popup_text = popup.locator("body").inner_text(timeout=5000)
                        popup_matches = re.findall(r'([1-5])조\s*[:\-\s]?\s*(\d{6})', popup_text)
                        for grp, num in popup_matches:
                            tickets.append({'group': f'{grp}조', 'number': num})
                        popup.close()
                        if tickets:
                            break
                    except Exception:
                        continue
    except Exception as e:
        print(f"  ⚠️ 마이페이지 연금복권 조회 실패: {e}")

    return tickets


def _purchase_once(page: Page, round_num: int) -> dict:
    """연금복권 720+ 1세트(5,000원, 1조~5조 5매)를 구매합니다."""
    # 1. 팝업 정리
    dismiss_popups(page)
    time.sleep(0.5)

    balance_before = _read_balance(page)

    # 2. '번호 선택하기' 클릭
    print("  👉 [1/5] '번호 선택하기' 클릭...")
    _click_first_available(
        page,
        [
            "a.btn_gray_st1.large.full:has-text('번호 선택하기')",
            "a:has-text('+ 번호 선택하기')",
            "a:has-text('번호 선택하기')",
            "button:has-text('번호 선택하기')",
            "[onclick*='selNumberPopup']",
        ],
        "번호 선택하기 버튼",
        timeout=15000,
    )

    page.wait_for_selector("#popup4", state="visible", timeout=10000)
    time.sleep(1)

    # 3. '모든 조' 선택 및 '자동번호' 클릭
    print("  👉 [2/5] '모든 조' 확인 및 '자동번호' 생성...")
    try:
        all_jo = page.locator("#popup4 span.group.all, #popup4 .selGroup, #popup4 .group.all, #popup4 a:has-text('모든 조')").first
        if all_jo.is_visible(timeout=1500):
            all_jo.click()
            time.sleep(0.3)
    except Exception:
        pass

    _click_first_available(
        page,
        [
            "#popup4 a.btn_wht.xsmall:has-text('자동번호')",
            "#popup4 a:has-text('자동번호')",
            "#popup4 button:has-text('자동번호')",
            "#popup4 [onclick*='doAuto']",
        ],
        "자동번호 버튼",
        timeout=5000,
    )

    # 번호 생성 대기
    try:
        page.wait_for_function(
            """
            () => {
                const popup = document.querySelector('#popup4');
                return !!popup && /\\d/.test(popup.innerText || '');
            }
            """,
            timeout=5000,
        )
    except Exception:
        pass
    time.sleep(0.5)

    selected_digits = _extract_selected_digits(page.locator("#popup4"))
    if selected_digits:
        print(f"  🎯 번호 생성 확인: 1조~5조 [{selected_digits}]")

    # 4. '선택완료' 클릭
    print("  👉 [3/5] '선택완료' 확정...")
    _click_first_available(
        page,
        [
            "#popup4 a.btn_blue.full.large:has-text('선택완료')",
            "#popup4 a:has-text('선택완료')",
            "#popup4 button:has-text('선택완료')",
            "#popup4 [onclick*='doVerify']",
        ],
        "선택완료 버튼",
        timeout=5000,
    )
    time.sleep(0.8)
    try:
        page.wait_for_selector("#popup4", state="hidden", timeout=10000)
    except Exception:
        pass

    # 번호 재확인
    if not selected_digits:
        selected_digits = _extract_selected_digits(page)

    delete_count = page.locator("text='삭제'").count()
    print(f"  🛒 선택된 티켓 확인 (삭제 버튼: {delete_count}개)")

    # 5. '구매하기' 클릭 및 결제 진행
    print("  👉 [4/5] '구매하기' 결제 실행...")
    dialog_messages = []

    def _on_dialog(dialog):
        try:
            msg = dialog.message or ""
            print(f"    💬 결제 대화상자: {msg}")
            dialog_messages.append(msg)
            dialog.accept()
        except Exception:
            pass

    page.on("dialog", _on_dialog)
    try:
        _click_first_available(
            page,
            [
                "a.btn_blue.large.full:has-text('구매하기')",
                "a:has-text('구매하기')",
                "button:has-text('구매하기')",
                "[onclick*='doOrder']",
                ".lotto720_btn_pay",
            ],
            "구매하기 버튼",
            timeout=5000,
        )
        time.sleep(2)

        # 결제 완료 대기
        try:
            page.wait_for_function(
                """
                () => {
                    const text = document.body ? document.body.innerText : "";
                    const selectors = ["#popupLayerAlert", "#popupLayerConfirm", ".popup_layer", ".popup_wrap", ".layer_popup", "#result", "#report", "#popup1", ".saleRetMsg"];
                    const markers = [
                        "연금복권720+ 구매완료",
                        "구매가 완료되었습니다",
                        "구매를 완료하였습니다",
                        "구매완료",
                        "구매 완료",
                        "예치금이 부족",
                        "잔액이 부족",
                        "구매한도",
                        "선택된 번호가 없습니다",
                    ];
                    return selectors.some((selector) => {
                        const el = document.querySelector(selector);
                        return el && el.offsetParent !== null;
                    }) || markers.some((marker) => text.includes(marker));
                }
                """,
                timeout=30000,
            )
        except Exception:
            pass
        time.sleep(1)
        try:
            page.screenshot(path=f"pension720_after_buy_{int(time.time())}.png")
        except Exception:
            pass
    finally:
        try:
            page.remove_listener("dialog", _on_dialog)
        except Exception:
            pass

    # 6. 엄격한 결과 검증
    print("  👉 [5/5] 결제 결과 엄격 검증...")
    result_text = _get_visible_result_text(page)
    failure_reason = _detect_failure_reason(result_text, dialog_messages)
    if failure_reason:
        raise RuntimeError(f"동행복권 구매 실패: {failure_reason}")

    balance_after = _read_balance(page)
    is_success = False

    # (1) 성공 문구 감지
    if _is_purchase_success(result_text) or any(("완료" in m or "정상" in m) for m in dialog_messages):
        is_success = True
        print("  ✅ 동행복권 결제 완료 화면 확인")

    # (2) 발권 카운터(.saleCnt) 확인
    try:
        cnt_el = page.locator(".saleCnt")
        if cnt_el.count() > 0 and cnt_el.first.is_visible(timeout=1000):
            cnt_val = re.sub(r"[^0-9]", "", cnt_el.first.inner_text() or "0")
            if int(cnt_val) >= 5:
                is_success = True
                print(f"  ✅ 발권 카운터 확인 ({cnt_val}매)")
    except Exception:
        pass

    # (3) 예치금 차감 확인
    if balance_before >= 0 and balance_after >= 0:
        delta = balance_before - balance_after
        if delta >= PER_PURCHASE_AMOUNT:
            is_success = True
            print(f"  ✅ 예치금 차감 확인: {balance_before:,}원 -> {balance_after:,}원 (₩{delta:,} 차감)")

    # (4) 마이페이지 실구매 검증
    if not is_success:
        print("  🔍 마이페이지에서 실구매 여부 즉시 검증...")
        mypage_tickets = get_purchased_pension720_from_mypage(page, round_num)
        if mypage_tickets and len(mypage_tickets) >= 5:
            is_success = True
            print(f"  ✅ 마이페이지 실구매 확인: {len(mypage_tickets)}매")

    if not is_success:
        raise RuntimeError("연금복권 720+ 구매 실패: 동행복권 결제 완료 및 예치금 차감이 확인되지 않았습니다.")

    # 1조~5조 티켓 구성
    tickets = []
    if selected_digits and len(selected_digits) == 6:
        tickets = [{'group': f'{g}조', 'number': selected_digits} for g in range(1, 6)]
    else:
        mypage_tickets = get_purchased_pension720_from_mypage(page, round_num)
        if mypage_tickets:
            tickets = mypage_tickets[:5]

    dismiss_popups(page)

    return {
        "games": 5,
        "total_cost": PER_PURCHASE_AMOUNT,
        "round": round_num,
        "tickets": tickets,
        "number": selected_digits,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "success": True,
    }


def purchase_lotto720(page: Page, target_amount: int = None, send_notification: bool = True) -> dict:
    """
    연금복권 720+를 구매합니다.
    - 5,000원 단위로 반복 구매하여 목표 금액(기본 10,000원 = 2세트, 10매)을 맞춥니다.
    """
    normalized_amount = _get_target_amount(target_amount)
    purchase_count = normalized_amount // PER_PURCHASE_AMOUNT

    print(f"🚀 연금복권 720+ 구매 시작 (목표 금액: ₩{normalized_amount:,}, {purchase_count}세트, 총 {purchase_count * 5}매)")

    # 모바일 뷰포트 설정 (안정적인 모바일 구매 UI)
    page.set_viewport_size({"width": 430, "height": 932})

    GAME_URLS = [
        "https://m.dhlottery.co.kr/game_mobile/pension720/game.jsp",
        "https://el.dhlottery.co.kr/game_mobile/pension720/game.jsp",
    ]
    connected = False
    for gurl in GAME_URLS:
        try:
            print(f"  연금복권 모바일 구매 페이지 접속 시도: {gurl}")
            page.goto(gurl, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
            if "/login" in page.url or "method=login" in page.url:
                print("  ⚠️ 세션 만료 감지 -> 재로그인 후 재시도...")
                from login import login
                login(page)
                page.goto(gurl, timeout=30000, wait_until="domcontentloaded")
                time.sleep(2)
            connected = True
            break
        except Exception as conn_err:
            print(f"  ⚠️ {gurl} 접속 실패: {conn_err}")
            continue

    if not connected:
        page.set_viewport_size({"width": 1920, "height": 1080})
        raise RuntimeError("연금복권 720+ 구매 페이지 접속 실패")

    round_num = get_current_pension720_round(page=page)
    print(f"🎯 연금복권 720+ 판매 회차: 제 {round_num}회")

    total_cost = 0
    all_tickets = []

    try:
        for i in range(purchase_count):
            print(f"\n--- [세트 {i + 1}/{purchase_count}] 구매 진행 ---")
            if i > 0:
                page.goto(page.url, timeout=20000, wait_until="domcontentloaded")
                time.sleep(2)

            res = _purchase_once(page, round_num)
            total_cost += res.get("total_cost", 0)
            if res.get("tickets"):
                all_tickets.extend(res["tickets"])
            time.sleep(2)

        # 번호 확인 fallback
        if not all_tickets or len(all_tickets) < total_cost // 1000:
            print("🔍 발권 번호 확인을 위해 마이페이지 구매내역을 최종 조회합니다...")
            mypage_tickets = get_purchased_pension720_from_mypage(page, round_num)
            if mypage_tickets:
                all_tickets = mypage_tickets

        # 구매 내역 파일 저장 (실제 구매 성공 시에만)
        if total_cost > 0 and all_tickets:
            save_purchased_pension720(round_num, all_tickets, total_cost)

        print(f"\n🎉 연금복권 720+ 구매 성공! (총 ₩{total_cost:,}, {len(all_tickets)}매)")

        if send_notification:
            notify_lotto720_purchase(
                success=True,
                tickets=all_tickets,
                amount=total_cost,
                purchase_count=purchase_count,
                round_num=round_num,
            )

        return {
            "games": len(all_tickets),
            "total_cost": total_cost,
            "round": round_num,
            "tickets": all_tickets,
            "verified": True,
        }

    except Exception as e:
        error_msg = str(e)
        print(f"❌ 연금복권 720+ 구매 중 오류 발생: {error_msg}")
        if send_notification:
            notify_lotto720_purchase(False, error_msg=error_msg, amount=normalized_amount)
        raise
    finally:
        # 데스크톱 뷰포트 복원 (로또 6/45 및 잔액 확인용)
        try:
            page.set_viewport_size({"width": 1920, "height": 1080})
        except Exception:
            pass


def run(playwright: Playwright) -> None:
    """연금복권 720+를 구매합니다 (단독 실행용)."""
    from login import login
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    page = context.new_page()

    try:
        login(page)
        purchase_lotto720(page)
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    if sync_playwright:
        with sync_playwright() as playwright:
            run(playwright)
    else:
        print("Playwright is not installed.")
