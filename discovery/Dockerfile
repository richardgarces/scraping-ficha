FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sitemap_discovery.py /app/
ENTRYPOINT ["python", "/app/sitemap_discovery.py"]
