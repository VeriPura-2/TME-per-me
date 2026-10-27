FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vialibera ./vialibera
ENV GCP_PROJECT=181473838676
CMD ["python", "-m", "vialibera.app"]
