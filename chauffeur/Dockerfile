ARG BUILD_FROM=ghcr.io/hassio-addons/base-python:13.2.0
FROM $BUILD_FROM

ENV LANG C.UTF-8

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod a+x /app/run.sh

CMD [ "/app/run.sh" ]
