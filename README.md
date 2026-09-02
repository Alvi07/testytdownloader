# ⚡ ProStream - Next-Gen YouTube & Video Downloader

A production-grade, high-performance web application to analyze and download videos from **YouTube, YouTube Shorts, Instagram Reels, TikTok, and more** in Full HD (1080p, 720p, 480p, 360p) and studio-quality MP3 (320kbps / 192kbps).

Built with a **Modern Dark Glassmorphism HTML5/CSS3/Vanilla JS** frontend and an asynchronous **Python FastAPI + `yt-dlp` + FFmpeg** backend, engineered for 1-click deployment on **Render.com**.

---

## 🚀 Key Features

- 💎 **Ultra-Modern Glassmorphism UI**: Glowing neon gradients, backdrop blur effects, smooth micro-animations, and full mobile-first responsiveness.
- ⚡ **Asynchronous Streaming Engine**: Built with FastAPI and `yt-dlp` for lightning-fast metadata extraction and non-blocking downloads.
- 🎬 **Multi-Format Support**:
  - **Video (MP4)**: 1080p Full HD, 720p HD, 480p SD, 360p.
  - **Audio (MP3 / M4A)**: Studio 320kbps, Standard 192kbps, Lossless AAC.
- 📋 **Smart Clipboard Integration**: 1-click Paste & Analyze directly from your clipboard.
- 🕒 **Recent Downloads History**: Browser `localStorage` integration with instant re-download and history management.
- 🧹 **Automatic Storage Cleaner**: Server automatically wipes temporary media files after client download completes to maintain minimal disk footprint.
- 🛡️ **Production-Ready on Render**: Includes `Dockerfile` and `render.yaml` for zero-configuration cloud deployment.

---

## 📂 Project Structure

```
reel-downloader/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI server, static routing, and API endpoints
│   ├── config.py            # Global configuration, directory paths, and settings
│   ├── services/
│   │   ├── __init__.py
│   │   ├── downloader.py    # yt-dlp extraction & media downloading logic
│   │   └── cleaner.py       # Auto-cleanup for temporary downloaded files
│   └── utils/
│       ├── __init__.py
│       └── helpers.py       # Size, duration, count formatters & URL sanitization
├── static/
│   ├── css/
│   │   └── style.css        # Glassmorphism UI styles & animations
│   ├── js/
│   │   └── app.js           # Frontend client logic, history manager & toasts
│   └── index.html           # Main Single Page Application interface
├── Dockerfile               # Production Docker container with Python 3.11 & FFmpeg
├── render.yaml              # Render.com 1-Click Blueprint specification
├── requirements.txt         # Python dependencies
├── build.sh                 # Fallback build script for standard Linux hosting
├── .dockerignore
├── .gitignore
└── README.md
```

---

## 💻 Local Development Setup

### 1. Prerequisites
- **Python 3.10+** installed.
- **FFmpeg** installed on your system:
  - **Windows**: Install via `winget install Gyan.FFmpeg` or `choco install ffmpeg`.
  - **macOS**: `brew install ffmpeg`
  - **Linux (Ubuntu/Debian)**: `sudo apt update && sudo apt install -y ffmpeg`

### 2. Clone & Install Dependencies
```bash
# Navigate to project directory
cd reel-downloader

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Development Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Open [http://localhost:8000](http://localhost:8000) in your browser!

---

## 🌐 Deploying to Render.com (Step-by-Step Guide)

Deploying ProStream on **Render** is 100% free and takes less than 2 minutes using Docker:

### Method 1: Docker Web Service (Recommended - Fastest & Guaranteed FFmpeg)

1. **Push your code to GitHub**:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: ProStream Video Downloader"
   # Create a repository on GitHub, then link it:
   git remote add origin https://github.com/<your-username>/<your-repo-name>.git
   git branch -M main
   git push -u origin main
   ```

2. **Open Render Dashboard**:
   - Go to [dashboard.render.com](https://dashboard.render.com/) and Sign in / Sign up.
   - Click the **"New +"** button at the top right and select **"Web Service"**.

3. **Connect Your GitHub Repository**:
   - Select your newly pushed repository and click **"Connect"**.

4. **Configure Settings**:
   - **Name**: `prostream-downloader` (or any name you like).
   - **Region**: Choose the closest region (e.g. Frankfurt, Oregon, Singapore).
   - **Environment**: Select **`Docker`** *(Render will automatically detect your `Dockerfile`)*.
   - **Instance Type**: Select **`Free`**.
   - **Health Check Path**: `/api/health`

5. **Deploy**:
   - Click **"Create Web Service"**.
   - Render will build the container with Python and FFmpeg pre-configured and provide you with a live `https://prostream-downloader.onrender.com` URL!

---

### Method 2: One-Click Render Blueprint

1. Push your repository to GitHub.
2. In Render, click **"New +"** > **"Blueprint"**.
3. Connect your repository. Render will automatically read `render.yaml` and provision the web service for you without any manual input!

---

## 🛡️ API Reference

### 1. `POST /api/info`
Extracts metadata, thumbnails, duration, and available format options.
- **Request Body**:
  ```json
  { "url": "https://www.youtube.com/watch?v=..." }
  ```
- **Response**:
  ```json
  {
    "success": true,
    "data": {
      "title": "Video Title",
      "thumbnail": "https://...",
      "duration_formatted": "04:12",
      "uploader": "Channel Name",
      "view_count_formatted": "1.2M",
      "video_options": [
        { "resolution": "1080p", "quality_tag": "Full HD", "ext": "mp4" },
        { "resolution": "720p", "quality_tag": "HD", "ext": "mp4" }
      ],
      "audio_options": [
        { "format_key": "mp3_320", "title": "MP3 Audio (High Quality)", "bitrate": "320 kbps" }
      ]
    }
  }
  ```

### 2. `GET /api/download`
Streams the requested format directly to the client and triggers browser download.
- **Query Parameters**:
  - `url`: Target video URL (URL encoded).
  - `format_type`: `video` or `audio`.
  - `quality`: Quality identifier (e.g. `1080p`, `720p`, `mp3_320`, `m4a_best`).

### 3. `GET /api/health`
Health check endpoint returning `{ "status": "ok" }`.

---

## 📄 License
This project is open-source and intended for personal backups and educational purposes.
