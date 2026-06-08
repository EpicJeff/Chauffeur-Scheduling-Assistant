FROM python:3.11-slim

ENV LANG C.UTF-8

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod a+x /app/run.sh

CMD [ "/app/run.sh" ]
