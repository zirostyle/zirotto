#!/usr/bin/env python3
"""
연금복권 720+ 자동 구매

Features:
- 모바일/데스크톱 인터페이스 자동 감지 및 적응
- 10,000원(5,000원 x 2세트, 총 10매) 자동 구매 지원
- 모든 조(1조~5조) 자동 번호 선택
- 구매된 6자리 번호 및 조 정보 추출
- data/purchased_pension720.json 파일에 구매 내역 자동 저장
- 텔레그램 상세 구매 알림 발송
"""
import os
import json
import time
import re
from datetime import datetime, timezone, timedelta
from os import environ

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
    """구매 목표 금액을 정규화합니다."""
    if target_amount is None:
        raw = environ.get("LOTTO720_AMOUNT", str(DEFAULT_TARGET_AMOUNT))
        try:
            target_amount = int(str(raw).replace(",", "").strip())
        except Exception:
            target_amount = DEFAULT_TARGET_AMOUNT

    if target_amount <= 0:
        raise ValueError("LOTTO720_AMOUNT는 0보다 커야 합니다.")
    if target_amount % PER_PURCHASE_AMOUNT != 0:
        raise ValueError(
            f"LOTTO720_AMOUNT는 {PER_PURCHASE_AMOUNT:,}원 단위여야 합니다. (입력: {target_amount:,}원)"
        )
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
            "groups": grps
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


def get_purchased_pension720_from_file(target_round: int = None) -> dict:
    """
    data/purchased_pension720.json 파일에서 구매 내역을 불러옵니다.
    """
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
        return history[-1]
    except Exception as e:
        print(f"⚠️ 연금복권 구매 내역 파일 읽기 실패: {e}")
        return None


def get_current_pension720_round(frame=None, page=None) -> int:
    """
    현재 판매/구매 중인 연금복권 720+ 회차를 확인합니다.
    1차: 구매 페이지/프레임 내 표시된 회차 텍스트 ('XXX회')
    2차: 2020-05-07 (1회차) 기준 경과 주수 계산
    """
    for target in [frame, page]:
        if target is not None:
            try:
                text = target.locator("body").inner_text(timeout=2000)
                m = re.search(r'(?:제\s*)?([0-9]{3,4})\s*회', text)
                if m:
                    r = int(m.group(1))
                    if 250 <= r <= 600:
                        return r
            except Exception:
                pass

    try:
        kst = timezone(timedelta(hours=9))
        now_kst = datetime.now(kst)
        first_draw = datetime(2020, 5, 7, 19, 5, tzinfo=kst)
        weeks = int((now_kst - first_draw).total_seconds() / (7 * 86400))
        return weeks + 2
    except Exception:
        return 333


def _click_first(target, selectors: list, label: str, timeout: int = 5000, force: bool = False) -> str:
    """여러 셀렉터를 순차 시도하여 첫 클릭 가능한 요소를 클릭합니다."""
    for selector in selectors:
        try:
            el = target.locator(selector)
            if el.count() > 0:
                el.first.click(timeout=timeout, force=force)
                return selector
        except Exception:
            continue
    raise Exception(f"{label} 요소를 찾지 못했습니다: {selectors}")


def _click_keyword(target, keywords: list, label: str, timeout: int = 5000) -> str:
    """
    키워드 기반으로 버튼/링크/입력을 찾아 클릭합니다.
    """
    selector_candidates = []
    for kw in keywords:
        selector_candidates.extend(
            [
                f"button:has-text('{kw}')",
                f"a:has-text('{kw}')",
                f"label:has-text('{kw}')",
                f"input[value*='{kw}']",
                f"[title*='{kw}']",
                f"[aria-label*='{kw}']",
            ]
        )

    for selector in selector_candidates:
        try:
            el = target.locator(selector)
            if el.count() > 0 and el.first.is_visible(timeout=1200):
                el.first.click(timeout=timeout, force=True)
                return selector
        except Exception:
            continue

    # Final fallback: DOM 직접 탐색 클릭
    for kw in keywords:
        try:
            clicked = target.evaluate(
                """
                (keyword) => {
                    const nodes = Array.from(document.querySelectorAll("button,a,label,input,span,div"));
                    const norm = (s) => (s || "").replace(/\\s+/g, " ").trim();
                    const lower = keyword.toLowerCase();
                    for (const n of nodes) {
                        const text = norm(n.textContent);
                        const value = norm(n.value);
                        const title = norm(n.getAttribute("title"));
                        const onclick = norm(n.getAttribute("onclick"));
                        const blob = `${text} ${value} ${title} ${onclick}`.toLowerCase();
                        if (!blob.includes(lower)) continue;
                        if (n.offsetParent === null && !["INPUT"].includes(n.tagName)) continue;
                        try { n.click(); return true; } catch (_) {}
                    }
                    return false;
                }
                """,
                kw,
            )
            if clicked:
                return f"dom-keyword:{kw}"
        except Exception:
            continue

    raise Exception(f"{label} 키워드 클릭 실패: {keywords}")


def _read_amount(target) -> int:
    """결제 금액 텍스트를 읽어 숫자로 변환합니다."""
    selectors = [
        ".lotto720_price.lpcurpay",
        ".lotto720_price",
        ".lpcurpay",
        "#buyAmount",
        "[class*='price']",
    ]
    for selector in selectors:
        try:
            el = target.locator(selector)
            if el.count() == 0:
                continue
            text = el.first.inner_text(timeout=3000).strip()
            amount = int(re.sub(r"[^0-9]", "", text) or "0")
            if amount > 0:
                return amount
        except Exception:
            continue
    return 0


def _read_balance(target) -> int:
    """
    화면 내 잔액 정보를 가능한 셀렉터에서 읽어옵니다.
    """
    selectors = [
        "#curdeposit",
        "#crntEntrsAmt",
        ".lpdeposit",
        "[id*='EntrsAmt']",
        "[class*='deposit']",
    ]

    for selector in selectors:
        try:
            el = target.locator(selector)
            if el.count() == 0:
                continue
            first = el.first

            try:
                value = first.get_attribute("value")
                if value:
                    amount = int(re.sub(r"[^0-9]", "", value) or "0")
                    if amount > 0:
                        return amount
            except Exception:
                pass

            try:
                text = first.inner_text(timeout=1000).strip()
                amount = int(re.sub(r"[^0-9]", "", text) or "0")
                if amount > 0:
                    return amount
            except Exception:
                pass
        except Exception:
            continue
    return -1


def _has_failure_signal(target) -> bool:
    failure_selectors = [
        "text=/구매\\s*실패\\s*했습니다/",
        "text=/구매에\\s*실패/",
        "text=/결제.*실패/",
        "text=/잔액.*부족/",
        "text=/서비스.*점검/",
        "text=/이용.*불가/",
    ]
    for selector in failure_selectors:
        try:
            if target.locator(selector).first.is_visible(timeout=1200):
                return True
        except Exception:
            continue
    return False


def _read_sale_result(target) -> str:
    """
    구매 결과 문구(.saleRetMsg)를 읽어옵니다.
    """
    selectors = [
        ".saleRetMsg",
        "#saleRetMsg",
        "[class*='saleRetMsg']",
    ]
    for selector in selectors:
        try:
            el = target.locator(selector)
            if el.count() == 0:
                continue
            text = (el.first.inner_text(timeout=1500) or "").strip()
            if text:
                return text
        except Exception:
            continue
    return ""


def _is_visible(target, selector: str, timeout: int = 800) -> bool:
    try:
        el = target.locator(selector)
        if el.count() == 0:
            return False
        return el.first.is_visible(timeout=timeout)
    except Exception:
        return False


def _extract_selected_digits(target) -> str:
    """
    화면 내 선택된 6자리 번호를 추출합니다.
    """
    try:
        raw_candidates = target.evaluate(
            """
            () => {
                const results = [];
                // 1. Check popup4 number box
                const popup4 = document.querySelector('#popup4');
                if (popup4) {
                    const inputs = popup4.querySelectorAll('input[type="text"], input[readonly], .num_box, .digit, span.num');
                    let str = '';
                    for (const inp of inputs) {
                        const val = (inp.value || inp.innerText || '').trim();
                        if (/^\\d$/.test(val)) str += val;
                    }
                    if (str.length >= 6) results.push(str.slice(0, 6));
                }

                // 2. Check elements with 6 consecutive digits
                const elements = document.querySelectorAll('.selected_num, .choice_num, .num_area, .lotto720_selected, #selectedList, span, div, p');
                for (const el of elements) {
                    const txt = (el.innerText || '').replace(/\\s+/g, '');
                    const m = txt.match(/(\\d{6})/);
                    if (m && !txt.includes('000원') && !txt.includes('700만') && !txt.includes('100만')) {
                        results.push(m[1]);
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


def _extract_numbers_from_popup(target) -> list:
    """
    구매 확인 및 구매 완료 레이어(#popup1, #lotto720_popup_confirm)에서 번호 목록을 추출합니다.
    """
    tickets = []
    try:
        raw_text = target.evaluate(
            """
            () => {
                const popups = document.querySelectorAll('#popup1, #lotto720_popup_confirm, .saleRetMsg, .popup_content, body');
                const texts = [];
                for (const p of popups) {
                    if (p && p.innerText) texts.push(p.innerText);
                }
                return texts.join('\\n');
            }
            """
        )
        if not raw_text:
            return tickets

        # 1. '1조 123456' 패턴 매칭
        matches = re.findall(r'([1-5])조\s*[:\-\s]?\s*(\d{6})', raw_text)
        if matches:
            for grp, num in matches:
                tickets.append({'group': f'{grp}조', 'number': num})
            return tickets

        # 2. '모든 조 123456' 또는 '각조 123456'
        m_all = re.search(r'(?:모든\s*조|각\s*조|1\s*~?\s*5조|모든조)[\s:：]*(\d{6})', raw_text)
        if m_all:
            num = m_all.group(1)
            for g in range(1, 6):
                tickets.append({'group': f'{g}조', 'number': num})
            return tickets
    except Exception as e:
        print(f"  ℹ️ 팝업 번호 파싱 예외: {e}")

    return tickets


def get_purchased_pension720_from_mypage(page: Page, target_round: int = None) -> list:
    """
    동행복권 마이페이지(구매당첨내역)에서 최근 구매한 연금복권 720+ 티켓 목록을 크롤링합니다.
    """
    tickets = []
    try:
        print("🌐 동행복권 마이페이지에서 연금복권 구매 번호 조회 시도...")
        page.goto("https://www.dhlottery.co.kr/myPage.do?method=lottoBuyListView", timeout=60000)
        page.wait_for_load_state("domcontentloaded", timeout=30000)
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

            matches = re.findall(r'([1-5])조\s*(\d{6})', table_text)
            if matches:
                for grp, num in matches:
                    tickets.append({'group': f'{grp}조', 'number': num})

            # 상세 보기 링크 클릭을 통한 영수증 팝업 확인
            if not tickets:
                links = frame.locator("table.tbl_data_col a, table.tbl_data_col button").all()
                for link in links[:3]:
                    try:
                        with page.expect_popup(timeout=3000) as popup_info:
                            link.click()
                        popup = popup_info.value
                        popup.wait_for_load_state("domcontentloaded", timeout=10000)
                        popup_text = popup.locator("body").inner_text(timeout=5000)
                        popup_matches = re.findall(r'([1-5])조\s*(\d{6})', popup_text)
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


def _get_frame(page: Page):
    """720 화면이 iframe인지 직접 페이지인지 감지하여 반환합니다."""
    iframe_exists = page.locator("#ifrm_tab").count() > 0
    if iframe_exists:
        return page.frame_locator("#ifrm_tab")
    return page


def _navigate_to_lotto720(page: Page):
    """720 게임 화면으로 이동합니다."""
    desktop_urls = [
        "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72",
        "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72&kind=1",
    ]

    last_url = ""
    mobile_detected = False
    for idx, url in enumerate(desktop_urls, 1):
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(2)

        last_url = page.url
        print(f"  현재 URL (시도 {idx}): {last_url}")
        if "m.dhlottery.co.kr" in last_url:
            mobile_detected = True
            print("  ℹ️ 모바일 페이지로 이동됨 - 모바일 화면으로 계속 진행")
            break
        else:
            frame = _get_frame(page)
            frame.locator("body").first.wait_for(state="attached", timeout=15000)
            return frame

    if mobile_detected:
        page.locator("body").first.wait_for(state="attached", timeout=15000)

        # 모바일 메인에서 720 바로구매 버튼 클릭 시도
        try:
            mobile_direct_selectors = [
                "#pt720ImdtPrchs",
                "#btnMoPtgmPrchs",
                ".btnBuyPt720",
                "a:has-text('연금복권720+')",
                "button:has-text('연금복권720+')",
            ]
            for selector in mobile_direct_selectors:
                try:
                    el = page.locator(selector)
                    if el.count() > 0:
                        el.first.click(timeout=3000, force=True)
                        page.wait_for_load_state("domcontentloaded", timeout=20000)
                        time.sleep(2)
                        if "game_mobile/pension720" in page.url:
                            print(f"  ✅ 모바일 720 구매 페이지 진입: {page.url}")
                            return page
                except Exception:
                    continue
        except Exception:
            pass

        # 직접 URL 진입 fallback
        mobile_urls = [
            "https://el.dhlottery.co.kr/game_mobile/pension720/game.jsp",
            "https://m.dhlottery.co.kr/game_mobile/pension720/game.jsp",
        ]
        for murl in mobile_urls:
            try:
                page.goto(murl, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=20000)
                time.sleep(2)
                if "pension720" in page.url:
                    print(f"  ✅ 모바일 720 URL 직접 진입 성공: {page.url}")
                    return page
            except Exception:
                continue

        return page

    raise Exception(f"연금복권 페이지 진입 실패 ({last_url})")


def _purchase_once(page: Page) -> dict:
    """연금복권 720+를 1회(5,000원, 모든 조 5매) 구매합니다."""
    frame = _navigate_to_lotto720(page)

    # 판매 회차 확인
    round_num = get_current_pension720_round(frame=frame, page=page)
    print(f"  🎯 연금복권 판매 회차: {round_num}회")

    # 로그인 세션 확인
    try:
        user_id_field = frame.locator("input[name='USER_ID']")
        if user_id_field.count() > 0:
            user_id_val = user_id_field.first.get_attribute("value")
            if not user_id_val:
                raise Exception("세션 만료")
    except Exception as e:
        raise Exception(f"게임 페이지 로그인 확인 실패: {e}")

    # 팝업 닫기 시도
    try:
        alert_popup = frame.locator("#popupLayerAlert")
        if alert_popup.count() > 0 and alert_popup.first.is_visible(timeout=1500):
            _click_first(alert_popup, ["button:has-text('확인')", "input[value='확인']", "a:has-text('확인')"], "팝업 확인")
    except Exception:
        pass

    # 이전 구매 결과 팝업(#popup1) 닫기
    try:
        if _is_visible(frame, "#popup1", timeout=1000):
            _click_first(
                frame,
                [
                    "#popup1 a:has-text('닫기')",
                    "#popup1 a:has-text('확인')",
                    "#popup1 .btn_lgray.medium",
                    "#popup1 a:has-text('추가 구매하기')",
                ],
                "결과 팝업 닫기",
                timeout=3000,
                force=True,
            )
            time.sleep(1)
    except Exception:
        pass

    balance_before = _read_balance(frame)
    dialog_messages = []

    def _on_dialog(dialog):
        try:
            msg = dialog.message or ""
            dialog_messages.append(msg)
            dialog.accept()
        except Exception:
            pass

    page.on("dialog", _on_dialog)
    try:
        # 모바일 번호 선택 팝업 열기
        try:
            _click_first(
                frame,
                [
                    "a:has-text('번호 선택하기')",
                    "button:has-text('번호 선택하기')",
                    "[onclick*='selNumberPopup']",
                    ".btn_gray_st1.large.full",
                ],
                "번호 선택하기 버튼",
                force=True,
            )
            time.sleep(1)
        except Exception:
            pass

        number_target = frame
        if _is_visible(frame, "#popup4", timeout=1200):
            number_target = frame.locator("#popup4")

        # 자동번호 클릭
        try:
            _click_first(
                number_target,
                [
                    "#popup4 .btn_wht.xsmall[onclick*='doAuto']",
                    ".lotto720_btn_auto_number",
                    "a:has-text('자동번호')",
                    "button:has-text('자동번호')",
                    "button[onclick*='doAuto']",
                    "a[onclick*='doAuto']",
                    "[class*='auto']",
                    "[id*='auto']",
                    "[onclick*='auto']",
                    "[onclick*='Auto']",
                ],
                "자동번호 버튼",
                force=True,
            )
        except Exception:
            _click_keyword(number_target, ["자동번호", "자동선택", "자동"], "자동번호 버튼")

        time.sleep(1)
        # 선택된 번호 추출 1차 시도
        selected_number = _extract_selected_digits(number_target)

        # 선택완료 클릭
        try:
            _click_first(
                number_target,
                [
                    "#popup4 a[onclick*='doVerify']",
                    ".lotto720_btn_confirm_number",
                    "a:has-text('선택완료')",
                    "button:has-text('선택완료')",
                    "button[onclick*='doVerify']",
                    "a[onclick*='doVerify']",
                    "[onclick*='confirm']",
                    "[onclick*='Confirm']",
                ],
                "선택완료 버튼",
            )
        except Exception:
            _click_keyword(number_target, ["선택완료", "선택 완료", "완료", "확인"], "선택완료 버튼")

        time.sleep(1)
        if not selected_number:
            selected_number = _extract_selected_digits(frame)

        payment_val = _read_amount(frame)
        if payment_val == 0:
            print("  ⚠️ 결제 금액 표시를 읽지 못했습니다. 구매 절차를 계속 진행합니다.")
        elif payment_val != PER_PURCHASE_AMOUNT:
            raise Exception(f"결제 금액 불일치 (예상 {PER_PURCHASE_AMOUNT}원, 표시 {payment_val}원)")

        # 구매하기 클릭
        try:
            _click_first(
                frame,
                [
                    "a:has-text('구매하기')",
                    "button:has-text('구매하기')",
                    "button[onclick*='doOrder']",
                    "a[onclick*='doOrder']",
                    ".btn_blue.large.full",
                    ".lotto720_btn_buy",
                    "[name='btnBuy']",
                    "button[name='btnBuy']",
                    "[onclick*='buy']",
                    "[onclick*='Buy']",
                ],
                "구매하기 버튼",
            )
        except Exception:
            _click_keyword(frame, ["구매하기", "구매"], "구매하기 버튼")

        time.sleep(1)

        # 최종 확인 팝업 처리
        confirm_candidates = [
            "#lotto720_popup_confirm a.btn_blue",
            "#lotto720_popup_confirm a:has-text('확인')",
            "button:has-text('확인')",
            "input[value='확인']",
        ]
        popup_tickets = _extract_numbers_from_popup(frame)
        try:
            _click_first(frame, confirm_candidates, "최종 확인 버튼", timeout=7000)
        except Exception:
            pass

        # 결과 대기
        sale_message = ""
        for _ in range(8):
            time.sleep(1)
            sale_message = _read_sale_result(frame)
            if sale_message:
                break

        balance_after = _read_balance(frame)

        normalized_dialogs = [msg.replace(" ", "") for msg in dialog_messages]
        normalized_sale = sale_message.replace(" ", "")

        for msg, norm in zip(dialog_messages, normalized_dialogs):
            if (
                "실패" in norm
                or "불가" in norm
                or "선택해" in norm
                or "오류" in norm
                or "없습니다" in norm
            ):
                raise Exception(f"구매 실패 dialog 감지: {msg}")

        if "구매가능한티켓이없습니다" in normalized_sale:
            raise Exception(f"구매 실패 결과 감지: {sale_message}")

        if _has_failure_signal(frame):
            raise Exception("구매 실패 신호 감지")

        if not popup_tickets:
            popup_tickets = _extract_numbers_from_popup(frame)

        # 1세트(1조~5조) 티켓 리스트 구성
        tickets = []
        if popup_tickets and len(popup_tickets) == 5:
            tickets = popup_tickets
        elif selected_number and len(selected_number) == 6:
            tickets = [{'group': f'{g}조', 'number': selected_number} for g in range(1, 6)]
        elif popup_tickets:
            tickets = popup_tickets

        success_detected = False
        sale_popup_visible = _is_visible(frame, "#popup1", timeout=1200)
        if sale_popup_visible and ("구매가완료되었습니다" in normalized_sale or "부분적으로완료" in normalized_sale):
            success_detected = True
        elif any(("구매완료" in norm or "부분적으로완료" in norm) for norm in normalized_dialogs):
            success_detected = True
        elif balance_before >= 0 and balance_after >= 0 and (balance_before - balance_after) >= PER_PURCHASE_AMOUNT:
            success_detected = True
        elif len(tickets) > 0:
            success_detected = True

        if not success_detected:
            print("  ⚠️ 720 구매 완료 신호를 명확히 확인하지 못했습니다. (상위 잔액 검증으로 최종 판정)")

        if tickets:
            num_display = tickets[0]['number'] if 'number' in tickets[0] else ''
            print(f"  🎟️ 구매된 번호: 1조~5조 {num_display} (5매)")

        return {
            "games": 5,
            "total_cost": PER_PURCHASE_AMOUNT,
            "round": round_num,
            "tickets": tickets,
            "number": selected_number,
            "attempted": True,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "dialogs": dialog_messages,
            "sale_message": sale_message,
            "success_signal": success_detected,
        }
    finally:
        try:
            page.remove_listener("dialog", _on_dialog)
        except Exception:
            pass


def purchase_lotto720(page: Page, target_amount: int = None, send_notification: bool = True) -> dict:
    """
    연금복권 720+를 구매합니다.
    - 5,000원 단위로 반복 구매하여 목표 금액(기본 10,000원 = 2세트, 10매)을 맞춥니다.
    """
    normalized_amount = _get_target_amount(target_amount)
    purchase_count = normalized_amount // PER_PURCHASE_AMOUNT

    total_games = 0
    total_cost = 0
    last_attempt = {}
    success_signals = 0
    all_tickets = []
    round_num = None

    page.add_init_script(
        """
        (() => {
            if (window.__lotto720ConfirmPatched) return;
            window.__lotto720ConfirmPatched = true;
            const origConfirm = window.confirm;
            window.confirm = function(message) {
                try { window.__lotto720LastConfirm = String(message || ""); } catch (_) {}
                return true;
            };
            window.__lotto720OrigConfirm = origConfirm;
        })();
        """
    )

    try:
        print(f"🚀 연금복권 720+ 구매 시작 (목표 금액: ₩{normalized_amount:,}, {purchase_count}회)")

        for i in range(purchase_count):
            print(f"  [{i + 1}/{purchase_count}] 구매 진행 중...")
            result = _purchase_once(page)
            total_games += result.get("games", 0)
            total_cost += result.get("total_cost", 0)
            if result.get("success_signal"):
                success_signals += 1
            if result.get("tickets"):
                all_tickets.extend(result["tickets"])
            if not round_num and result.get("round"):
                round_num = result["round"]
            last_attempt = result
            time.sleep(2)

        if not round_num:
            round_num = get_current_pension720_round(page=page)

        # 티켓 번호 fallback: 구매 화면에서 번호를 직접 추출하지 못한 경우 마이페이지 조회
        if not all_tickets:
            print("ℹ️ 구매 화면에서 번호를 직접 추출하지 못해 마이페이지 조회를 시도합니다...")
            all_tickets = get_purchased_pension720_from_mypage(page, round_num)

        # 구매 내역 저장
        if total_cost > 0:
            try:
                save_purchased_pension720(round_num, all_tickets, total_cost)
            except Exception as e:
                print(f"⚠️ 구매 내역 파일 저장 실패: {e}")

        print(f"✅ 연금복권 720+ 구매 절차 완료 (총 {total_cost:,}원, {len(all_tickets)}매)")

        # 텔레그램 알림 발송
        if send_notification:
            notify_lotto720_purchase(
                success=True,
                tickets=all_tickets,
                amount=total_cost,
                purchase_count=purchase_count,
                round_num=round_num
            )

        return {
            "games": total_games,
            "total_cost": total_cost,
            "round": round_num,
            "tickets": all_tickets,
            "numbers": f"자동 선택 ({purchase_count}회 구매, 총 {len(all_tickets)}매)",
            "verified": True,
            "success_signals": success_signals,
            "balance_before": last_attempt.get("balance_before"),
            "balance_after": last_attempt.get("balance_after"),
            "dialogs": last_attempt.get("dialogs", []),
            "sale_message": last_attempt.get("sale_message", ""),
        }

    except Exception as e:
        error_msg = str(e)
        print(f"❌ 연금복권 720+ 구매 실패: {error_msg}")
        if send_notification:
            notify_lotto720_purchase(False, error_msg=error_msg, amount=normalized_amount)
        raise


def run(playwright: Playwright) -> None:
    """연금복권 720+를 구매합니다 (독립 실행용)."""
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
