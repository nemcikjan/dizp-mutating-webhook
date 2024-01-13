FROM python:3.12-alpine AS base

WORKDIR /app

COPY requirements.txt .

RUN pip3 install -r requirements.txt

FROM base as Prod

COPY src /app

ENTRYPOINT ["gunicorn"]

CMD ["mutating_admission_controller:admission_controller"]
