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

Open `face_trigger.py` and edit the parameters at the top:

`face_trigger.py` の上部にある以下のパラメータで動作を調整できます：

```python
JAW_OPEN_THRESHOLD  = 0.22   # Mouth open sensitivity / 口の開き感度
BLINK_DELTA         = 0.28   # Slow blink sensitivity / スローブリンク感度
BLINK_HOLD_SECS     = 0.30   # Slow blink duration (sec) / スローブリンク判定秒数
SMILE_THRESHOLD     = 0.12   # Smile sensitivity / スマイル感度
```
