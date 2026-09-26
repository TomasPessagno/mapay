FROM python:3.11-slim
WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends gdal-bin libgdal-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PORT=8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
