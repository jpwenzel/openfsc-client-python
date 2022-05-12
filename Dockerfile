FROM python:3.9-alpine
LABEL maintainer="jp@pace.car"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip3 install pipenv

WORKDIR /app
COPY Pipfile Pipfile.lock ./
COPY openfsc-client ./openfsc-client/
RUN pipenv install --deploy

CMD ["pipenv", "run", "python3", "openfsc-client/openfsc-client.py"]
