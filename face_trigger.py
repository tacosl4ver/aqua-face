#!/usr/bin/env python3
"""
face_trigger.py — ハンズフリー音声入力コントローラー
  口を開ける        → Fn押下（Aqua Voice 録音開始）
  スローブリンク    → Fn解放（Aqua Voice 録音終了）
  スマイル          → Enter送信（READY状態のみ）

Usage:
  python3 face_trigger.py             # カメラプレビューあり（初期チューニング用）
  python3 face_trigger.py --headless  # バックグラウンド動作
"""

import argparse
import os
import sys
import time
from enum import Enum, auto
from pathlib import Path

import Quartz
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from pynput.keyboard import Controller, Key

# ── モデルパス ─────────────────────────────────────────────────────────────────
MODEL_PATH = Path(__file__).parent / "face_landmarker.task"

# ── 調整パラメータ ─────────────────────────────────────────────────────────────
JAW_OPEN_THRESHOLD   = 0.22   # 口の開き（0〜1）：これ以上で録音開始
BLINK_DELTA          = 0.28   # ベースラインからこれ以上上がったら「目閉じ」判定
BLINK_HOLD_SECS      = 0.30   # スローブリンクと判定するまでの秒数
EAR_BASELINE_ALPHA   = 0.05   # ベースラインの更新速度（小さいほど安定）
SMILE_THRESHOLD      = 0.12   # 笑顔スコア（0〜1）：これ以上でスマイル判定
SMILE_HOLD_SECS      = 0.00   # スマイルをキープする秒数
COOLDOWN_SECS        = 0.00   # 録音停止後、Enter受付までの待機時間
CAMERA_WIDTH         = 320    # カメラ解像度（小さいほどCPU低減）
CAMERA_HEIGHT        = 240
FRAME_SKIP           = 2      # N-1フレームおきに処理（2=15fps相当）

# Fn キー: modifier key なので FlagsChanged イベントで送る必要がある
_FN_KEYCODE = 63
_FN_FLAG    = Quartz.kCGEventFlagMaskSecondaryFn  # 0x800000


def _fn_event(pressed: bool):
    src   = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    event = Quartz.CGEventCreateKeyboardEvent(src, _FN_KEYCODE, pressed)
    Quartz.CGEventSetType(event, Quartz.kCGEventFlagsChanged)
    Quartz.CGEventSetFlags(event, _FN_FLAG if pressed else 0)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, event)


def fn_press():
    _fn_event(True)


def fn_release():
    _fn_event(False)


class State(Enum):
    IDLE     = auto()  # 待機（Enterトリガー無効）
    RECORD   = auto()  # 録音中（Fn押下中）
    COOLDOWN = auto()  # Aqua Voice文字起こし待ち（Enterトリガー無効）
    READY    = auto()  # 次の発話またはEnter待ち


STATE_COLOR = {
    State.IDLE:     (80,  80,  80),
    State.RECORD:   (200, 60,   0),
    State.COOLDOWN: (200, 160,  0),
    State.READY:    (0,  180,  60),
}
STATE_LABEL = {
    State.IDLE:     "IDLE",
    State.RECORD:   "REC  (slow-blink to stop)",
    State.COOLDOWN: "PROCESSING...",
    State.READY:    "READY  (smile = Enter)",
}


def get_blendshape(blendshapes, name: str) -> float:
    for b in blendshapes:
        if b.category_name == name:
            return b.score
    return 0.0


def run(headless: bool):
    if not MODEL_PATH.exists():
        sys.exit(f"モデルファイルが見つかりません: {MODEL_PATH}")

    kb    = Controller()  # Enter キー用
    state = State.IDLE
    fn_held          = False
    t_cooldown_start = 0.0
    t_blink_start    = None
    t_smile_start    = None
    smile_must_reset = False  # Enter送信後、一度スマイルが消えるまで次を無効にする
    t_jaw_closed_at  = 0.0    # 顎が閉じた時刻（直後のblink誤検知を防ぐ）
    JAW_BLINK_GUARD  = 0.25   # 顎が閉じてからblink検知を再開するまでの秒数
    jaw_was_open     = False
    ear_baseline     = 0.30   # 起動時の初期値、すぐに実測値に収束する

    base_options = mp_python.BaseOptions(model_asset_path=str(MODEL_PATH))
    options = vision.FaceLandmarkerOptions(
        base_options=base_options,
        output_face_blendshapes=True,
        num_faces=1,
        min_face_detection_confidence=0.7,
        min_face_presence_confidence=0.7,
        min_tracking_confidence=0.7,
    )
    detector = vision.FaceLandmarker.create_from_options(options)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        sys.exit("カメラが開けません")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

    print("face_trigger 起動。終了: q キー（プレビューあり）または Ctrl+C")

    frame_count = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue

            frame_count += 1
            if frame_count % FRAME_SKIP != 0:
                if not headless:
                    cv2.imshow("face_trigger", frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                continue

            h, w = frame.shape[:2]
            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            )
            result = detector.detect(mp_image)
            now = time.time()

            if result.face_blendshapes:
                bs = result.face_blendshapes[0]

                jaw   = get_blendshape(bs, "jawOpen")
                blink = (get_blendshape(bs, "eyeBlinkLeft") +
                         get_blendshape(bs, "eyeBlinkRight")) / 2
                smile = (get_blendshape(bs, "mouthSmileLeft") +
                         get_blendshape(bs, "mouthSmileRight")) / 2

                # 目が開いている時だけベースラインを更新（blink低い=目が開いている）
                if blink < ear_baseline + BLINK_DELTA * 0.5:
                    ear_baseline = (1 - EAR_BASELINE_ALPHA) * ear_baseline + EAR_BASELINE_ALPHA * blink
                    ear_baseline = min(ear_baseline, 0.35)  # 上限を設けてドリフト防止

                # 顎が開→閉に変わった瞬間を記録（直後のblink誤検知を防ぐ）
                if jaw > JAW_OPEN_THRESHOLD:
                    jaw_was_open = True
                elif jaw_was_open:
                    t_jaw_closed_at = now
                    jaw_was_open = False
                    t_blink_start = None

                blink_allowed = (now - t_jaw_closed_at) > JAW_BLINK_GUARD
                eye_closed = blink_allowed and (blink > ear_baseline + BLINK_DELTA)

                # ── 状態遷移 ───────────────────────────────────────────────
                if state in (State.IDLE, State.READY):

                    # 口を開ける → 録音開始
                    if jaw > JAW_OPEN_THRESHOLD:
                        fn_press()
                        fn_held = True
                        state = State.RECORD
                        t_blink_start = None
                        t_smile_start = None

                    # スマイル → Enter（IDLE・READY両方）
                    elif smile > SMILE_THRESHOLD and not smile_must_reset:
                        if t_smile_start is None:
                            t_smile_start = now
                        elif now - t_smile_start >= SMILE_HOLD_SECS:
                            kb.press(Key.enter)
                            kb.release(Key.enter)
                            smile_must_reset = True
                            t_smile_start    = None
                            state            = State.IDLE
                    else:
                        t_smile_start = None
                        if smile < SMILE_THRESHOLD:
                            smile_must_reset = False

                elif state == State.RECORD:

                    # スローブリンク → 録音停止
                    if eye_closed:
                        if t_blink_start is None:
                            t_blink_start = now
                        elif now - t_blink_start >= BLINK_HOLD_SECS:
                            fn_release()
                            fn_held = False
                            state = State.COOLDOWN
                            t_cooldown_start = now
                            t_blink_start = None
                    else:
                        t_blink_start = None

                elif state == State.COOLDOWN:
                    if now - t_cooldown_start >= COOLDOWN_SECS:
                        state = State.READY

                # ── デバッグ表示 ───────────────────────────────────────────
                if not headless:
                    color = STATE_COLOR[state]
                    label = STATE_LABEL[state]
                    cv2.rectangle(frame, (0, 0), (w, 50), color, -1)
                    cv2.putText(frame, label, (10, 35),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
                    cv2.putText(frame,
                                f"JAW:{jaw:.2f}  BLINK:{blink:.2f}(base:{ear_baseline:.2f})  SMILE:{smile:.2f}",
                                (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                                (200, 200, 200), 1)

            if not headless:
                cv2.imshow("face_trigger", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

    except KeyboardInterrupt:
        pass
    finally:
        if fn_held:
            try:
                fn_release()
            except Exception:
                pass
        detector.close()
        cap.release()
        if not headless:
            cv2.destroyAllWindows()
        print("終了")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true",
                        help="カメラプレビューなしでバックグラウンド動作")
    args = parser.parse_args()
    run(args.headless)
