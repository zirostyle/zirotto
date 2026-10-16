# zirotto 서비스 분석 및 개선 방안

## 1. 서비스 개요

**zirotto**는 동행복권(dhlottery.co.kr) 자동 구매 봇입니다. 서버 없이 GitHub Actions만으로 동작합니다.

| 항목 | 내용 |
|---|---|
| 대상 사이트 | dhlottery.co.kr (동행복권) |
| 구매 상품 | 로또 6/45 (₩1,000/게임), 연금복권 720+ (₩5,000 단위) |
| 자동화 방식 | Playwright (headless Chromium) 웹 스크래핑/조작 |
| 실행 환경 | GitHub Actions (`purchase.yml` 월 07:00 KST, `check_results.yml` 일 08:00 KST) |
| 알림 | Telegram Bot API |
| 인증 정보 | GitHub Secrets → CI에서 `.env` 파일로 생성 |
| 특수 기술 | Tesseract OCR로 충전 시 랜덤 보안 키패드 PIN 인식 |
| 코드 규모 | `src/` 9개 모듈, 약 2,844 LOC |

### 실행 흐름 (`src/auto_purchase.py:run_all_tasks`)

```
브라우저 1개 / 세션 1개로 순차 실행
  1. login()                         — 로그인 (3회 재시도)
  2. _notify_latest_lotto_result()    — 최신 당첨번호 + 내 구매내역 대조 알림
  3. 설정값 계산                       — LOTTO720_AMOUNT, AUTO_GAMES 등
  4. purchase_lotto645()              — 로또 6/45 구매 (날짜/플래그 게이팅)
  5. purchase_lotto720()              — 연금복권 720+ 구매 (잔액 차감으로 검증)
  6. 잔액 확인 → 부족 시 charge_balance() — ₩20,000 충전
```

### 모듈 구성

| 파일 | 역할 |
|---|---|
| `auto_purchase.py` | 오케스트레이터. 전체 흐름, 환경변수 파싱, 피처 플래그 |
| `login.py` | `.env` 로딩, 로그인 + 재시도 + 디버그 스크린샷 |
| `balance.py` | 예치금/구매가능 금액 스크래핑 |
| `charge.py` | 예치금 충전 + OCR 키패드 PIN 입력 (가장 취약한 경로) |
| `lotto645.py` | 로또 6/45 구매 (756줄, 최대 모듈) |
| `lotto720.py` | 연금복권 720+ 구매 (iframe/모바일 폴백, dialog 처리) |
| `check_results.py` | 당첨번호 조회 + 당첨 확인 |
| `telegram_notifier.py` | Telegram 전송 + 8종 알림 함수 |
| `notify_telegram.py` | CLI 셸 (`start`/`complete`/`error`) |

---

## 2. 발견된 문제점

### 🔴 P0 — 실제 동작에 영향을 주는 버그

#### B1. Telegram 시작/완료/에러 알림이 조용히 무시됨

`scripts/purchase.sh`가 호출하는 `notify_telegram.py`는 `telegram_notifier`만 import합니다. `telegram_notifier.py:8-9`는 **import 시점에 `os.environ`을 읽는데**, `load_dotenv()`를 호출하는 코드가 없습니다.

```python
# src/telegram_notifier.py:8-9
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
```

CI는 secrets를 `.env` 파일에 쓰기만 하고 환경변수로 export하지 않으므로, `send_telegram_message()`는 아래 가드에서 `False`를 반환하고 **로그도 남기지 않습니다.**

```python
# src/telegram_notifier.py:30-31
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    return False
```

`auto_purchase.py`에서만 알림이 동작하는 이유는 `from login import login`(line 20)이 `telegram_notifier` import보다 먼저 실행되어 우연히 `load_environment()`가 호출되기 때문입니다. **설계가 아니라 import 순서 의존성입니다.**

**영향:** 워크플로우 시작/완료/실패 알림을 한 번도 받지 못함. 실패를 인지할 수 없음.

#### B2. 당첨 "금액"이 실제로는 "장수"

`auto_purchase.py:146-149`와 `check_results.py`는 당첨 **개수**를 집계합니다.

```python
prizes[rank] = prizes.get(rank, 0) + 1   # 개수 누적
```

그런데 `telegram_notifier.py:137`은 이를 금액으로 렌더링합니다.

```python
message += f"{rank}: {amount:,}원\n"
```

**영향:** 5등 2장 당첨 시 `"5등: 2원"`이라는 메시지 전송.

#### B3. 충전이 구매 *후*에 실행됨

`README.md`와 `SETTINGS_SUMMARY.md`는 `잔액확인 → 충전 → 720 → 645` 순서로 문서화되어 있으나, 실제 코드는 `645(step 4) → 720(step 5) → 잔액/충전(step 6)` 순서입니다.

**영향:** 잔액이 부족하면 이번 주 구매가 **양쪽 다 실패**하고, 충전은 다음 주를 위해서만 이뤄집니다. 자동화의 핵심 목적이 깨집니다.

#### B4. 로또 645 성공 판정이 과도하게 관대함

`lotto645.py` 약 640번째 줄: 마이페이지 구매내역 테이블에 **행이 하나라도 있으면** 오늘 날짜가 없어도 `actual_purchased = True`로 설정합니다 (주석: "그래도 최근 내역이 있으면 일단 성공으로 간주").

**영향:** 지난주 구매 기록이 이번 주 신규 구매로 오보고됩니다. 720은 잔액 차감으로 검증하는데 645는 검증이 없어 일관성도 없습니다.

#### B5. 회차 번호를 날짜 계산으로 추정

`check_results.py:33-38`은 2002-12-07부터의 주 수로 회차를 계산합니다. API의 최신 회차를 읽지 않습니다. 3회차 하향 탐색으로 일부 보완하지만, `except: continue`(line 55)가 HTTP/JSON 오류를 삼킵니다.

**영향:** 회차 오차 시 잘못된 당첨번호 알림, 또는 조용한 실패.

#### B6. 죽은 코드 / 무의미한 조건

```python
# src/auto_purchase.py:222 — 정규식처럼 보이지만 in 연산자는 리터럴 매칭
if "구매 불가" in error_msg or "구매.*시간" in error_msg:  # 두 번째 조건은 절대 참이 안 됨
```

- `lotto720.py`의 `_navigate_to_lotto720()`에서 `else: return frame` 이후 `print("⚠️ 모바일 리다이렉트 감지...")`는 도달 불가
- `charge.py`: `re`, `Path`, `load_dotenv` 미사용 import
- `balance.py`: `Path`, `load_dotenv` 미사용 import
- `auto_purchase.py:345`: `# Test trigger Mon Jan 26 ...` 잔여 마커 주석

---

### 🟠 P1 — 안정성 / 보안

#### S1. 디버그 파일에 계정 정보 노출

`login.py`, `balance.py`, `charge.py`가 워크스페이스에 다음을 씁니다.

```
debug_before_login.png, debug_after_login.png, debug_login_page.html
debug_mypage.html, debug_charge_*.png
```

이 파일들은 **계정 ID, 예치금 잔액, 페이지 전체 HTML을 포함**하며 `.gitignore`에 없고 정리되지도 않습니다. 누군가 `upload-artifact` 스텝을 추가하면 즉시 유출됩니다.

#### S2. CI의 `.env` 생성 방식이 취약

```yaml
echo "PASSWD=${{ secrets.PASSWD }}" >> .env
```

값에 개행이나 따옴표가 있으면 깨집니다. `>>`이므로 기존 `.env`에 append됩니다.

#### S3. 예외를 무조건 삼키는 코드가 다수

`login.py:120`, `charge.py` 셀렉터 루프, `check_results.py:55,105,107` 등에 `except: pass` / `except Exception: pass`가 산재합니다. `get_my_lotto_purchases()`가 조용히 `[]`를 반환하면 "구매 내역 없음"으로 오보고됩니다.

#### S4. 멱등성 없음 — 실제 돈이 걸린 문제

`purchase.yml`에 `concurrency`가 있지만 `check_results.yml`에는 없습니다. 워크플로우를 재실행하면 **티켓을 중복 구매**합니다. dry-run 플래그도, 영수증 영속화도 없습니다.

#### S5. `time.sleep()` 기반 흐름 제어

전반적으로 Playwright의 대기/assertion 대신 `time.sleep(2~5)`를 사용합니다. 15분 job 타임아웃 하에서 느리고 레이스 컨디션에 취약합니다.

---

### 🟡 P2 — 유지보수성

#### M1. 테스트 0개

`pytest-playwright`가 `requirements.txt`에 있지만 테스트 파일이 없습니다. lint/type-check CI job도 없습니다.

#### M2. 로깅 부재

전부 `print()`입니다. 레벨, 타임스탬프, 구조화 출력이 없어 CI 로그 분석이 어렵습니다.

#### M3. 중복 로직

- 브라우저+컨텍스트+로그인 부트스트랩이 5개 모듈에 반복 (`balance.py:136`, `charge.py:303`, `lotto645.py:726`, `lotto720.py:617`, `check_results.py:250`)
- 번호 추출 로직이 `lotto645.py`(Python + JS)와 `check_results.py`에 중복
- 당첨 확인 로직이 `check_results.run()`과 `auto_purchase._notify_latest_lotto_result()`에 중복

#### M4. 과도하게 긴 함수

| 함수 | 길이 |
|---|---|
| `purchase_lotto645()` (`lotto645.py:266-723`) | 약 460줄 |
| `_purchase_once()` (`lotto720.py`) | 약 220줄 |
| `charge_deposit()` (`charge.py`) | 약 160줄 |

각각 네비게이션, 파싱, 검증, 알림이 뒤섞여 있습니다.

#### M5. 하드코딩 & 설정 불일치

- `CHARGE_AMOUNT = 20000`, `10000` 하한 (`auto_purchase.py:195-197`)
- 충전 금액 화이트리스트 `{5000, 10000, 20000}` (`charge.py:169`)
- `LOTTO645_ENABLE_FROM: "2026-02-23"`가 워크플로우에 박혀 있음 → **6/45는 해당 날짜까지 사실상 비활성**
- `AUTO_GAMES` 기본값이 코드는 `5`, README/CI는 `0` — 불일치
- `.env.example`에 `ENABLE_LOTTO645`, `LOTTO645_ENABLE_FROM` 누락

#### M6. 문서 불일치 (Doc drift)

| 항목 | README / SETTINGS_SUMMARY | FINAL_STATUS | 실제 |
|---|---|---|---|
| cron | `0 0 * * 1` | 매일 09:00 KST | `0 22 * * 0` (월 07:00 KST) |
| 실행 방식 | 스크립트 개별 실행 | — | 통합 `auto_purchase.py` |

README의 프로젝트 트리에 `auto_purchase.py`, `check_results.py`, `telegram_notifier.py`, `notify_telegram.py`가 빠져 있습니다.

#### M7. 의존성 미고정

전부 `>=`만 사용 → Playwright 업데이트 시 사이트 동작 변화 리스크. `pytest-playwright`는 미사용 의존성입니다.

---

## 3. 개선 로드맵

### Phase 1 — 즉시 수정 (P0 버그)

| # | 작업 | 파일 | 난이도 |
|---|---|---|---|
| 1 | `telegram_notifier.py`에서 환경변수를 **함수 호출 시점**에 읽도록 변경 + `load_dotenv()` 명시 호출 | `telegram_notifier.py` | S |
| 2 | 미설정 시 경고 로그 출력 (조용한 실패 제거) | `telegram_notifier.py` | S |
| 3 | 당첨 알림을 "장수"로 표기하거나 실제 당첨금 매핑 추가 | `telegram_notifier.py`, `auto_purchase.py` | S |
| 4 | **충전을 구매 전으로 이동** (잔액확인 → 충전 → 구매) | `auto_purchase.py` | M |
| 5 | 645 성공 판정에 오늘 날짜 필수 조건 적용 + 잔액 차감 검증 추가 (720과 동일하게) | `lotto645.py`, `auto_purchase.py` | M |
| 6 | 회차를 API 최신값에서 읽기 (`drwNo` 미지정 응답 활용) | `check_results.py` | S |
| 7 | 죽은 코드/미사용 import/잔여 주석 제거 | 전체 | S |

### Phase 2 — 안정성 & 보안

| # | 작업 | 난이도 |
|---|---|---|
| 8 | 디버그 파일을 `debug/` 디렉토리로 격리 + `.gitignore` 추가 + `DEBUG=1`일 때만 생성 | S |
| 9 | CI `.env` 생성을 heredoc 또는 `>` (덮어쓰기)로 변경 | S |
| 10 | `except: pass` → 구체적 예외 + 로그 남기기 | M |
| 11 | `DRY_RUN` 환경변수 추가 (구매 직전 단계까지만 실행) | M |
| 12 | 구매 영수증을 JSON으로 커밋 또는 artifact 저장 → 중복 구매 방지 가드 | M |
| 13 | `check_results.yml`에 `concurrency` 추가 | S |
| 14 | `time.sleep()` → `page.wait_for_selector()` / `expect()` 로 전환 | L |

### Phase 3 — 구조 개선

| # | 작업 | 난이도 |
|---|---|---|
| 15 | `logging` 모듈 도입 (레벨, 타임스탬프, CI 친화적 포맷) | M |
| 16 | 브라우저 세션 부트스트랩을 `session.py` 컨텍스트 매니저로 통합 | M |
| 17 | `purchase_lotto645()`를 navigate / select / verify / buy / confirm 단계로 분해 | L |
| 18 | 번호 추출 로직을 `parsers.py`로 통합 | M |
| 19 | 하드코딩 값을 `config.py`(dataclass) 로 이동 | M |
| 20 | 타입 힌트 + `mypy` 도입 | M |

### Phase 4 — 품질 게이트

| # | 작업 | 난이도 |
|---|---|---|
| 21 | 순수 로직 단위 테스트 (`check_winning`, 금액 파싱, 회차 계산, 환경변수 파싱) | M |
| 22 | 저장된 HTML fixture 기반 파서 테스트 | M |
| 23 | `ruff` + `mypy` CI job 추가 | S |
| 24 | 의존성 버전 고정 (`==`) + `pytest-playwright` 제거 or 활용 | S |
| 25 | 문서 통일 — cron, 실행 방식, 프로젝트 트리, 기본값 정정 | S |
| 26 | `.env.example`에 `ENABLE_LOTTO645`, `LOTTO645_ENABLE_FROM`, `DRY_RUN`, `DEBUG` 추가 | S |

---

## 4. 우선순위 권고

**지금 당장 고쳐야 하는 3가지:**

1. **B1 (Telegram 알림 무동작)** — 실패를 인지하지 못하는 상태. 자동화 신뢰성의 근본.
2. **B3 (충전 순서)** — 잔액 부족 시 이번 주 구매가 통째로 실패. 서비스 목적 자체가 깨짐.
3. **S4 (멱등성)** — 실제 금전 손실 위험. 워크플로우 재실행 = 중복 구매.

**주의:** 이 프로젝트는 제3자 사이트에 대한 자격증명 자동화이므로 해당 사이트 이용약관을 준수하는 범위에서만 운영해야 합니다. `README.md`의 면책 조항을 유지하세요.
