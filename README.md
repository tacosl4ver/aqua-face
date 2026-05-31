# AquaFace

**Hands-free voice input controller using MacBook camera**
**MacBookカメラを使ったハンズフリー音声入力コントローラー**

Control [Aqua Voice](https://withaqua.com) (or any push-to-talk app) with facial expressions — no hands required.
[Aqua Voice](https://withaqua.com)などのPush-to-Talkアプリを、表情だけで操作できます。

---

## How it works / 使い方

| Expression / 表情 | Action / 動作 |
|---|---|
| Open mouth / 口を開ける | Start recording / 録音開始（Fn押下） |
| Slow blink / ゆっくりまばたき | Stop recording / 録音停止（Fn解放） |
| Smile / 笑顔 | Send / Enter送信 |

---

## Requirements / 動作環境

- macOS（M1以降推奨）
- Python 3.10+
- Built-in or external camera / 内蔵または外部カメラ

---

## Setup / セットアップ

```bash
git clone https://github.com/tacosl4ver/aqua-face.git
cd aqua-face
bash install.sh
```

---

## Usage / 起動

```bash
# With camera preview（カメラプレビューあり）
python3 face_trigger.py

# Headless / background mode（バックグラウンド動作）
python3 face_trigger.py --headless
```

---

## Tuning / 閾値の調整

In preview mode, drag the sliders at the bottom of the window to adjust thresholds in real time. Settings are saved to `settings.json` on exit and restored on the next launch.

プレビューモードでは、ウィンドウ下部のスライダーをドラッグしてリアルタイムに閾値を変更できます。終了時に `settings.json` へ自動保存され、次回起動時に復元されます。

| Parameter | Default | Description |
|---|---|---|
| JAW | 0.22 | Mouth open threshold / 口の開き閾値 |
| BLINK_DELTA | 0.28 | Blink sensitivity above baseline / まばたき感度 |
| BLINK_HOLD | 0.30 s | Slow blink duration / スローブリンク判定秒数 |
| SMILE | 0.12 | Smile threshold (range 0–0.25) / スマイル閾値 |

---

## Dependencies & Licenses / 依存ライブラリとライセンス

| Library | License | Used for |
|---|---|---|
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | Apache 2.0 | Face landmark detection / 顔ランドマーク検出 |
| [OpenCV](https://github.com/opencv/opencv) | Apache 2.0 | Camera capture & preview / カメラ映像処理 |
| [pynput](https://github.com/moses-palmer/pynput) | LGPL v3 | Keyboard event (Enter) / キーボード操作 |
| [PyObjC Quartz](https://github.com/ronaldoussoren/pyobjc) | MIT | Fn key via CGEvent / Fnキー送信 |
| [psutil](https://github.com/giampaolo/psutil) | BSD 3-Clause | CPU metrics display / CPU情報表示 |
| [NumPy](https://github.com/numpy/numpy) | BSD 3-Clause | Frame compositing / フレーム合成 |

The face landmark model (`face_landmarker.task`) is provided by MediaPipe under Apache 2.0.

顔ランドマークモデル（`face_landmarker.task`）は MediaPipe が Apache 2.0 ライセンスで提供しています。

### Note on pynput (LGPL v3)

This project uses [pynput](https://github.com/moses-palmer/pynput), which is licensed under the **GNU Lesser General Public License v3 (LGPL v3)**.  
As required by LGPL v3, the pynput source code is available at: https://github.com/moses-palmer/pynput

pynput を LGPL v3 のもとで使用しています。LGPL v3 の要件に従い、pynput のソースコードは上記リンクから入手できます。

---

## Built with / 開発環境

This project was built with the assistance of [Claude Code](https://claude.ai/code) (Anthropic).

このプロジェクトは [Claude Code](https://claude.ai/code)（Anthropic）を使って開発しました。
