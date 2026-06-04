#!/usr/bin/env python3
"""
AquaFace メニューバーアプリ（PyObjC直接実装）
"""

import subprocess
import sys
import threading
import traceback
from pathlib import Path

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSMenu,
    NSMenuItem,
    NSObject,
    NSStatusBar,
    NSVariableStatusItemLength,
)

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

try:
    from face_trigger import run as ft_run
except Exception as e:
    print(f"face_trigger 読み込みエラー: {e}", flush=True)
    sys.exit(1)


class AquaFaceController(NSObject):

    def init(self):
        self = objc.super(AquaFaceController, self).init()
        if self is None:
            return None
        self._stop_event = None
        self._thread     = None

        # ステータスバーアイテム
        sb = NSStatusBar.systemStatusBar()
        self._status_item = sb.statusItemWithLength_(NSVariableStatusItemLength)
        self._status_item.setVisible_(True)
        self._status_item.button().setTitle_("AF")
        print(f"ステータスバーアイテム作成完了 visible={self._status_item.isVisible()}", flush=True)

        # メニュー
        menu = NSMenu.alloc().init()

        self._item_toggle = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "▶ 起動", "onToggle:", ""
        )
        self._item_toggle.setTarget_(self)
        menu.addItem_(self._item_toggle)

        item_preview = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "🔍 プレビューで起動", "onPreview:", ""
        )
        item_preview.setTarget_(self)
        menu.addItem_(item_preview)

        menu.addItem_(NSMenuItem.separatorItem())

        item_quit = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "終了", "onQuit:", ""
        )
        item_quit.setTarget_(self)
        menu.addItem_(item_quit)

        self._status_item.setMenu_(menu)
        return self

    def onToggle_(self, sender):
        if self._is_running():
            self._stop()
        else:
            self._start()

    def onPreview_(self, sender):
        if self._is_running():
            return
        subprocess.Popen([sys.executable, str(ROOT / "face_trigger.py")])

    def onQuit_(self, sender):
        self._stop()
        NSApplication.sharedApplication().terminate_(None)

    def _is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def _start(self):
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_safe, daemon=True)
        self._thread.start()
        self._item_toggle.setTitle_("⏹ 停止")
        self._status_item.button().setTitle_("👁 ON")

    def _run_safe(self):
        try:
            ft_run(headless=True, stop_event=self._stop_event)
        except Exception:
            print(traceback.format_exc(), flush=True)

    def _stop(self):
        if self._stop_event:
            self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._stop_event = None
        self._thread     = None
        self._item_toggle.setTitle_("▶ 起動")
        self._status_item.button().setTitle_("👁 AF")


if __name__ == "__main__":
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    app.finishLaunching()  # ステータスバー作成前に初期化を完了

    controller = AquaFaceController.alloc().init()

    print("AquaFace 起動中...", flush=True)
    app.run()
    del controller
