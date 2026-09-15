"""
pipeline.py

Phase 1 (generate_video_phase1): Scene JSON (hand-typed durations, no AI)
-> render -> record (silent) -> ffmpeg -> final.mp4 (no audio).

Phase 2 (generate_video_phase2): TTS synthesizes each scene's audio first,
REAL measured durations overwrite the scene JSON's durations, then
render -> record (silent) -> mux with the narration track -> final.mp4
(with audio). Audio is always the source of truth for timing, never a guess.

Phase 3 (generate_video_phase3): takes the dialogue lines (10-15) provided by
an EXTERNAL AI (the Telegram bot receives them as a JSON array), and:
  1. designer.py  – maps the lines to Scene JSON (fixed visual template, no cart)
  2. validator.py – checks animations/characters/images against the library
  then runs the same TTS→render→record→mux tail as phase 2.
No LLM/GGUF model is needed anywhere in the pipeline.

TTS engine: edge-tts (Microsoft Edge neural TTS, free, no GPU, no API key),
chạy trực tiếp trên máy local. Default voice: vi-VN-NamMinhNeural (nam).

Run from the project root in a Kaggle notebook cell (top-level await is
supported directly in Jupyter/Kaggle cells):

    import sys
    sys.path.insert(0, "src")
    from pipeline import generate_video_phase2, generate_video_phase3

    assets = {
        "background": "assets/background.jpg",
        "character": "assets/character.png",
        "character_confused": "assets/character_confused.png",  # optional
        "image_a": "assets/A.jpg",
        "image_b": "assets/B.jpg",
    }

    # Phase 2 (from a scene JSON file, e.g. hand-edited)
    result = await generate_video_phase2(
        scene_json_path="generated/scripts/example_scene.json",
        assets=assets, run_id="test_run_001",
    )

    # Phase 3 (external AI supplies the dialogue lines)
    result = await generate_video_phase3(
        script_lines=["Đây là A.", "Đây là B.", "..."],
        assets=assets, run_id="test_run_003",
    )
"""

import asyncio
import json
import os
import subprocess
from pathlib import Path

from renderer import render_html
from recorder import record_html, capture_scenes

BASE_DIR = Path(__file__).resolve().parent.parent
GENERATED_VIDEO_DIR = BASE_DIR / "generated" / "videos"

# "stills" (mặc định): chụp 1 ảnh/scene rồi để ffmpeg dựng video — nhanh hơn
# nhiều lần. "browser": quay màn hình realtime như bản cũ (đặt env
# RECORD_MODE=browser để quay lại cách cũ nếu thấy hình không ưng).
RECORD_MODE = os.getenv("RECORD_MODE", "stills").strip().lower()

FPS = 30
XFADE_DURATION = 0.5  # khớp với transition 0.5s trong templates/style.css

# Tham số encode video dùng chung (giữ nguyên như bản cũ: x264 / fast / crf 23).
_VIDEO_ENCODE_ARGS = [
    "-c:v", "libx264",
    "-preset", "fast",
    "-crf", "23",
    "-pix_fmt", "yuv420p",
]


def _run_ffmpeg(args: list, what: str) -> None:
    """Chạy ffmpeg im lặng; lỗi thì raise kèm stderr thật (bản cũ nuốt mất log).

    -nostdin: không giữ stdin (bot gọi qua subprocess, tránh treo).
    -loglevel error: bỏ hàng nghìn dòng progress -> không phình buffer RAM.
    """
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", *args],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg {what} lỗi (exit {proc.returncode}): {proc.stderr.strip()}")


def load_scene_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def convert_to_mp4(webm_path: Path) -> Path:
    """webm (không tiếng) -> mp4 (không tiếng). Chỉ phase 1 dùng."""
    mp4_path = webm_path.with_suffix(".mp4")
    _run_ffmpeg(["-i", str(webm_path), *_VIDEO_ENCODE_ARGS, str(mp4_path)], "convert_to_mp4")
    return mp4_path


def encode_with_audio(webm_path: Path, narration_path: Path, run_id: str) -> Path:
    """webm + narration -> final.mp4 trong MỘT lượt ffmpeg.

    Bản cũ chạy 2 lượt: webm->mp4 (encode x264) rồi mp4+wav->final (copy video).
    Lượt 2 phải đọc/ghi lại nguyên file 1080x1920 và để lại 1 mp4 trung gian
    nằm trên đĩa. Gộp lại: bớt 1 vòng ghi+đọc toàn bộ video và bớt luôn file
    tạm. Tham số encode y hệt nên chất lượng đầu ra không đổi.
    """
    final_path = webm_path.parent / f"{run_id}_final.mp4"
    _run_ffmpeg(
        [
            "-i", str(webm_path),
            "-i", str(narration_path),
            *_VIDEO_ENCODE_ARGS,
            "-c:a", "aac",
            "-shortest",
            str(final_path),
        ],
        "encode_with_audio",
    )
    return final_path


def encode_from_stills(
    frame_paths: list, scene_json: dict, narration_path: Path, run_id: str
) -> Path:
    """Dựng final.mp4 từ các ảnh tĩnh mỗi scene + narration, trong MỘT lượt ffmpeg.

    Thay cho đường "quay webm rồi transcode": ở đây không có lượt encode VP8
    nào, và x264 gặp toàn khung hình đứng yên nên chạy rất nhanh.

    Nhịp thời gian (audio vẫn là nguồn chuẩn duy nhất, y như trước):
      - scene i được kéo dài d_i + XFADE để có phần chồng lấn cho crossfade;
      - crossfade sang scene i bắt đầu đúng tại T_i = d_0 + ... + d_(i-1),
        tức đúng thời điểm câu thoại i bắt đầu vang lên — giống hệt lúc CSS
        transition khởi động ở đầu mỗi scene;
      - tổng video = sum(d) + XFADE, dài hơn narration đúng XFADE giây, nên
        -shortest cắt gọn phần đuôi thừa.
    """
    scenes = scene_json["scenes"]
    if len(frame_paths) != len(scenes):
        raise ValueError(
            f"encode_from_stills: có {len(frame_paths)} ảnh nhưng {len(scenes)} scene"
        )
    durations = [float(scene.get("duration") or 4) for scene in scenes]

    GENERATED_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    final_path = GENERATED_VIDEO_DIR / f"{run_id}_final.mp4"

    inputs = []
    for frame_path, duration in zip(frame_paths, durations):
        inputs += [
            "-loop", "1",
            "-framerate", str(FPS),
            "-t", f"{duration + XFADE_DURATION:.3f}",
            "-i", str(frame_path),
        ]
    inputs += ["-i", str(narration_path)]
    audio_index = len(frame_paths)

    # Chuẩn hoá từng ảnh về cùng fps/pixel format/timebase — xfade từ chối nối
    # hai luồng lệch nhau dù chỉ ở timebase.
    filters = [
        f"[{i}:v]fps={FPS},format=yuv420p,setsar=1,settb=AVTB[s{i}]"
        for i in range(len(frame_paths))
    ]
    last_label = "s0"
    offset = 0.0
    for i in range(1, len(frame_paths)):
        offset += durations[i - 1]
        filters.append(
            f"[{last_label}][s{i}]xfade=transition=fade:"
            f"duration={XFADE_DURATION}:offset={offset:.3f}[x{i}]"
        )
        last_label = f"x{i}"
    filters.append(f"[{last_label}]format=yuv420p[vout]")

    _run_ffmpeg(
        [
            *inputs,
            "-filter_complex", ";".join(filters),
            "-map", "[vout]",
            "-map", f"{audio_index}:a",
            *_VIDEO_ENCODE_ARGS,
            "-r", str(FPS),
            "-c:a", "aac",
            "-shortest",
            "-movflags", "+faststart",  # Telegram phát được ngay, không cần tải hết
            str(final_path),
        ],
        "encode_from_stills",
    )
    return final_path


async def generate_video_phase1(scene_json_path: str, assets: dict, run_id: str) -> Path:
    """No TTS - scene durations come straight from the hand-typed JSON."""
    scene_json = load_scene_json(scene_json_path)

    html_path = render_html(scene_json, assets, run_id)
    print(f"[pipeline] HTML rendered: {html_path}")

    webm_path = await record_html(html_path, run_id)
    print(f"[pipeline] Video recorded: {webm_path}")

    mp4_path = convert_to_mp4(webm_path)
    print(f"[pipeline] Final MP4 (no audio): {mp4_path}")

    return mp4_path


async def _tts_and_mux(scene_json: dict, assets: dict, run_id: str, voice: str) -> Path:
    """Shared tail of phases 2/3: TTS → real durations → render → record → mux."""
    from tts import synthesize_all_scenes, concat_audio

    if RECORD_MODE == "browser":
        # Đường cũ: trang tự phát scene bằng setTimeout theo "duration" nhúng
        # trong HTML, nên phải có duration THẬT trước khi render HTML.
        tts_result = await synthesize_all_scenes(scene_json, run_id, voice=voice)
        scene_json = tts_result["scene_json"]  # durations are now real, measured
        print(f"[pipeline] TTS (edge) generated for {len(tts_result['audio_paths'])} scenes")

        narration_path = concat_audio(tts_result["audio_paths"], run_id)
        print(f"[pipeline] Narration track: {narration_path}")

        html_path = render_html(scene_json, assets, run_id)
        print(f"[pipeline] HTML rendered: {html_path}")

        webm_path = await record_html(html_path, run_id)
        print(f"[pipeline] Video (silent) recorded: {webm_path}")

        final_path = encode_with_audio(webm_path, narration_path, run_id)
        print(f"[pipeline] Final MP4 (with audio): {final_path}")
        return final_path

    # Đường "stills": capture_scenes tự bấm từng scene rồi chụp, nó KHÔNG đọc
    # tới "duration" — chỉ cần biết có bao nhiêu scene và visual của từng scene.
    # Nhờ vậy chụp ảnh chạy song song được với TTS, và hai việc này không giành
    # tài nguyên của nhau: TTS là chờ mạng (gần như 0% CPU), chụp ảnh là CPU.
    # Trên máy ít core đây là phần thời gian cho không.
    #
    # Hệ quả: generated/html/<run_id>.html giữ duration placeholder (4s) thay vì
    # duration đo thật. Chỉ ảnh hưởng khi mở file HTML đó ra xem tay để debug —
    # nhịp của video thành phẩm do encode_from_stills quyết định, lấy từ
    # duration đo thật bên dưới.
    html_path = render_html(scene_json, assets, run_id)
    print(f"[pipeline] HTML rendered: {html_path}")

    capture_task = asyncio.create_task(capture_scenes(html_path, scene_json, run_id))
    try:
        tts_result = await synthesize_all_scenes(scene_json, run_id, voice=voice)
    except BaseException:
        # TTS hỏng thì đừng bỏ Chromium chạy mồ côi. cancel() mới chỉ là YÊU CẦU
        # huỷ — phải await tiếp thì task mới chạy được khối `finally:
        # await browser.close()` của capture_scenes. Bỏ qua bước await này là
        # để lại một tiến trình Chromium treo mỗi lần TTS lỗi.
        capture_task.cancel()
        try:
            await capture_task
        except BaseException:
            pass
        raise
    scene_json = tts_result["scene_json"]  # durations are now real, measured values
    print(f"[pipeline] TTS (edge) generated for {len(tts_result['audio_paths'])} scenes")

    frame_paths = await capture_task
    print(f"[pipeline] Captured {len(frame_paths)} scene stills")

    narration_path = concat_audio(tts_result["audio_paths"], run_id)
    print(f"[pipeline] Narration track: {narration_path}")

    final_path = encode_from_stills(frame_paths, scene_json, narration_path, run_id)
    print(f"[pipeline] Final MP4 (with audio): {final_path}")

    return final_path


async def generate_video_phase2(
    scene_json_path: str,
    assets: dict,
    run_id: str,
    voice: str = None,
) -> Path:
    """From a scene JSON file: TTS -> real durations -> render -> record -> mux audio.

    voice: edge-tts voice name (mặc định vi-VN-NamMinhNeural, xem tts.py).
    """
    scene_json = load_scene_json(scene_json_path)
    return await _tts_and_mux(scene_json, assets, run_id, voice)


async def generate_video_phase3(
    script_lines: list,
    assets: dict,
    run_id: str,
    voice: str = None,
) -> Path:
    """From external-AI dialogue lines (10-15) → designer → validator → video.

    script_lines: list of Vietnamese narration strings (10-15), produced by the
                  external AI and passed through by the Telegram bot.
    voice: edge-tts voice name (mặc định vi-VN-NamMinhNeural).
    """
    from designer import design_scenes
    from validator import validate_scene_json

    if not (10 <= len(script_lines) <= 15):
        raise ValueError(
            f"script_lines must be 10-15 lines, got {len(script_lines)}"
        )
    for ln in script_lines:
        if isinstance(ln, str):
            if not ln.strip():
                raise ValueError("Every script line must be a non-empty string")
        elif isinstance(ln, dict):
            if ln.get("char") not in ("A", "B", "both") or not str(ln.get("text", "")).strip():
                raise ValueError(
                    'Each dict line needs {"char": "A"|"B"|"both", "text": "..."}'
                )
        else:
            raise ValueError("Script lines must be strings or {char, text} dicts")

    scene_json = design_scenes(script_lines)
    validate_scene_json(scene_json)
    print(f"[pipeline] Scene JSON validated ({len(scene_json['scenes'])} scenes).")

    # Save the scene JSON for inspection/reuse
    scenes_dir = BASE_DIR / "generated" / "scripts"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    out_path = scenes_dir / f"{run_id}.json"
    out_path.write_text(
        json.dumps(scene_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[pipeline] Scene JSON saved: {out_path}")

    return await _tts_and_mux(scene_json, assets, run_id, voice)


if __name__ == "__main__":
    assets = {
        "background": str(BASE_DIR / "assets" / "background.jpg"),
        "character": str(BASE_DIR / "assets" / "character.png"),
        "character_confused": str(BASE_DIR / "assets" / "character_confused.png"),
        "image_a": str(BASE_DIR / "assets" / "A.jpg"),
        "image_b": str(BASE_DIR / "assets" / "B.jpg"),
    }

    result = asyncio.run(
        generate_video_phase2(
            scene_json_path=str(BASE_DIR / "generated" / "scripts" / "example_scene.json"),
            assets=assets,
            run_id="test_phase2",
        )
    )
    print("DONE (phase2):", result)

    result = asyncio.run(
        generate_video_phase3(
            script_lines=[
                "Đây là kẻ lừa đảo A.",
                "Đây là tay buôn lậu B.",
                "Vậy hai kẻ này có tội khác nhau thế nào.",
                "A dùng chiêu bài cũ, tinh vi và lặng lẽ.",
                "B thì phô trương, liều mạng như một màn sân khấu.",
                "Án dành cho A là 5 năm sau song sắt.",
                "Án dành cho B là 12 năm sau chấn song.",
                "Cả hai đều mượn hào quang để che đi bóng tối.",
                "Lá bài nào rồi cũng phải lật ngửa.",
                "Hãy sống đúng pháp luật, đừng học theo họ.",
            ],
            assets=assets,
            run_id="test_phase3",
        )
    )
    print("DONE (phase3):", result)