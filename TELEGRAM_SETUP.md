# 📱 텔레그램 알림 설정 가이드

로또 구매 시스템이 실행될 때마다 텔레그램으로 알림을 받을 수 있습니다.

## 🤖 1. 텔레그램 봇 생성

### 1단계: BotFather와 대화
1. 텔레그램 앱에서 [@BotFather](https://t.me/BotFather) 검색
2. `/start` 명령어 입력
3. `/newbot` 명령어 입력

### 2단계: 봇 이름 설정
- **Bot name**: `내 로또봇` (원하는 이름)
- **Bot username**: `my_lotto_bot` (영문, 숫자, 언더스코어만 가능, 반드시 `bot`으로 끝나야 함)

### 3단계: 토큰 저장
BotFather가 다음과 같은 토큰을 제공합니다:
```
1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
```
이 토큰을 복사해서 저장해두세요! (이것이 `TELEGRAM_BOT_TOKEN`)

## 💬 2. Chat ID 확인

### 1단계: 봇과 대화 시작
1. BotFather가 제공한 봇 링크 클릭 (예: `t.me/my_lotto_bot`)
2. **START** 버튼 클릭
3. 아무 메시지나 입력 (예: "안녕")

### 2단계: Chat ID 확인
웹 브라우저에서 다음 URL로 접속:
```
https://api.telegram.org/bot[봇토큰]/getUpdates
```

예시:
```
https://api.telegram.org/bot1234567890:ABCdefGHIjklMNOpqrsTUVwxyz/getUpdates
```

### 3단계: Chat ID 찾기
JSON 응답에서 `"chat":{"id":` 부분을 찾습니다:
```json
{
  "ok": true,
  "result": [
    {
      "update_id": 123456789,
      "message": {
        "message_id": 1,
        "from": {...},
        "chat": {
          "id": 987654321,  ← 이 숫자가 Chat ID
          "first_name": "홍길동",
          "type": "private"
        },
        "text": "안녕"
      }
    }
  ]
}
```

이 숫자(`987654321`)가 `TELEGRAM_CHAT_ID`입니다!

## 🔧 3. 환경 변수 설정

### GitHub Actions 사용 시

GitHub 저장소의 **Settings > Secrets and variables > Actions**에서 다음 Secrets 추가:

| Name | Value | 예시 |
|------|-------|------|
| `TELEGRAM_BOT_TOKEN` | 봇 토큰 | `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz` |
| `TELEGRAM_CHAT_ID` | Chat ID | `987654321` |

### 로컬 실행 시

`.env` 파일에 다음 내용 추가:
```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321
```

## 📬 4. 알림 내용

설정이 완료되면 다음 알림을 받을 수 있습니다:

### 🎰 구매 시작
```
🎰 로또 자동 구매 시작

구매 프로세스를 시작합니다...
```

### 💰 예치금 확인
```
💰 예치금 확인

예치금 잔액: 35,000원
구매가능 금액: 20,000원
```

### 💳 예치금 충전
```
💳 예치금 충전 완료

충전 금액: 10,000원
```

### 🎱 로또 6/45 구매
```
🎱 로또 6/45 구매 완료

자동: 5게임

총 금액: 5,000원
```

### 🎟️ 연금복권 720+ 구매
```
🎟️ 연금복권 720+ 구매 완료

금액: 5,000원
```

### ✅ 전체 완료
```
✅ 로또 구매 완료

모든 구매 작업이 성공적으로 완료되었습니다!
```

### 🚨 오류 발생
```
🚨 오류 발생

오류 메시지...
```

## 🧪 5. 테스트

설정이 완료되면 다음 명령으로 테스트할 수 있습니다:

```bash
# 로컬에서 테스트
python src/notify_telegram.py start
```

또는 GitHub Actions에서 **Run workflow**를 실행하여 실제 알림을 확인하세요!

## ❓ 문제 해결

### 알림이 오지 않을 때
1. ✅ 봇과 대화를 시작했는지 확인 (START 버튼 클릭)
2. ✅ `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`가 올바른지 확인
3. ✅ Chat ID가 숫자인지 확인 (따옴표 없이)
4. ✅ 봇 토큰에 공백이나 줄바꿈이 없는지 확인

### Chat ID를 못 찾을 때
[@userinfobot](https://t.me/userinfobot)에게 메시지를 보내면 자신의 Chat ID를 확인할 수 있습니다.

---

**참고**: 텔레그램 알림 설정은 선택 사항입니다. 설정하지 않아도 로또 구매는 정상적으로 작동합니다.
