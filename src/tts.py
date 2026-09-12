"""
tts.py - Phase 2

Turns each scene's text into a Vietnamese voice clip using edge-tts
(free, no API key, no local GPU). The voice is an edge-tts voice name:

- "vi-VN-NamMinhNeural" (mặc định, nam miền Bắc)
- "vi-VN-HoaiMyNeural"  (nữ miền Bắc)

Per spec: the LLM never estimates spoken duration. Each scene's audio is
generated first, its REAL duration is measured with ffprobe, and that
measured value overwrites the scene's "duration" field - audio is the
single source of truth for timing.
"""

import asyncio
import subprocess
from pathlib import Path

import edge_tts

BASE_DIR = Path(__file__).resolve().parent.parent
GENERATED_AUDIO_DIR = BASE_DIR / "generated" / "audio"

EDGE_DEFAULT_VOICE = "vi-VN-NamMinhNeural"


def get_audio_duration(path: Path) -> float:
    """Exact duration in seconds via ffprobe (never estimated)."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


class TTSBackend:
    """Edge-tts facade. Instantiated once per run."""
    def __init__(self, voice=None, rate: str = "+25%", max_retries: int = 3):
        self.voice = voice or EDGE_DEFAULT_VOICE
        self.rate = rate
        self.max_retries = max_retries

    async def synthesize(self, text: str, out_path: Path) -> float:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
                await communicate.save(str(out_path))
                return get_audio_duration(out_path)
            except Exception as e:  # noqa: BLE001 - mạng edge-tts hay flaky, thử lại
                last_err = e
                print(f"[tts] attempt {attempt} failed: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(2 * attempt)
        raise RuntimeError(
            f"edge-tts thất bại sau {self.max_retries} lần cho câu "
            f"'{text[:50]}...': {last_err}"
        )


async def synthesize_all_scenes(scene_json: dict, run_id: str,
                                voice: str = None) -> dict:
    """
    Generates one audio clip per scene (in generated/audio/<run_id>/scene_NN.mp3),
    overwrites each scene's 'duration' with the real measured value, and returns
    the updated scene_json plus the ordered list of audio paths.

    voice: edge-tts voice name (mặc định vi-VN-NamMinhNeural).
    """
    backend = TTSBackend(voice=voice)

    run_audio_dir = GENERATED_AUDIO_DIR / run_id
    audio_paths = [
        run_audio_dir / f"scene_{i:02d}.mp3"
        for i in range(len(scene_json["scenes"]))
    ]

    for i, scene in enumerate(scene_json["scenes"]):
        duration = await backend.synthesize(scene["text"], audio_paths[i])
        scene["duration"] = round(duration, 3)

    return {"scene_json": scene_json, "audio_paths": audio_paths}


def concat_audio(audio_paths: list, run_id: str) -> Path:
    """Concatenate per-scene clips (in scene order) into one narration track."""
    run_audio_dir = GENERATED_AUDIO_DIR / run_id
    concat_list_path = run_audio_dir / "concat_list.txt"
    concat_list_path.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in audio_paths),
        encoding="utf-8",
    )
    final_audio_path = run_audio_dir / "narration.wav"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list_path),
            "-ar", "44100",
            "-ac", "1",
            str(final_audio_path),
        ],
        check=True, capture_output=True,
    )
    return final_audio_path