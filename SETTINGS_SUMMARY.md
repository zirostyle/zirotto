# ⚙️ 설정 요약

설정 항목의 전체 목록과 기본값입니다. 상세 설명은 [README.md](README.md) 및
[.env.example](.env.example) 참조.

## 📅 스케줄

| 워크플로우 | cron (UTC) | 실행 시각 (KST) |
|---|---|---|
| `purchase.yml` | `0 1 * * 1` | 매주 **월요일 10:00** — 두 복권 통합 구매 |
| `check_results.yml` | `0 11 * * 4` | 매주 **목요일 20:00** — 720+ 결과 확인 |
| `check_results.yml` | `0 13 * * 6` | 매주 **토요일 22:00** — 6/45 결과 확인 |
| `test.yml` | – | push / PR 시 |

## 🔐 GitHub Secrets

| Secret | 필수 | 설명 |
|---|---|---|
| `USER_ID` | ✅ | 동행복권 아이디 |
| `PASSWD` | ✅ | 동행복권 비밀번호 |
| `CHARGE_PIN` | ✅ | 간편충전 PIN 6자리 |
| `TELEGRAM_BOT_TOKEN` | – | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | – | 텔레그램 Chat ID |

## 🎛️ GitHub Variables (구매 설정)

비밀값이 아니므로 Secrets 가 아니라 **Variables** 탭에 설정합니다.

| Variable | 기본값 | 범위 / 제약 |
|---|---|---|
| `STRATEGY_GAMES` | `5` | 기댓값 최적화 번호 게임 수 |
| `AUTO_GAMES` | `0` | 사이트 자동 선택 게임 수 |
| `MANUAL_NUMBERS` | `[]` | JSON. 각 6개 / 1~45 / 중복 없음 |
| `ENABLE_LOTTO645` | `1` | `0` 이면 6/45 미구매 |
| `LOTTO645_ENABLE_FROM` | (없음) | `YYYY-MM-DD`. 이 날짜 이전엔 미구매 |
| `ENABLE_LOTTO720` | `1` | `0` 이면 720+ 미구매 |
| `LOTTO720_AMOUNT` | `5000` | **5,000원 단위** |
| `CHARGE_AMOUNT` | `10000` | `5000` / `10000` / `20000` 만 가능 |
| `MIN_BALANCE_FLOOR` | `10000` | 확보할 최소 잔액 |
| `STRATEGY_SEED` | (없음) | 지정 시 번호 생성 재현 가능 |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

> ⚠️ `STRATEGY_GAMES + AUTO_GAMES + len(MANUAL_NUMBERS)` 합계는 **최대 5게임**.
> 초과하면 실행 전 검증 단계에서 차단되고 텔레그램으로 오류가 통보됩니다.

## 🚩 실행 시 플래그 (workflow_dispatch 입력)

| 입력 | 기본 | 효과 |
|---|---|---|
| `dry_run` | `true` | 수동 실행은 기본적으로 실제 구매·충전 없이 직전 단계까지만 실행 |
| `debug` | `false` | `debug/` 에 스크린샷·HTML 저장 |

## 💸 예상 비용 (기본 설정)

| 항목 | 금액 |
|---|---|
| 로또 6/45 (전략 5게임) | 5,000원 |
| 연금복권 720+ | 5,000원 |
| **주간 구매 합계** | **10,000원** |
| 충전 발생 시 (1회) | +10,000원 |

`MIN_BALANCE_FLOOR=10000` 이므로 필요 잔액은
`max(6/45 비용 + 720+ 비용, 10000)` = 10,000원 입니다.
구매가능 금액이 이보다 적으면 `CHARGE_AMOUNT` 단위로 충전을 반복합니다 (최대 5회).

## 🔄 실행 순서

```
1. 로그인
2. 잔액 확인 → 부족 시 충전 → 재확인       ← 구매보다 먼저
3. 로또 6/45 구매
4. 연금복권 720+ 구매 → 예치금 차감으로 검증
5. 결과 요약 알림

추첨 결과는 구매 실행과 분리해 720+는 목요일, 6/45는 토요일에 각각 알립니다.
```

## 📝 설정 변경 방법

| 변경 대상 | 방법 |
|---|---|
| 스케줄 | `.github/workflows/purchase.yml` 의 `cron` |
| 구매 게임 수 / 금액 / 충전액 | GitHub **Variables** (코드 수정 불필요) |
| 로컬 실행 설정 | `.env` 파일 |

## ✅ 검증 상태

- 테스트 120개 통과 (`pytest -q`)
- 린트 통과 (`ruff check src tests`)
- push / PR 시 `test.yml` 에서 자동 실행
