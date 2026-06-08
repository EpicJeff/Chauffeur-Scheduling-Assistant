ARG BUILD_FROM=ghcr.io/hassio-addons/base-python/amd64:17.0.0
FROM $BUILD_FROM

ENV LANG C.UTF-8
ENV PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod a+x /app/run.sh

CMD [ "/app/run.sh" ]
