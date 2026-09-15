# AI Video Comparison Tool

Personal tool to auto-generate A-vs-B comparison videos, chạy hoàn toàn local
(không cần Kaggle/GPU).

Luồng: kịch bản 10-15 câu (do AI ngoài viết, JSON) + 2 ảnh nhân vật A/B
-> designer map visual -> edge-tts (giọng NamMinh mặc định, tốc độ 1.25x)
-> HTML/CSS/JS -> Playwright/Chromium chụp 1 ảnh mỗi scene -> FFmpeg
(crossfade + ghép tiếng) -> final.mp4

## Cấu trúc

```
tol/                     # gốc repo (mọi máy clone về là chạy được)
├── src/                 # pipeline render video (designer/tts/renderer/...)
├── templates/           # HTML/CSS/JS template
├── animations/          # js animation hiệu ứng nhân vật
├── generated/           # output tạm (audio/frames/html/scripts/videos) — tự xóa
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
## Chế độ dựng video (`RECORD_MODE`)

Mặc định `stills`: mỗi scene chỉ chụp **một ảnh tĩnh**, rồi FFmpeg dựng thẳng
ra H.264 kèm crossfade 0.5s giữa các scene. Làm được vì mọi transition trong
`templates/style.css` đều hữu hạn (<= 0.5s, `forwards`) — sau đó khung hình
đứng yên, nên quay realtime là encode lặp lại hàng nghìn khung giống hệt nhau.

So với bản cũ, cách này bỏ hẳn **hai** lượt encode toàn bộ video: VP8 của
Chromium lúc quay, và lượt transcode webm -> H.264 sau đó.

Ở chế độ này TTS (chờ mạng) và chụp ảnh (CPU) chạy **song song**, vì
`capture_scenes` không cần tới duration — hai việc không giành tài nguyên
của nhau nên trên máy ít core phần thời gian này gần như được cho không.

Muốn quay lại đúng cách cũ (Chromium record realtime):

```bash
RECORD_MODE=browser python -m telegram_bot.bot
```

## Deploy trên server (PM2)

Bot chạy long-polling (không cần mở port/webhook/nginx), nên chỉ cần 1 tiến
trình sống bền. Dùng `ecosystem.config.js` có sẵn ở gốc repo:

```bash
# 1) chuẩn bị (1 lần)
sudo apt-get update && sudo apt-get install -y python3-venv ffmpeg
bash setup_local.sh                                      # .venv + edge-tts + Chromium
.venv/bin/pip install -r telegram_bot/requirements.txt   # aiogram, dùng chung venv với pipeline
sudo .venv/bin/python -m playwright install-deps chromium  # thư viện hệ thống cho Chromium
                                                           # (server mới cài OS thường thiếu mục
                                                           #  này — setup_local.sh không cài)
cp telegram_bot/env.example telegram_bot/.env             # điền BOT_TOKEN thật

# 2) chạy bằng PM2
npm install -g pm2          # nếu server chưa có
pm2 start ecosystem.config.js
pm2 save && pm2 startup     # để pm2 tự bật lại bot khi server reboot
```

Theo dõi / cập nhật:

```bash
pm2 logs ai-video-bot       # xem log realtime
pm2 status                  # trạng thái tiến trình
git pull && pm2 restart ai-video-bot   # deploy code mới
```

Lưu ý: cả bot lẫn worker render (`local_job.py`, chạy qua subprocess) đều
dùng chung `.venv/bin/python` — không cần venv riêng cho bot.
