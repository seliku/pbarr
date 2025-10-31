FROM python:3.11-slim

WORKDIR /app

# System dependencies (including ffmpeg für yt-dlp)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp installieren (wichtig!)
RUN pip install --no-cache-dir yt-dlp

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app/ app/

# Volumes
RUN mkdir -p /app/downloads /app/logs /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
