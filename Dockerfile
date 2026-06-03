# Shared image for any *red bot.
# Built per-service from docker-compose.yml, e.g.:
#   build:
#     context: .
#     args: { BOT: Vred, PYTHON_VERSION: "3.12" }
ARG PYTHON_VERSION=3.14
FROM python:${PYTHON_VERSION}-slim

ARG BOT
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install deps first for better layer caching
COPY ${BOT}/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code (secrets are excluded via .dockerignore and injected at runtime)
COPY ${BOT}/ ./

CMD ["python", "main.py"]
