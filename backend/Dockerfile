# Same Python as CI (.github/workflows/ci-cd.yml). Every dependency ships a manylinux wheel for it
# (rasterio bundles GDAL), so no system packages or compilers are needed.
FROM python:3.14-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PORT=8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
