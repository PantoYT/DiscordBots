FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY client.py logic.py calendar_sync.py main.py ./
RUN python logic.py

# Secrets and state live on the volume, never in the image.
ENV VRED_DATA_DIR=/data \
    TZ=Europe/Warsaw \
    PYTHONUNBUFFERED=1
VOLUME /data

CMD ["python", "main.py"]
