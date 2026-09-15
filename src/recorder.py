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
GENERATED_FRAMES_DIR = BASE_DIR / "generated" / "frames"

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
    # Máy không có GPU: mặc định Chromium vẫn đẻ riêng một GPU process để dò
    # phần cứng, hỏng, rồi mới lùi về SwiftShader. Tắt thẳng thì bớt được cả
    # một tiến trình (~150MB RAM) và vài giây khởi động mỗi job.
    "--disable-gpu",
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


# Mọi transition trong templates/style.css đều <= 0.5s và đều "forwards"
# (không có animation lặp vô hạn), nên sau ngần này ms khung hình đã đứng yên.
SETTLE_MS = 650


async def capture_scenes(
    html_path: Path,
    scene_json: dict,
    run_id: str,
    viewport: dict = None,
    settle_ms: int = SETTLE_MS,
) -> list:
    """Chụp MỘT ảnh tĩnh cho mỗi scene thay vì quay màn hình realtime.

    Vì sao: mọi scene đều đứng yên sau ~0.5s transition. Quay realtime bắt
    Chromium composite + encode VP8 đủ 25 khung/giây suốt cả video (60s video
    = 60s CPU tối thiểu, ~87% số khung là giống hệt nhau), rồi còn phải
    transcode webm -> H.264 thêm một lượt nữa. Chụp ảnh thì Chromium chỉ làm
    việc đúng <số scene> lần, và pipeline.encode_from_stills dựng thẳng ra
    H.264 — bỏ hẳn cả hai lượt encode đó.

    Trả về danh sách ảnh PNG theo đúng thứ tự scene.
    """
    viewport = viewport or DEFAULT_VIEWPORT
    frames_dir = GENERATED_FRAMES_DIR / run_id
    frames_dir.mkdir(parents=True, exist_ok=True)

    frame_paths = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=CHROMIUM_ARGS)
        try:
            context = await browser.new_context(viewport=viewport)
            page = await context.new_page()
            # Phải chạy TRƯỚC animation.js để nó không tự phát scene (sẽ đua
            # với vòng chụp bên dưới và cho ra ảnh sai scene).
            await page.add_init_script("window.__CAPTURE_MODE__ = true;")
            await page.goto(html_path.resolve().as_uri())

            # Ảnh nền/nhân vật phải decode xong, không thì scene đầu chụp ra
            # khung trắng.
            await page.wait_for_function(
                "() => typeof window.__applyScene === 'function' "
                "&& Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)",
                timeout=60_000,
            )

            for index in range(len(scene_json["scenes"])):
                await page.evaluate("i => window.__applyScene(i)", index)
                await page.wait_for_timeout(settle_ms)
                out_path = frames_dir / f"scene_{index:03d}.png"
                await page.screenshot(path=str(out_path))
                frame_paths.append(out_path)

            await context.close()
        finally:
            await browser.close()  # luôn kill Chromium, kể cả khi lỗi giữa chừng

    if not frame_paths:
        raise RuntimeError("capture_scenes: scene JSON không có scene nào để chụp")
    return frame_paths
