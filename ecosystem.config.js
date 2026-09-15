// ecosystem.config.js — chạy Telegram bot bằng PM2 trên server.
//
// Chuẩn bị (1 lần, trên server — giả định Ubuntu/Debian):
//   sudo apt-get update && sudo apt-get install -y python3-venv ffmpeg
//   bash setup_local.sh                                        # tạo .venv + edge-tts + Chromium
//   .venv/bin/pip install -r telegram_bot/requirements.txt      # aiogram cho bot (dùng chung venv)
//   sudo .venv/bin/python -m playwright install-deps chromium   # thư viện hệ thống cho Chromium
//                                                                # (setup_local.sh không cài mục này,
//                                                                #  máy dev thường đã có sẵn nhưng
//                                                                #  server mới cài hệ điều hành thì chưa)
//   cp telegram_bot/env.example telegram_bot/.env               # rồi điền BOT_TOKEN thật vào
//
// Chạy:
//   npm install -g pm2          # nếu server chưa có pm2
//   pm2 start ecosystem.config.js
//   pm2 save && pm2 startup     # để pm2 tự khởi động lại bot khi server reboot
//
// Theo dõi:
//   pm2 logs ai-video-bot
//   pm2 status
//
// Cập nhật code sau này:
//   git pull && pm2 restart ai-video-bot
module.exports = {
  apps: [
    {
      name: "ai-video-bot",
      cwd: __dirname,
      script: ".venv/bin/python",
      args: "-m telegram_bot.bot",
      interpreter: "none",
      autorestart: true,
      max_restarts: 20,
      restart_delay: 5000,
      // bot.py tự retry vòng lặp polling khi mất mạng (xem main() trong bot.py);
      // PM2 chỉ cần hồi sinh tiến trình nếu nó crash hẳn (OOM, exception chưa bắt...).
      kill_timeout: 20000, // cho render/subprocess đang chạy dở kịp thoát sạch khi restart/stop
    },
  ],
};
