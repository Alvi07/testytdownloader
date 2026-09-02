#!/usr/bin/env bash
# exit on error
set -o errexit

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Download and setup static ffmpeg binary if not present
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing standalone static FFmpeg binary..."
    mkdir -p bin
    curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz | tar -xJ --strip-components=1 -C bin
    export PATH="$PWD/bin:$PATH"
fi

echo "Build completed successfully!"
