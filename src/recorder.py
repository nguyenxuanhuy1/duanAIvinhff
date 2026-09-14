"""
recorder.py

Launches Chromium via Playwright's ASYNC API (required inside Kaggle/Jupyter,
which already runs its own asyncio event loop - the sync API raises
"using Playwright Sync API inside the asyncio loop").

Loads the self-contained HTML from renderer.py, lets the animation play,
and uses Playwright's built-in video recording to capture a .webm file.
Waits for window.__SCENE_DONE__ (set by templates/animation.js) instead of
a hardcoded sleep, so it never cuts off a scene early or waits too long.
"""

from pathlib import Path

from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
GENERATED_VIDEO_DIR = BASE_DIR / "generated" / "videos"

DEFAULT_VIEWPORT = {"width": 1080, "height": 1920}  # portrait, short-form video

# Cờ khởi động Chromium: cắt các subsystem không dùng khi record offscreen
# (giảm RAM + CPU), và chặn throttling timer — cả kịch bản chạy bằng
# setTimeout nên renderer bị "backgrounded" sẽ làm scene giãn/lệch thời lượng.
CHROMIUM_ARGS = [
    "--disable-dev-shm-usage",          # /dev/shm nhỏ -> dùng /tmp, tránh crash OOM
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--renderer-process-limit=1",       # 1 tab duy nhất, không cần process pool
    "--disable-extensions",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-sync",
    "--disable-background-networking",
    "--metrics-recording-only",
    "--no-first-run",
    "--mute-audio",                     # video record là silent, bỏ audio stack
]


async def record_html(
    html_path: Path,
    run_id: str,
    viewport: dict = None,
    poll_interval: float = 0.5,
    max_wait_seconds: float = 180.0,
) -> Path:
    viewport = viewport or DEFAULT_VIEWPORT
    GENERATED_VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=CHROMIUM_ARGS)
        try:
            context = await browser.new_context(
                viewport=viewport,
                record_video_dir=str(GENERATED_VIDEO_DIR),
                record_video_size=viewport,
            )
            page = await context.new_page()
            await page.goto(html_path.resolve().as_uri())

            # Poll ngay trong trang (polling=ms) thay vì evaluate() mỗi 0.5s:
            # bỏ hàng trăm round-trip CDP làm gián đoạn compositor khi đang record.
            try:
                await page.wait_for_function(
                    "() => window.__SCENE_DONE__ === true",
                    polling=int(poll_interval * 1000),
                    timeout=max_wait_seconds * 1000,
                )
            except Exception:
                print(
                    f"[recorder] WARNING: scene did not signal completion within "
                    f"{max_wait_seconds}s, stopping recording anyway (run_id={run_id})"
                )

            video = page.video  # must grab reference before closing
            await context.close()  # flush video file
        finally:
            await browser.close()  # luôn kill Chromium, kể cả khi lỗi giữa chừng

        if video is None:
            raise RuntimeError("Playwright did not produce a video object")

        raw_path = Path(await video.path())
        final_path = GENERATED_VIDEO_DIR / f"{run_id}.webm"
        raw_path.replace(final_path)
        return final_path
