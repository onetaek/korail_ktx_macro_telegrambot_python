# KORAIL KTX Telegram 예약 봇

개인 사용을 위한 Python 기반 KORAIL 열차 조회·예약 Telegram 봇입니다.

## 준비물

- Windows PC
- Python 3.11 이상
- Git
- Telegram 앱
- Telegram BotFather에서 발급한 봇 토큰
- 본인의 Telegram 숫자 chat ID
- KORAIL 계정

## 설치

PowerShell에서 순서대로 실행합니다.

```powershell
git clone https://github.com/onetaek/korail_ktx_macro_telegrambot_python.git
cd korail_ktx_macro_telegrambot_python

python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\\.venv\\Scripts\\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`korail-mobile-api`는 PyPI 패키지가 아니라 GitHub 저장소에서 설치됩니다. `requirements.txt` 설치 과정에서 자동으로 함께 설치됩니다.

## 환경변수 설정

```powershell
Copy-Item .env.example .env
notepad .env
```

`.env`에 다음 값을 입력합니다.

```env
TELEGRAM_BOT_TOKEN=BotFather에서_받은_토큰
TELEGRAM_ALLOWED_CHAT_IDS=본인의_숫자_chat_id
KORAIL_ID=코레일_아이디
KORAIL_PASSWORD=코레일_비밀번호
```

`.env`는 비밀번호와 토큰을 포함하므로 GitHub에 올리면 안 됩니다. `.gitignore`에 의해 자동으로 제외됩니다.

Telegram chat ID는 `@userinfobot` 등으로 확인할 수 있습니다.

## 실행

가상환경이 활성화된 상태에서 실행합니다.

```powershell
python -m app.main
```

로그에 Telegram polling 시작 메시지가 출력되면 정상 실행된 상태입니다. 종료하려면 `Ctrl+C`를 누릅니다.

## Docker로 실행

Docker Desktop이 실행 중인 상태에서 프로젝트 루트에서 실행합니다.

```powershell
docker compose up -d --build
docker compose logs -f korail-macro
```

`.env` 파일은 이미지에 포함하지 않고 Compose가 컨테이너 실행 시 주입합니다. 중지하려면 다음을 실행합니다.

```powershell
docker compose down
```

## 서버 배포

Docker를 사용해 컨테이너 환경에 배포할 수 있습니다. Linux 서버뿐 아니라 Docker Desktop 또는 WSL2가 구성된 Windows 환경에서도 Docker Compose와 `.env` 파일을 준비한 뒤 Docker 이미지를 pull하여 컨테이너로 실행합니다.

## Telegram 명령

- `/start`: 예약 조건 입력 시작
- `/status`: 예약 작업 상태 확인
- `/config`: 조회 주기와 최대 실행 시간 변경
- `/cancel`: 입력 또는 예약 작업 취소
- `/help`: 명령어 안내

`/start` 이후 출발일, 출발역, 도착역, 시간, 열차 종류, 좌석 조건, 인원을 입력하면 열차 목록이 표시됩니다.

열차 하나를 선택하려면 다음처럼 입력합니다.

```text
3
```

여러 열차를 선택하려면 쉼표로 구분합니다.

```text
1,4,6
```

## 조회 설정

`.env`의 초기값은 다음과 같습니다.

```env
KORAIL_SEARCH_INTERVAL_SECONDS=1
KORAIL_SEARCH_JITTER_MIN_SECONDS=0.1
KORAIL_SEARCH_JITTER_MAX_SECONDS=0.5
KORAIL_MAX_SEARCH_MINUTES=120
```

`/config`를 입력하면 다음 순서로 실행 중인 설정을 변경할 수 있습니다.

```text
기본 조회 주기(초)
Jitter 최소값(초)
Jitter 최대값(초)
최대 실행 시간(분)
```

예를 들어 `0.5`, `0.1`, `0.5`, `120`을 입력하면 실제 조회 간격은 `0.6~1.0초`가 됩니다. `/config`로 변경한 값은 즉시 적용되며, 프로그램을 재시작하면 `.env` 값으로 돌아갑니다.

## 동작 범위

- Telegram 대화 기반 예약
- 열차 조회
- 선택 열차 대상 예약 재시도
- 미결제 예약 완료 알림
- 예약 흐름 로그

결제·환불은 구현하지 않았습니다. 모든 세션과 예약 작업은 메모리에만 저장되므로 프로그램을 종료하면 사라집니다.

## 주의 사항

`korail-mobile-api`는 KORAIL의 공식 공개 API가 아닌 비공식 클라이언트입니다. 예약 요청은 실제 계정 상태를 변경할 수 있으므로 개인 계정으로 사용하고, KORAIL 정책과 서버 부하를 고려해야 합니다.

같은 Telegram 봇 토큰으로 프로그램을 여러 개 실행하면 polling 충돌이 발생할 수 있습니다.

## 테스트

```powershell
python -m pytest
```
