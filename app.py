#!/usr/bin/env python3
"""
AquaFace メニューバーアプリ
  - メニューバーのアイコンから起動 / 停止を切り替え
  - ヘッドレスモードでバックグラウンド動作
  - プレビューは別プロセスとして起動
"""

import subprocess
import sys
import threading
from pathlib import Path

import rumps

# face_trigger.py と同じディレクトリを参照
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from face_trigger import run as ft_run  # noqa: E402


class AquaFaceApp(rumps.App):
    def __init__(self):
        super().__init__("AquaFace", title="AF", quit_button=None)
        self._stop_event = None
        self._thread     = None

        self._item_toggle  = rumps.MenuItem("▶ 起動",        callback=self.on_toggle)
        self._item_preview = rumps.MenuItem("🔍 プレビューで起動", callback=self.on_preview)
        self._item_quit    = rumps.MenuItem("終了",           callback=self.on_quit)

        self.menu = [
            self._item_toggle,
            self._item_preview,
            None,
            self._item_quit,
        ]

    # ── 起動 / 停止 ─────────────────────────────────────────────────────────
    def on_toggle(self, _):
        if self._is_running():
            self._stop()
        else:
            self._start()

    def _is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def _start(self):
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=ft_run,
            kwargs={"headless": True, "stop_event": self._stop_event},
            daemon=True,
        )
        self._thread.start()
        self._item_toggle.title  = "⏹ 停止"
        self._item_preview.set_callback(None)  # 実行中はプレビュー無効
        self.title = "AF ⏺"

    def _stop(self):
        if self._stop_event:
            self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._stop_event = None
        self._thread     = None
        self._item_toggle.title  = "▶ 起動"
        self._item_preview.set_callback(self.on_preview)
        self.title = "AF"

    # ── プレビュー（別プロセス）──────────────────────────────────────────────
    def on_preview(self, _):
        subprocess.Popen([sys.executable, str(ROOT / "face_trigger.py")])

    # ── 終了 ─────────────────────────────────────────────────────────────────
    def on_quit(self, _):
        self._stop()
        rumps.quit_application()


if __name__ == "__main__":
    AquaFaceApp().run()
