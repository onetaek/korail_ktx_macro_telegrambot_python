FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 애플리케이션 전용 비-root 사용자
RUN addgroup --system app && adduser --system --ingroup app app

# korail-mobile-api를 GitHub에서 설치하기 위해 git이 필요합니다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY app ./app

RUN chown -R app:app /app
USER app

CMD ["python", "-m", "app.main"]
