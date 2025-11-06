FROM python:3.11-slim

# Build argument for version
ARG VERSION=0.0.0-dev

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    curl \
    postgresql-client \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]



# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source for version generation
COPY pyproject.toml .
COPY app/__init__.py app/__init__.py

# Generate version file from build argument
RUN echo "version = '${VERSION}'" > app/_version.py

# App code and migrations
COPY app/ app/
COPY migrate_*.py ./

# Static files
COPY app/static/ app/static/

# Volumes


EXPOSE 8000
