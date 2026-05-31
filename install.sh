#!/bin/bash
set -e

echo "Installing dependencies..."
pip3 install -r requirements.txt

echo "Downloading face landmark model..."
curl -L "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task" \
     -o face_landmarker.task

# ── LaunchAgent（ログイン時自動起動）セットアップ ──────────────────────────
PYTHON_PATH="$(which python3)"
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/app.py"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/com.aquaface.app.plist"

mkdir -p "$PLIST_DIR"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.aquaface.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>${SCRIPT_PATH}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/aquaface.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/aquaface.log</string>
</dict>
</plist>
EOF

# 既にロード済みなら一度アンロード
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo ""
echo "Setup complete."
echo ""
echo "Usage:"
echo "  python3 app.py              # メニューバーアプリとして起動"
echo "  python3 face_trigger.py     # カメラプレビューあり（チューニング用）"
echo "  python3 face_trigger.py --headless  # バックグラウンド単体起動"
echo ""
echo "Login item installed: $PLIST_PATH"
echo "次回ログイン時から自動起動します。"
