#!/usr/bin/env bash
# setup_local.sh — chuẩn bị môi trường render video local (không Kaggle).
#
# Làm: tạo venv .venv ở gốc repo, cài playwright+edge-tts+ffmpeg-python,
#      cài chromium, kiểm tra ffmpeg.
#
# Chạy: bash setup_local.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"

echo "==> Tạo venv: $VENV"
python3 -m venv "$VENV"

echo "==> Cài pipeline deps (playwright, ffmpeg-python, edge-tts)"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$ROOT/requirements.txt"

echo "==> Cài Chromium cho Playwright"
"$VENV/bin/python" -m playwright install chromium

echo "==> Kiểm tra ffmpeg/ffprobe"
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  echo "    ffmpeg OK: $(ffmpeg -version 2>/dev/null | head -1)"
else
  echo "    THIẾU ffmpeg — cài bằng: sudo apt install -y ffmpeg"
fi

echo "==> XONG. Bot sẽ tự dùng: $VENV/bin/python"
echo "    (config.py auto-detect .venv ở gốc repo — không cần cấu hình)"