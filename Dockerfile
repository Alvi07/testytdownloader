# Production Dockerfile for YouTube & Media Downloader on Render.com
FROM python:3.11-slim

# Avoid prompts from debian apt
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies including FFmpeg + unzip for Deno
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Deno (required by modern yt-dlp for YouTube JS challenges)
RUN curl -fsSL https://github.com/denoland/deno/releases/download/v2.1.4/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip \
    && unzip /tmp/deno.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip \
    && deno --version

# Set working directory
WORKDIR /app

# Install Python requirements (yt-dlp[default] includes ejs helper)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -U "yt-dlp[default]" \
    && pip install --no-cache-dir -U --pre "yt-dlp[default]" || true \
    && yt-dlp --version \
    && deno --version

# Copy application source code
COPY . .

# Create temp downloads directory with full permissions
RUN mkdir -p /app/temp_downloads && chmod 777 /app/temp_downloads

# Default port
ENV PORT=8000
EXPOSE 8000

# Start FastAPI application using Uvicorn
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
