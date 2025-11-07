FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# (opcional) ferramentas para compilar wheels nativos
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# deps (usa seu requirements.prod.txt) + gunicorn
COPY requirements.deploy.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# código
COPY app ./app
COPY config.py run.py ./

# diretório do SQLite (montado via volume /data)
RUN mkdir -p /data

EXPOSE 8080
CMD ["gunicorn","-w","2","-k","gthread","-b","0.0.0.0:8080","app.wsgi:app"]
