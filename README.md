# KORAIL KTX 예약 프로그램

KORAIL 열차를 조회하고 선택한 열차의 미결제 예약을 시도하는 개인용 프로그램입니다.

- GUI 방식: Windows 사용자가 가장 쉽게 사용
- Telegram 방식: Telegram 채팅으로 원격 사용
- 서버 방식: Linux 서버에서 Telegram 봇을 상시 실행
- 결제·환불은 지원하지 않음
- 예약 상태는 메모리에만 저장

## 1. GUI로 사용하기

가장 쉬운 사용 방법입니다. GUI 실행파일을 사용하면 사용자 PC에 Python이 없어도 됩니다.

### 실행파일 사용

아래 링크를 클릭하면 최신 Release의 GUI 실행파일을 바로 다운로드할 수 있습니다.

[최신 GUI 실행파일 다운로드](https://github.com/onetaek/korail_ktx_macro_telegrambot_python/releases/latest/download/KorailReservationGui.exe)

또는 [Releases 목록](https://github.com/onetaek/korail_ktx_macro_telegrambot_python/releases)에서 원하는 버전을 선택할 수 있습니다.

다운로드한 파일을 실행하면 됩니다.

```text
KorailReservationGui.exe
```

사용자 PC에는 Python, Git, 가상환경, `.env`가 필요하지 않습니다. GUI에서 KORAIL ID·비밀번호와 예약 조건을 직접 입력합니다.

GUI에서 다음 정보를 입력합니다.

- KORAIL ID·비밀번호
- 출발일·출발역·도착역
- 출발·종료 시간
- 열차 종류·좌석 옵션
- 조회 주기·Jitter·최대 실행 시간

사용 순서:

1. `1. 열차 조회` 클릭
2. 조회 결과에서 예약할 열차를 하나 이상 선택
3. 여러 열차는 `Ctrl` 또는 `Shift`로 다중 선택
4. `2. 선택 열차 예약 시작` 클릭
5. 예약을 중지하려면 `3. 예약 취소` 클릭

GUI는 KORAIL 인증정보를 파일에 저장하지 않고 실행 중 메모리에서만 사용합니다.

### GUI 실행파일 직접 만들기

개발 환경에서 Python과 Git을 준비한 뒤 실행합니다.

```powershell
git clone https://github.com/onetaek/korail_ktx_macro_telegrambot_python.git
cd korail_ktx_macro_telegrambot_python

python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\\.venv\\Scripts\\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
pyinstaller --noconfirm --clean --onefile --windowed --name KorailReservationGui gui_main.py
```

생성된 실행파일:

```text
dist\\KorailReservationGui.exe
```

### GitHub Release 등록

버전 태그를 GitHub에 push하면 GitHub Actions가 Windows 환경에서 GUI 실행파일을 자동으로 빌드하고 Release에 첨부합니다.

```powershell
git add .
git commit -m "release: prepare GUI executable distribution"
git tag v1.0.0
git push origin HEAD
git push origin v1.0.0
```

이후 GitHub 저장소의 `Releases`에서 `KorailReservationGui.exe`를 사용자에게 배포합니다. Release workflow 파일은 [gui-release.yml](.github/workflows/gui-release.yml)입니다.

## 2. Telegram으로 사용하기

Telegram 봇을 통해 원격으로 예약하려는 경우 사용합니다.

### 설치

```powershell
git clone https://github.com/onetaek/korail_ktx_macro_telegrambot_python.git
cd korail_ktx_macro_telegrambot_python

python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\\.venv\\Scripts\\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`korail-mobile-api`는 PyPI가 아닌 GitHub 저장소에서 `requirements.txt`를 통해 설치됩니다.

### 환경변수 설정

```powershell
Copy-Item .env.example .env
notepad .env
```

`.env`에 입력합니다.

```env
TELEGRAM_BOT_TOKEN=BotFather에서_받은_토큰
TELEGRAM_ALLOWED_CHAT_IDS=본인의_숫자_chat_id
KORAIL_ID=코레일_아이디
KORAIL_PASSWORD=코레일_비밀번호
```

`.env`는 비밀번호와 토큰을 포함하므로 GitHub에 올리면 안 됩니다. `.gitignore`에 의해 제외됩니다.

### 실행

```powershell
python -m app.main
```

Telegram 명령:

- `/start`: 예약 조건 입력 시작
- `/status`: 예약 상태 확인
- `/config`: 조회 주기·Jitter·최대 실행 시간 변경
- `/cancel`: 입력 또는 예약 작업 취소
- `/help`: 명령어 안내

## 3. Docker로 서버에 배포하기

서버에는 Docker와 Docker Compose Plugin이 설치되어 있어야 합니다. `Dockerfile`은 Python 3.11 기반 이미지에서 GitHub의 `korail-mobile-api`를 설치하고, 비-root 사용자로 Telegram 봇을 실행합니다.

### 서버 준비

Ubuntu 기준으로 Docker를 설치한 뒤 저장소를 받습니다.

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker

git clone https://github.com/onetaek/korail_ktx_macro_telegrambot_python.git
cd korail_ktx_macro_telegrambot_python
```

### 환경변수 설정

```bash
cp .env.example .env
nano .env
```

`.env`에 Telegram과 KORAIL 계정 정보를 입력합니다.

```env
TELEGRAM_BOT_TOKEN=BotFather에서_받은_토큰
TELEGRAM_ALLOWED_CHAT_IDS=본인의_숫자_chat_id
KORAIL_ID=코레일_아이디
KORAIL_PASSWORD=코레일_비밀번호
```

### 이미지 실행

`docker-compose.prod.yml`은 `${IMAGE_NAME}:${IMAGE_TAG}` 이미지를 사용합니다.

```bash
export IMAGE_NAME=your-dockerhub-id/korail-ktx-macro
export IMAGE_TAG=latest

docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Private Registry 이미지를 사용하는 경우 먼저 로그인합니다.

```bash
docker login
```

상태와 로그 확인:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f korail-macro
```

중지·재시작:

```bash
docker compose -f docker-compose.prod.yml restart
docker compose -f docker-compose.prod.yml down
```

### 서버에서 직접 이미지 빌드하기

Docker Hub에 이미지를 올리지 않고 서버에서 직접 빌드할 수도 있습니다.

```bash
docker build -t korail-ktx-macro:local .
IMAGE_NAME=korail-ktx-macro IMAGE_TAG=local docker compose -f docker-compose.prod.yml up -d
```

코드나 의존성이 변경되면 다시 빌드합니다.

```bash
docker build --no-cache -t korail-ktx-macro:local .
IMAGE_NAME=korail-ktx-macro IMAGE_TAG=local docker compose -f docker-compose.prod.yml up -d --force-recreate
```

## 조회 설정

초기값은 `.env`에서 설정합니다.

```env
KORAIL_SEARCH_INTERVAL_SECONDS=1
KORAIL_SEARCH_JITTER_MIN_SECONDS=0.1
KORAIL_SEARCH_JITTER_MAX_SECONDS=0.5
KORAIL_MAX_SEARCH_MINUTES=120
```

GUI에서는 입력창에서 직접 변경할 수 있습니다. Telegram에서는 `/config` 입력 후 기본 주기, Jitter 최소값, Jitter 최대값, 최대 실행 시간을 순서대로 입력합니다.

## 테스트

```powershell
python -m pytest
```

## 주의 사항

`korail-mobile-api`는 KORAIL의 공식 공개 API가 아닌 비공식 클라이언트입니다. 예약 요청은 실제 계정 상태를 변경할 수 있으므로 개인 계정으로 사용하고, KORAIL 정책과 서버 부하를 고려해야 합니다.

프로그램이 종료되면 메모리에 저장된 대화와 예약 작업은 사라집니다. 결제와 환불은 자동으로 진행하지 않습니다.
