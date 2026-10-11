FROM python:3.11-slim

ENV LANG=C.UTF-8

# ffmpeg: moment clips transcode to H.264 720p mp4 on upload — phones record
# HEVC .mov that Chrome-based wall panels cannot decode, and raw uploads are
# 10x the size. (services/storage.py falls back to store-as-is without it.)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Chromium for browse missions (services/browse.py). Headless only. The
# Playwright CDN timed out from the HA box at build time (30 s per try), so:
# a longer connection timeout, then Debian's chromium as the fallback (the
# runner launches it by executable_path when the bundle is absent), and the
# step never fails the build — without any browser the runner refuses
# honestly with "no browser on this box".
ENV PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=300000
RUN (python -m playwright install --with-deps chromium \
     || (echo "Playwright's Chromium download failed; installing Debian's chromium instead" \
         && apt-get update && apt-get install -y --no-install-recommends chromium)) \
    ; rm -rf /var/lib/apt/lists/*

COPY . .

RUN chmod a+x /app/run.sh

CMD [ "/app/run.sh" ]
