# 🎰 로또 자동 구매 시스템

동행복권 자동구매 시스템 - 로또 6/45 및 연금복권 720+ 자동화

> [!IMPORTANT]
> 동행복권 구매지원 도구이며, 자동구매 설정시 신중한 확인 필요
> **모든 구매 결과 및 예치금 사용 책임은 사용자 본인에게 있음**
>
> **복권 과몰입 및 중독 예방 제도 준수**
> 동행복권 제공 제도(구매 한도, 충전 제한, 이용 시간 등) 범위 내에서만 동작하도록 설계됨. 해당 제도를 우회하거나 무력화하는 기능 미포함.

## ✨ 주요 기능

### 자동화된 로또 구매 워크플로우
1. **잔액 확인** - 구매가능 금액 조회
2. **조건부 충전** - 잔액 부족 시 자동 충전 (10,000원)
3. **연금복권 720+ 구매** - 자동 구매 (5,000원)
4. **로또 6/45 구매** - 자동/수동 번호 선택 구매

### 핵심 기능
- ✅ **완전 자동화** - Playwright 기반 브라우저 자동화
- ✅ **OCR 키패드 인식** - 랜덤 키패드 자동 입력 (Tesseract)
- ✅ **결제 금액 검증** - 구매 전 금액 확인
- ✅ **GitHub Actions** - 서버 없이 클라우드에서 자동 실행
- ✅ **텔레그램 알림** - 실행 내용 실시간 알림 📱
- ✅ **유연한 설정** - 커맨드라인 인자 또는 .env 파일 지원

## 📁 프로젝트 구조

```
lotto/
├── src/                          # Python 스크립트
│   ├── balance.py               # 잔액 조회
│   ├── charge.py                # 예치금 충전 (간편 충전)
│   ├── login.py                 # 로그인 모듈
│   ├── lotto645.py              # 로또 6/45 구매
│   └── lotto720.py              # 연금복권 720+ 구매
├── scripts/                      # 실행 스크립트
│   └── purchase.sh              # 메인 워크플로우 스크립트
├── .github/workflows/            # GitHub Actions
│   └── purchase.yml             # 자동 구매 워크플로우
├── .env                          # 환경 변수 (비공개)
├── .env.example                  # 환경 변수 예시
├── requirements.txt              # Python 의존성
└── README.md                     # 설명 문서
```

## 🚀 시작하기

GitHub Actions를 이용하여 서버 없이 매주 자동으로 로또를 구매할 수 있습니다.

### 1. 저장소 Fork 또는 클론

이 저장소를 본인의 GitHub 계정으로 **Fork** 하거나 새 레포지토리에 코드를 푸시합니다.

### 2. GitHub Secrets 설정

GitHub 저장소의 **Settings > Secrets and variables > Actions**에서 `New repository secret` 클릭 후 다음 변수를 추가합니다:

| Name | Value | 설명 |
|------|-------|------|
| `USER_ID` | `your_id` | 동행복권 아이디 |
| `PASSWD` | `your_password` | 동행복권 비밀번호 |
| `CHARGE_PIN` | `123456` | 충전용 PIN 6자리 |
| `AUTO_GAMES` | `3` | (선택) 자동 게임 수 (0-5) |
| `MANUAL_NUMBERS` | `[[1,2,3,4,5,6]]` | (선택) 수동 번호 JSON |
| `TELEGRAM_BOT_TOKEN` | `123:ABC...` | (선택) 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | `987654321` | (선택) 텔레그램 Chat ID |

### 3. 워크플로우 실행

**수동 실행:**
- GitHub 저장소의 **Actions** 탭으로 이동
- **Lotto Purchase (Run on GitHub)** 워크플로우 선택
- **Run workflow** 버튼 클릭

**자동 실행 (스케줄):**
- `.github/workflows/purchase.yml` 파일 수정
- `schedule` 부분의 주석(`#`) 제거
- 원하는 시간으로 cron 설정 변경 (기본: 매주 일요일 09:00 KST)

```yaml
# 수정 전
# schedule:
#   - cron: '0 0 * * 0'

# 수정 후 (매주 일요일 오전 9시 KST)
schedule:
  - cron: '0 0 * * 0'
```

> **참고:** Cron은 UTC 기준이므로 한국 시간(KST)에서 9시간을 빼야 합니다.
> - 한국 시간 월요일 09:00 → UTC 월요일 00:00 → `0 0 * * 1`

## 📱 텔레그램 알림 설정 (선택)

로또 구매 시 실시간으로 텔레그램 알림을 받을 수 있습니다!

### 알림 내용
- 🎰 구매 프로세스 시작
- 💰 예치금 잔액 확인
- 💳 충전 완료 알림
- 🎱 로또 6/45 구매 결과
- 🎟️ 연금복권 720+ 구매 결과
- ✅ 전체 프로세스 완료
- 🚨 오류 발생 시 즉시 알림

### 설정 방법
자세한 텔레그램 봇 생성 및 설정 방법은 [TELEGRAM_SETUP.md](TELEGRAM_SETUP.md)를 참고하세요.

**간단 요약:**
1. [@BotFather](https://t.me/BotFather)에서 봇 생성 → 토큰 받기
2. 봇과 대화 시작 → Chat ID 확인
3. GitHub Secrets에 `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID` 추가

> 텔레그램 알림은 선택 사항입니다. 설정하지 않아도 로또 구매는 정상적으로 작동합니다.

## 🔧 환경 변수

### 필수 변수

| 변수 | 설명 | 예시 |
|------|------|------|
| `USER_ID` | 동행복권 아이디 | `your_id` |
| `PASSWD` | 동행복권 비밀번호 | `your_password` |
| `CHARGE_PIN` | 충전용 6자리 PIN | `123456` |

### 선택 변수

| 변수 | 설명 | 기본값 | 예시 |
|------|------|--------|------|
| `AUTO_GAMES` | 로또 6/45 자동 게임 수 | `0` | `5` |
| `MANUAL_NUMBERS` | 로또 6/45 수동 번호 (JSON) | `[]` | `[[1,2,3,4,5,6]]` |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 | `없음` | `123:ABC...xyz` |
| `TELEGRAM_CHAT_ID` | 텔레그램 Chat ID | `없음` | `987654321` |

### .env 파일 예시 (로컬 실행용)

```env
# 동행복권 계정 정보
USER_ID=myid
PASSWD=mypassword

# 간편충전 PIN (6자리)
CHARGE_PIN=123456

# 로또 6/45 설정
AUTO_GAMES=1
MANUAL_NUMBERS=[]

# 또는 수동 번호 지정
# MANUAL_NUMBERS=[[1,2,3,4,5,6], [7,8,9,10,11,12]]
```

## 📜 스크립트 설명

### Python 스크립트 (`src/`)

#### `login.py`
- 공통 로그인 모듈
- 다른 스크립트에서 import하여 사용

#### `balance.py`
- 예치금 잔액 및 구매가능 금액 조회
- 반환값: `{'deposit_balance': int, 'available_amount': int}`

#### `charge.py`
- 간편충전 기능 (가상계좌 입금 아님)
- OCR 활용 랜덤 키패드 자동 인식
- 지원 금액: 5,000원, 10,000원, 20,000원

#### `lotto645.py`
- 로또 6/45 구매
- 자동/수동 번호 선택 가능
- 결제 금액 검증

#### `lotto720.py`
- 연금복권 720+ 구매
- 임의 번호 모든 조(組) 자동 선택
- 고정 금액: 5,000원
- 결제 금액 검증

### Shell 스크립트 (`scripts/`)

#### `purchase.sh`
메인 워크플로우 스크립트:
1. 잔액 확인
2. 조건부 충전 (10,000원 미만 시)
3. 로또 720+ 구매
4. 로또 6/45 구매

## 🛠️ 기술 스택

- **Python 3.9+**
- **Playwright** - 브라우저 자동화
- **Tesseract OCR** - 키패드 숫자 인식
- **Pillow** - 이미지 처리
- **python-dotenv** - 환경 변수 관리
- **GitHub Actions** - 클라우드 자동화

## ⚠️ 주의사항

1. **간편 충전 사용**: [간편충전] 기능 사용, [가상계좌 입금] 미지원
2. **OCR 정확도**: 키패드 숫자 인식률 약 90-95%, 실패 시 재시도 또는 수동 확인 요망
3. **보안**: GitHub Secrets를 통해 민감 정보 관리, `.env` 파일 커밋 금지
4. **테스트**: 실제 사용 전 수동 워크플로우 실행으로 테스트 권장
5. **구매 한도**: 동행복권 주간 구매 한도 준수

## 🐛 트러블슈팅

### OCR 인식 실패
GitHub Actions 워크플로우에서 Tesseract가 자동으로 설치됩니다. 로컬 실행 시:

```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-kor
```

### Playwright 브라우저 오류
```bash
# 브라우저 재설치
playwright install chromium
playwright install-deps chromium
```

### GitHub Actions 워크플로우 실패
- Actions 탭에서 로그 확인
- Secrets가 올바르게 설정되었는지 확인
- 동행복권 사이트 점검 시간 확인 (매일 23:50 ~ 00:10)

## 📝 로컬 실행 (선택사항)

로컬 컴퓨터나 서버에서 직접 실행하려면:

```bash
# 저장소 클론
git clone <repository-url>
cd lotto

# 가상환경 생성 및 활성화
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium

# .env 파일 생성 및 편집
cp .env.example .env
nano .env

# 워크플로우 실행
./scripts/purchase.sh
```

## 📄 라이선스

이 프로젝트는 개인적인 용도로 자유롭게 사용할 수 있습니다. 상업적 용도나 재배포 시 원 저작자 표시를 권장합니다.

---

**면책 조항:** 이 도구는 동행복권 자동 구매를 지원하기 위한 것이며, 모든 구매 결과와 책임은 사용자에게 있습니다. 복권은 중독성이 있을 수 있으니 적절한 금액으로 즐기시기 바랍니다.
