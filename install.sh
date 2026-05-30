#!/bin/bash
set -e

echo "Installing dependencies..."
pip3 install -r requirements.txt

echo "Downloading face landmark model..."
curl -L "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task" \
     -o face_landmarker.task

echo ""
echo "Setup complete. Run with:"
echo "  python3 face_trigger.py           # with camera preview"
echo "  python3 face_trigger.py --headless  # background mode"
