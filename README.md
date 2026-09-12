# AI Video Comparison Tool

Personal tool to auto-generate A-vs-B comparison videos, chạy hoàn toàn local
(không cần Kaggle/GPU).

Luồng: kịch bản 10-15 câu (do AI ngoài viết, JSON) + 2 ảnh nhân vật A/B
-> designer map visual -> edge-tts (giọng NamMinh mặc định, tốc độ 1.25x)
-> HTML/CSS/JS -> Playwright/Chromium record -> FFmpeg -> final.mp4

## Cấu trúc

```
tol/                     # gốc repo (mọi máy clone về là chạy được)
├── src/                 # pipeline render video (designer/tts/renderer/...)
├── templates/           # HTML/CSS/JS template
├── animations/          # js animation hiệu ứng nhân vật
├── generated/           # output tạm (audio/html/scripts/videos) — tự xóa
├── telegram_bot/        # bot Telegram (bot.py, config.py, assets/, prompts/)
├── requirements.txt
├── setup_local.sh       # tạo .venv + cài deps + playwright chromium
└── .env (trong telegram_bot/)  # chỉ gồm BOT_TOKEN + DEFAULT_VOICE
```

## Chạy (lần đầu, trên bất kỳ máy nào)

```bash
bash setup_local.sh                # tạo .venv + playwright/chromium + edge-tts
sudo apt-get install -y ffmpeg     # thiếu ffmpeg thì render lỗi
cp telegram_bot/env.example telegram_bot/.env   # điền BOT_TOKEN vào
```

Venv được **tự động tìm** (`config.py`): `.venv/` ở gốc repo. Không cần sửa
đường dẫn nào — clone về máy khác là chạy.

## Chạy bot

```bash
setsid nohup python3 -m telegram_bot.bot >> bot.log 2>&1 < /dev/null &
```

## Test pipeline trực tiếp (không qua bot)

```bash
.venv/bin/python src/pipeline.py
```