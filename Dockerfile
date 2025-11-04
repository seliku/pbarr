FROM python:3.11-slim

WORKDIR /app

# System dependencies (including ffmpeg für yt-dlp)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    curl \
    redsocks \
    iptables \
    && rm -rf /var/lib/apt/lists/*

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

# yt-dlp installieren (wichtig!)
RUN pip install --no-cache-dir yt-dlp

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code and migrations
COPY app/ app/
COPY migrate_*.py ./

# Static files
COPY app/static/ app/static/

# Volumes
RUN mkdir -p /app/downloads /app/logs /app/data

EXPOSE 8000
