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
         && apt-get update && apt-get install -y --no-install-recommends chromium xvfb)) \
    ; rm -rf /var/lib/apt/lists/*

# Packages added after 2.499.762 get their own layer, AFTER the heavy ones:
# editing requirements.txt invalidates the pip and Chromium layers above, and
# a full rebuild re-downloads ~60 packages and Chromium from the HA box, whose
# network has stalled mid-download (2.499.763's first build died on a 15 s
# read timeout). Add new packages here, with a longer timeout and retries.
COPY requirements-twin.txt .
RUN pip install --no-cache-dir --timeout 120 --retries 10 -r requirements-twin.txt

COPY . .

RUN chmod a+x /app/run.sh

CMD [ "/app/run.sh" ]
