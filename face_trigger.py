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
import json
import sys
import time
from enum import Enum, auto
from pathlib import Path

import numpy as np
import psutil
import Quartz
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from pynput.keyboard import Controller, Key

# ── モデルパス ─────────────────────────────────────────────────────────────────
MODEL_PATH    = Path(__file__).parent / "face_landmarker.task"
SETTINGS_PATH = Path(__file__).parent / "settings.json"

# ── 調整パラメータ（初期値）─────────────────────────────────────────────────────
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
    State.RECORD:   (0,   0, 220),
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


def run(headless: bool, stop_event=None):
    if not MODEL_PATH.exists():
        sys.exit(f"モデルファイルが見つかりません: {MODEL_PATH}")

    kb    = Controller()  # Enter キー用
    state = State.IDLE
    fn_held          = False
    t_cooldown_start = 0.0
    t_blink_start    = None
    t_smile_start    = None
    smile_must_reset = False
    t_jaw_closed_at  = 0.0
    JAW_BLINK_GUARD  = 0.25
    jaw_was_open     = False
    ear_baseline     = 0.30

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

    psutil.cpu_percent(interval=None)  # 初回呼び出しで計測基準を設定

    frame_count   = 0
    proc_count    = 0
    fps_val       = 0.0
    fps_last_t    = time.time()
    fps_last_proc = 0
    cpu_str       = "CPU: --"

    # 可変閾値: [jaw, blink_delta, blink_hold, smile]（保存値があれば復元）
    _defaults = [JAW_OPEN_THRESHOLD, BLINK_DELTA, BLINK_HOLD_SECS, SMILE_THRESHOLD]
    try:
        _saved = json.loads(SETTINGS_PATH.read_text())
        thresholds = [float(_saved.get(k, d)) for k, d in
                      zip(["jaw", "blink_delta", "blink_hold", "smile"], _defaults)]
        print(f"設定を読み込みました: {SETTINGS_PATH}")
    except Exception:
        thresholds = _defaults[:]

    # スキップフレームでもパネルを再描画するためにキャッシュ
    disp_state    = State.IDLE
    disp_jaw      = 0.0
    disp_blink    = 0.0
    disp_smile    = 0.0
    disp_ear_bl   = ear_baseline

    # ── コントロールパネル定数 ──────────────────────────────────────────────────
    CTRL_H   = 140   # パネル高さ
    LBL_W    = 90    # ラベル幅
    BAR_W    = 180   # バー幅
    BAR_X    = LBL_W
    ROW_H    = 24    # スライダー1行の高さ
    ROWS_TOP = 38    # パネル内でスライダーが始まるY
    SL_NAMES = ["JAW", "BLINK_DELTA", "BLINK_HOLD", "SMILE"]
    SL_MAX   = [1.0,   1.0,          1.0,           0.25]   # SMILE は 0.25 を上限に
    _drag    = [-1]  # ドラッグ中のスライダーindex（-1=なし）
    cam_h    = [CAMERA_HEIGHT]  # 実フレーム高さ（初回フレームで更新）

    def _draw_ctrl(fw):
        panel = np.full((CTRL_H, fw, 3), 22, dtype=np.uint8)

        # CPU/FPS 行
        cv2.putText(panel, cpu_str,
                    (6, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (100, 200, 255), 1)

        # NOW 行（現在値 + ブリンク閾値）
        blink_thr = disp_ear_bl + thresholds[1]
        live = (f"NOW  JAW:{disp_jaw:.2f}  "
                f"BLINK:{disp_blink:.2f}(thr:{blink_thr:.2f})  "
                f"SMILE:{disp_smile:.2f}")
        cv2.putText(panel, live,
                    (6, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 210, 0), 1)

        # 区切り線
        cv2.line(panel, (0, 36), (fw, 36), (70, 70, 70), 1)

        # スライダー行
        for i, (name, val, sl_max) in enumerate(zip(SL_NAMES, thresholds, SL_MAX)):
            ry = ROWS_TOP + i * ROW_H
            by = ry + (ROW_H - 8) // 2   # バートップY（行内で垂直中央）

            # ラベル
            cv2.putText(panel, name,
                        (4, ry + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (180, 180, 180), 1)

            # バー背景
            cv2.rectangle(panel, (BAR_X, by), (BAR_X + BAR_W, by + 8), (55, 55, 55), -1)

            # バー塗り（val / sl_max で正規化）
            fill = max(0, min(BAR_W, int(val / sl_max * BAR_W)))
            cv2.rectangle(panel, (BAR_X, by), (BAR_X + fill, by + 8), (30, 130, 200), -1)

            # ハンドル（ドラッグ中は黄色）
            hx   = BAR_X + fill
            hcol = (60, 220, 255) if _drag[0] == i else (210, 210, 210)
            cv2.circle(panel, (hx, by + 4), 8, hcol, -1)

            cv2.putText(panel, f"{val:.2f}",
                        (BAR_X + BAR_W + 5, ry + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (220, 200, 60), 1)

        return panel

    def mouse_cb(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONUP:
            _drag[0] = -1
            return
        py = y - cam_h[0]   # コントロールパネル内Y
        if event == cv2.EVENT_LBUTTONDOWN:
            if py >= ROWS_TOP:
                i = (py - ROWS_TOP) // ROW_H
                if 0 <= i < 4:
                    _drag[0] = i
        if _drag[0] >= 0 and (flags & cv2.EVENT_FLAG_LBUTTON):
            sl_max = SL_MAX[_drag[0]]
            val = max(0.01, min(sl_max, (x - BAR_X) / BAR_W * sl_max))
            thresholds[_drag[0]] = round(val, 3)

    if not headless:
        cv2.namedWindow("face_trigger")
        cv2.setMouseCallback("face_trigger", mouse_cb)

    try:
        while not (stop_event and stop_event.is_set()):
            ok, frame = cap.read()
            if not ok:
                continue

            frame_count += 1
            jaw_thresh   = thresholds[0]
            blink_delta  = thresholds[1]
            blink_hold   = thresholds[2]
            smile_thresh = thresholds[3]

            if frame_count % FRAME_SKIP != 0:
                if not headless:
                    # スキップフレーム: 上部バーのみ再描画してちらつき防止
                    h, w = frame.shape[:2]
                    cam_h[0] = h
                    color = STATE_COLOR[disp_state]
                    cv2.rectangle(frame, (0, 0), (w, 50), color, -1)
                    cv2.putText(frame, STATE_LABEL[disp_state],
                                (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
                    composite = np.vstack([frame, _draw_ctrl(w)])
                    cv2.imshow("face_trigger", composite)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                continue

            # ── CPU / FPS 更新（15処理フレームごと）──────────────────────────
            proc_count += 1
            if proc_count % 15 == 0:
                now_t   = time.time()
                elapsed = now_t - fps_last_t
                if elapsed > 0:
                    fps_val = (proc_count - fps_last_proc) / elapsed
                fps_last_t    = now_t
                fps_last_proc = proc_count
                cpu_pct = psutil.cpu_percent(interval=None)
                freq    = psutil.cpu_freq()
                if freq:
                    cpu_str = f"CPU:{cpu_pct:.0f}%  {freq.current/1000:.2f}GHz  FPS:{fps_val:.0f}"
                else:
                    cpu_str = f"CPU:{cpu_pct:.0f}%  FPS:{fps_val:.0f}"

            h, w = frame.shape[:2]
            cam_h[0] = h
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
                if blink < ear_baseline + blink_delta * 0.5:
                    ear_baseline = (1 - EAR_BASELINE_ALPHA) * ear_baseline + EAR_BASELINE_ALPHA * blink
                    ear_baseline = min(ear_baseline, 0.35)

                # 顎が開→閉に変わった瞬間を記録（直後のblink誤検知を防ぐ）
                if jaw > jaw_thresh:
                    jaw_was_open = True
                elif jaw_was_open:
                    t_jaw_closed_at = now
                    jaw_was_open = False
                    t_blink_start = None

                blink_allowed = (now - t_jaw_closed_at) > JAW_BLINK_GUARD
                eye_closed = blink_allowed and (blink > ear_baseline + blink_delta)

                # ── 状態遷移 ───────────────────────────────────────────────
                if state in (State.IDLE, State.READY):

                    if jaw > jaw_thresh:
                        fn_press()
                        fn_held = True
                        state = State.RECORD
                        t_blink_start = None
                        t_smile_start = None

                    elif smile > smile_thresh and not smile_must_reset:
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
                        if smile < smile_thresh:
                            smile_must_reset = False

                elif state == State.RECORD:

                    if eye_closed:
                        if t_blink_start is None:
                            t_blink_start = now
                        elif now - t_blink_start >= blink_hold:
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

                # 表示キャッシュ更新
                disp_state  = state
                disp_jaw    = jaw
                disp_blink  = blink
                disp_smile  = smile
                disp_ear_bl = ear_baseline

            # ── 描画 ──────────────────────────────────────────────────────
            if not headless:
                color = STATE_COLOR[disp_state]
                cv2.rectangle(frame, (0, 0), (w, 50), color, -1)
                cv2.putText(frame, STATE_LABEL[disp_state],
                            (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
                composite = np.vstack([frame, _draw_ctrl(w)])
                cv2.imshow("face_trigger", composite)
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
        data = {"jaw": thresholds[0], "blink_delta": thresholds[1],
                "blink_hold": thresholds[2], "smile": thresholds[3]}
        SETTINGS_PATH.write_text(json.dumps(data, indent=2))
        print(f"設定を保存しました: {SETTINGS_PATH}")
        print("終了")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true",
                        help="カメラプレビューなしでバックグラウンド動作")
    args = parser.parse_args()
    run(args.headless)
