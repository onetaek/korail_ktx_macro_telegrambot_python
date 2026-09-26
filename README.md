# KORAIL KTX Telegram 예약 봇

개인 사용을 위한 Python 기반 KORAIL 열차 조회·예약 봇입니다.

## 빠른 시작

Python이 이미 설치되어 있고, GitHub 저장소 주소를 알고 있다면 아래 명령만 순서대로 실행하면 됩니다.

```powershell
git clone https://github.com/onetaek/korail_ktx_macro_telegrambot_python.git
cd korail_ktx_macro_telegrambot_python

python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Copy-Item .env.example .env
notepad .env
```

`.env`에 `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_ALLOWED_CHAT_IDS`를 입력하고 저장한 뒤 실행합니다.

```powershell
python -m app.main
```

예약이 끝나거나 프로그램을 종료하려면 실행 중인 PowerShell 창에서 `Ctrl+C`를 누릅니다.

## Docker로 실행하기

Docker Desktop이 설치된 Windows PC에서는 Python 가상환경을 직접 만들지 않고 컨테이너로 실행할 수 있습니다. 이미지에는 GitHub에서 설치하는 `korail-mobile-api`와 필요한 Python 패키지가 포함됩니다.

먼저 `.env`를 준비합니다.

```powershell
Copy-Item .env.example .env
notepad .env
```

이미지를 빌드하고 컨테이너를 실행합니다.

```powershell
docker build -t korail-telegram-bot .
docker run --name korail-telegram-bot --env-file .env korail-telegram-bot
```

실행 중인 로그를 확인합니다.

```powershell
docker logs -f korail-telegram-bot
```

컨테이너를 종료하고 삭제합니다.

```powershell
docker stop korail-telegram-bot
docker rm korail-telegram-bot
```

코드나 의존성을 변경한 뒤에는 이미지를 다시 빌드합니다.

```powershell
docker build --no-cache -t korail-telegram-bot .
```

예약 상태는 메모리에만 저장되므로 컨테이너를 재시작하거나 삭제하면 진행 중인 대화와 예약 작업이 사라집니다.

- Python 3.11 이상
- Telegram Long Polling과 예약 작업을 하나의 프로세스에서 실행
- 열차 조회 후 미결제 예약을 시도하고 Telegram으로 결과 알림
- 결제·환불은 구현하지 않음

## 주의 사항

`korail-mobile-api`는 KORAIL의 공식 공개 API가 아니라 코레일톡 앱 요청을 재현하는 비공식 클라이언트입니다. 예약 요청은 실제 계정 상태를 변경할 수 있으므로 개인 계정으로 사용하고, KORAIL 이용약관과 서버 부하를 고려해야 합니다.

프로그램을 종료하거나 PC를 재부팅하면 메모리에 있던 대화 상태와 예약 작업은 사라집니다. 예약 중에는 PC와 인터넷 연결을 유지해야 하며, 같은 봇 토큰으로 프로그램을 여러 개 실행하면 Telegram polling 충돌이 발생할 수 있습니다.

## 1. 준비물

- Windows PC
- Python 3.11 이상
- Telegram 앱
- Telegram BotFather에서 발급한 봇 토큰
- 본인의 Telegram 숫자 chat ID
- KORAIL 계정

## 2. 설치

PowerShell에서 아래 명령을 순서대로 실행합니다.

```powershell
git clone https://github.com/onetaek/korail
cd korail_ktx_macro_telegrambot_python

python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt`에는 일반 PyPI 패키지와 함께 다음 GitHub 저장소 의존성이 포함되어 있습니다.

```text
git+https://github.com/yakisoba0728/korail-mobile-api.git
```

따라서 `korail-mobile-api`를 별도로 복사할 필요 없이 `pip install -r requirements.txt`만 실행하면 됩니다.

## 3. 환경변수 설정

```powershell
Copy-Item .env.example .env
notepad .env
```

`.env`에서 다음 값을 수정합니다. KORAIL ID와 비밀번호는 Telegram 대화로 입력하지 않고 `.env`에서만 관리합니다.

```env
TELEGRAM_BOT_TOKEN=BotFather에서_받은_토큰
TELEGRAM_ALLOWED_CHAT_IDS=본인의_숫자_chat_id
KORAIL_ID=코레일_아이디
KORAIL_PASSWORD=코레일_비밀번호
```

Telegram chat ID는 `@userinfobot` 등을 이용해 확인할 수 있습니다. 여러 chat ID를 허용하려면 쉼표로 구분합니다.

```env
TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321
```

`.env`에는 토큰과 개인 정보가 들어가므로 GitHub에 올리면 안 됩니다. `.gitignore`가 `.env`를 자동으로 제외합니다. 토큰을 실수로 공개했다면 BotFather에서 즉시 폐기하고 새 토큰을 발급하세요.

## 4. 실행

가상환경이 활성화된 상태에서 실행합니다.

```powershell
python -m app.main
```

이 프로그램은 웹 서버를 실행하지 않습니다. Telegram polling이 정상적으로 시작되었다는 로그가 나오면 실행된 상태입니다. 예약 중에는 실행 중인 PowerShell 창을 닫지 마세요. 종료하려면 `Ctrl+C`를 누릅니다.

## 5. Telegram 사용법

봇 채팅에서 `/start`를 입력한 뒤 안내에 따라 출발일, 출발역, 도착역, 검색 시간, 열차 종류, 좌석 조건, 승객 수를 입력합니다. KORAIL ID와 비밀번호는 `.env`의 `KORAIL_ID`, `KORAIL_PASSWORD`를 사용합니다. 이후 조회된 열차 목록에서 예약할 번호를 입력합니다.

열차 하나만 선택할 때는 다음처럼 입력합니다.

```text
3
```

여러 열차를 선택할 때는 쉼표로 구분합니다.

```text
1,4,6
```

선택한 열차가 매진되면 선택된 열차만 대상으로 설정된 주기에 따라 예약을 재시도합니다.

지원 명령:

- `/start`: 새 예약 작업 시작
- `/status`: 현재 작업 상태 확인
- `/cancel`: 실행 중인 작업 취소
- `/help`: 사용법 확인

좌석이 검색되면 미결제 예약을 시도하고, 성공 또는 실패 결과를 Telegram으로 전송합니다. 결제는 자동으로 진행하지 않습니다.

## 6. 조회 주기 설정

`.env`에서 기본 주기와 랜덤 지연 범위를 설정할 수 있습니다.

```env
KORAIL_SEARCH_INTERVAL_SECONDS=1
KORAIL_SEARCH_JITTER_MIN_SECONDS=0.1
KORAIL_SEARCH_JITTER_MAX_SECONDS=0.5
```

위 설정은 각 조회 사이에 `1.1~1.5초`를 무작위로 대기합니다. 값 변경 후에는 프로그램을 재시작해야 적용됩니다. 기본 조회 주기는 최소 1초 이상으로 설정하는 것을 권장합니다.

## 7. 로그 확인

실행 중인 PowerShell 창에서 다음과 같은 예약 흐름을 확인할 수 있습니다.

```text
Telegram update received
Conversation state changed
Reservation job created
Korail login started
Train search started
Search completed
No available train; retrying
Train selected
Reservation request started
Reservation completed
Telegram notification sent
```

비밀번호, 봇 토큰, 세션 쿠키, 전체 요청 payload는 로그에 출력하지 않습니다. KORAIL 로그인 실패 시에는 가능한 경우 오류 코드와 사용자 메시지를 기록합니다.

## 8. 테스트

```powershell
python -m pytest
```

테스트는 대화 입력과 상태 전환 같은 로컬 로직을 검증하며, 실제 KORAIL 예약 요청은 포함하지 않습니다.

## 9. 문제 해결

### 프로그램이 시작되지 않음

```powershell
.\.venv\Scripts\Activate.ps1
python -m app.main
```

실행 전에 `.env`가 프로젝트 루트에 있고, 토큰과 chat ID가 입력되어 있는지 확인합니다.

### Telegram이 응답하지 않음

1. `.env`의 `TELEGRAM_BOT_TOKEN`이 정확한지 확인합니다.
2. `TELEGRAM_ALLOWED_CHAT_IDS`에 본인의 숫자 chat ID가 있는지 확인합니다.
3. 같은 봇을 실행 중인 다른 PC나 터미널이 없는지 확인합니다.
4. 설정 변경 후 프로그램을 재시작합니다.

### GitHub 의존성 설치 실패

Python 3.11 이상인지 확인한 뒤 다시 실행합니다.

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Git이 설치되어 있어야 `git+https://...` 형식의 의존성을 받을 수 있습니다.

## 라이선스 및 책임

이 프로젝트는 개인 학습·개인 사용 목적의 비공식 도구입니다. KORAIL 정책 변경으로 동작하지 않을 수 있으며, 사용으로 발생하는 예약·계정·서비스상의 문제는 사용자가 책임져야 합니다.
