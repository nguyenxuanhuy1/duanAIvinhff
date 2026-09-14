"""Config: đọc biến môi trường từ .env, cung cấp hằng số toàn cục."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv(BASE_DIR / ".env")


def _required(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        raise SystemExit(f"Thiếu biến môi trường bắt buộc: {name} (xem telegram_bot/env.example)")
    return val


BOT_TOKEN = _required("BOT_TOKEN")

JOBS_DIR = BASE_DIR / "telegram_bot" / "jobs"


def _find_venv_python() -> Path:
    """Tự tìm python của virtualenv (tương đối theo repo — dùng chung mọi máy).

    Thứ tự ưu tiên:
      1. env LOCAL_VENV_PYTHON nếu set (gỡ bỏ để auto).
      2. .venv/bin/python ở gốc repo (setup_local.sh tạo).
      3. kaggle-pipeline/.venv/bin/python (cấu trúc cũ, fallback).
    """
    env = os.getenv("LOCAL_VENV_PYTHON")
    if env:
        return Path(env)
    for cand in (
        BASE_DIR / ".venv" / "bin" / "python",
        BASE_DIR / "kaggle-pipeline" / ".venv" / "bin" / "python",
    ):
        if cand.is_file():
            return cand
    return BASE_DIR / ".venv" / "bin" / "python"


# Pipeline (src/) + thư mục venv để chạy render local.
# Bot render qua subprocess bằng venv python này để không cần cài
# playwright/edge-tts vào python hệ thống của bot.
LOCAL_VENV_PYTHON = str(_find_venv_python())

# Giọng TTS mặc định (edge-tts, miễn phí, chạy local): nam miền Bắc.
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "vi-VN-NamMinhNeural")