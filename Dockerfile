FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libopus0 gosu \
    && rm -rf /var/lib/apt/lists/* \
    && adduser --disabled-password --gecos "" --uid 1000 dabot

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh start.sh \
    && mkdir -p /app/data /app/logs \
    && chown -R dabot:dabot /app

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "main.py"]
