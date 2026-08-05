FROM python:3.11-slim

ENV LANG C.UTF-8

# ffmpeg: moment clips transcode to H.264 720p mp4 on upload — phones record
# HEVC .mov that Chrome-based wall panels cannot decode, and raw uploads are
# 10x the size. (services/storage.py falls back to store-as-is without it.)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod a+x /app/run.sh

CMD [ "/app/run.sh" ]
