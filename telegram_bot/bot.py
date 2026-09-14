"""bot.py — Telegram bot: nhận 2 ảnh nhân vật + kịch bản JSON, render video local, gửi mp4.

Chạy:
    python -m telegram_bot.bot

Luồng: /start → bot gửi prompt cho AI ngoài (ChatGPT/Gemini) → user dán prompt
vào AI ngoài, trả lời 2 câu (nhân vật A/B là ai), AI ngoài tự nghiên cứu và xuất
JSON (mảng 10-15 câu thoại) + tóm tắt → user gửi về bot: 2 ảnh nhân vật + đoạn
JSON → bot validate, render bằng pipeline local (edge-tts, giọng mặc định) →
gửi video mp4 cho user.
"""
import asyncio
import glob
import json
import shutil
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, Message

from telegram_bot.config import (
    BOT_TOKEN,
    DEFAULT_VOICE,
    JOBS_DIR,
    LOCAL_VENV_PYTHON,
)

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "external_ai.txt"
EXTERNAL_AI_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
LOCAL_JOB = Path(__file__).resolve().parent / "local_job.py"

MIN_LINES = 10
MAX_LINES = 15

# Chỉ chạy 1 job render cùng lúc — tránh _purge_old_data xóa nhầm job đang chạy.
RENDER_LOCK = asyncio.Lock()

# asyncio chỉ giữ weak-ref tới task; không neo lại thì GC có thể huỷ job
# render giữa chừng (user chờ mãi không có video). Giữ strong-ref ở đây.
_RENDER_TASKS: set = set()

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)


class Job(StatesGroup):
    wait_json = State()
    wait_photo_a = State()
    wait_photo_b = State()


# ============================== /start, /cancel ==============================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Job.wait_json)
    await message.answer(
        f"{EXTERNAL_AI_PROMPT}"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Đã hủy. Gõ /start để làm lại.")


# ============ bước 1: JSON kịch bản ============

@router.message(Job.wait_json)
async def on_scene_json(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Gửi đoạn JSON kịch bản (mảng 10-15 câu thoại).")
        return
    try:
        lines = json.loads(text)
    except json.JSONDecodeError:
        await message.answer(
            "❌ Không parse được JSON. Gửi lại đúng mảng JSON AI ngoài xuất ra, "
            "vd:\n<code>[{&quot;char&quot;:&quot;A&quot;,&quot;text&quot;:&quot;...&quot;}, ...]</code>"
        )
        return

    if not isinstance(lines, list):
        await message.answer("❌ JSON phải là 1 mảng các câu thoại (vd: <code>[...]</code>).")
        return
    if not (MIN_LINES <= len(lines) <= MAX_LINES):
        await message.answer(
            f"❌ Kịch bản cần có {MIN_LINES}-{MAX_LINES} câu, bạn gửi {len(lines)} câu. "
            "Nhờ AI ngoài viết lại cho đủ số câu nhé."
        )
        return

    norm = []
    for i, ln in enumerate(lines):
        if isinstance(ln, str):
            if not ln.strip():
                await message.answer(f"❌ Câu {i+1} trống — kiểm tra lại JSON.")
                return
            norm.append(ln)
        elif isinstance(ln, dict):
            char = str(ln.get("char", "")).strip()
            t = str(ln.get("text", "")).strip()
            if char not in ("A", "B", "both") or not t:
                await message.answer(
                    f"❌ Câu {i+1} sai định dạng — mỗi phần tử cần "
                    "<code>{&quot;char&quot;:&quot;A&quot;|&quot;B&quot;|&quot;both&quot;,&quot;text&quot;:&quot;...&quot;}</code>."
                )
                return
            norm.append({"char": char, "text": t})
        else:
            await message.answer(f"❌ Câu {i+1} không phải chuỗi hay đối tượng JSON.")
            return

    data = await state.get_data()
    data["script_lines"] = norm
    await state.set_data(data)
    await state.set_state(Job.wait_photo_a)
    await message.answer(
        f"✅ Đã nhận kịch bản ({len(lines)} câu).\n\n"
        "Giờ gửi <b>ảnh nhân vật A</b>."
    )


# ============ bước 2: ảnh nhân vật A ============

async def _save_photo(message: Message, state: FSMContext, filename: str) -> tuple:
    """Tải ảnh user gửi vào thư mục staging của job, trả về FSM data mới."""
    data = await state.get_data()
    staging = data.get("staging")
    if staging:
        staging = Path(staging)
    else:
        staging = JOBS_DIR / f"staging_{message.from_user.id}_{uuid.uuid4().hex[:6]}"
        staging.mkdir(parents=True, exist_ok=True)
        data["staging"] = str(staging)
    path = staging / filename
    await message.bot.download(message.photo[-1], destination=path)
    return data, path


@router.message(Job.wait_photo_a, F.photo)
async def on_photo_a(message: Message, state: FSMContext):
    data, path = await _save_photo(message, state, "a.jpg")
    data["photo_a"] = str(path)
    await state.set_data(data)
    await state.set_state(Job.wait_photo_b)
    await message.answer("✅ Đã nhận ảnh <b>nhân vật A</b>. Giờ gửi <b>ảnh nhân vật B</b>.")


@router.message(Job.wait_photo_a)
async def on_photo_a_wrong(message: Message):
    await message.answer("⏳ Đang chờ <b>ảnh nhân vật A</b> — gửi 1 ảnh (không phải văn bản).")


# ============ bước 3: ảnh nhân vật B → render ============

@router.message(Job.wait_photo_b, F.photo)
async def on_photo_b(message: Message, state: FSMContext):
    data, path = await _save_photo(message, state, "b.jpg")
    data["photo_b"] = str(path)

    await state.clear()
    await message.answer("✅ Đã đủ: JSON + 2 ảnh. Đang render video… (vài phút)")
    task = asyncio.create_task(_render_and_send(message.bot, message.chat.id, data))
    _RENDER_TASKS.add(task)
    task.add_done_callback(_RENDER_TASKS.discard)


@router.message(Job.wait_photo_b)
async def on_photo_b_wrong(message: Message):
    await message.answer("⏳ Đang chờ <b>ảnh nhân vật B</b> — gửi 1 ảnh (không phải văn bản).")


# ============================== render local ==============================

def _purge_old_data(job_dir: Path, keep_dirs: tuple = ()) -> None:
    """Xóa toàn bộ data của các job trước (để máy luôn nhẹ).

    - Mọi job_id*/staging* còn sót trong JOBS_DIR (trừ job_dir đang dùng
      và các thư mục trong keep_dirs, vd staging ảnh A/B của job hiện tại).
    - Mọi artifact trong kaggle-pipeline/generated (audio/html/scripts/videos)
      trừ các file .gitkeep.
    Chạy ở đầu mỗi job mới.
    """
    keep = {Path(p) for p in keep_dirs if p}
    keep.add(job_dir)
    for child in JOBS_DIR.iterdir():
        if child in keep:
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
        except Exception:
            pass

    gen_root = Path(__file__).resolve().parent.parent / "generated"
    for sub in ("audio", "html", "scripts", "videos"):
        d = gen_root / sub
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.name == ".gitkeep":
                continue
            try:
                if f.is_dir():
                    shutil.rmtree(f, ignore_errors=True)
                else:
                    f.unlink()
            except Exception:
                pass


def _cleanup(data: dict, *dirs) -> None:
    paths = list(dirs)
    staging = data.get("staging")
    if staging:
        paths.append(Path(staging))
    for p in paths:
        try:
            if Path(p).is_dir():
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass
    # Dọn artifact trung gian của pipeline cho riêng run này.
    # KHÔNG xóa video _final.mp4 ở đây — nó chỉ bị xóa SAU khi gửi thành công.
    run_id = data.get("run_id")
    if not run_id:
        return
    base = Path(__file__).resolve().parent.parent / "generated"
    # Xoá cả thư mục audio/<run_id>: bản cũ chỉ xoá file bên trong, để lại
    # thư mục rỗng tích tụ dần sau mỗi job.
    shutil.rmtree(base / "audio" / run_id, ignore_errors=True)
    for pat in (f"html/{run_id}.html", f"scripts/{run_id}.json",
                f"videos/{run_id}.mp4", f"videos/{run_id}.webm"):
        for f in glob.glob(str(base / pat)):
            try:
                Path(f).unlink()
            except Exception:
                pass


async def _render_and_send(bot_: Bot, chat_id: int, data: dict) -> None:
    async with RENDER_LOCK:
        await _render_and_send_locked(bot_, chat_id, data)


async def _render_and_send_locked(bot_: Bot, chat_id: int, data: dict) -> None:
    job_id = uuid.uuid4().hex[:8]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    _purge_old_data(job_dir, keep_dirs=(data.get("staging"),))

    meta = {
        "run_id": f"tg_{job_id}",
        "voice": DEFAULT_VOICE,
        "script_lines": data["script_lines"],
    }
    (job_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    # Gán run_id NGAY: bản cũ chỉ gán sau khi render xong, nên mỗi lần render
    # lỗi là audio/html/scripts/webm của run đó nằm lại vĩnh viễn trên đĩa.
    data["run_id"] = meta["run_id"]

    shutil.copy(data["photo_a"], job_dir / "image_a.jpg")
    shutil.copy(data["photo_b"], job_dir / "image_b.jpg")

    mp4: Path | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            LOCAL_VENV_PYTHON, str(LOCAL_JOB), str(job_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await _drain_output(proc, f"[job:{job_id}]")
        await proc.wait()

        result_path = job_dir / "result.json"
        if not result_path.exists():
            await bot_.send_message(chat_id, "❌ Không nhận được kết quả render.")
            return
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("ok"):
            await bot_.send_message(chat_id, f"❌ Render thất bại: {result.get('error')}")
            return

        mp4 = Path(result["mp4"])
        if not mp4.exists():
            await bot_.send_message(chat_id, "❌ Không thấy file video sau khi render.")
            return
    except Exception as e:
        await bot_.send_message(chat_id, f"⚠️ Lỗi khi chạy render: {e}")
        return
    finally:
        # Dọn job_dir/staging/trung gian; KHÔNG xóa _final.mp4 (đang chờ gửi)
        _cleanup(data, job_dir)

    # Gửi với retry — chỉ xóa video SAU khi gửi thành công.
    await _send_video_with_retry(bot_, chat_id, mp4)
    # Gửi xong (dù thành công hay bỏ cuộc sau retry) mới xóa video gốc
    try:
        mp4.unlink()
    except OSError:
        pass


async def _drain_output(proc, tag: str) -> None:
    """In log worker theo từng dòng ngay khi nó phát ra.

    Bản cũ dùng proc.communicate(): giữ TOÀN BỘ stdout của cả job render trong
    RAM cho tới khi worker kết thúc. Đọc theo dòng thì bộ nhớ luôn là hằng số,
    và log hiện ra ngay thay vì đợi render xong mới thấy.
    """
    stream = proc.stdout
    if stream is None:
        return
    while True:
        try:
            line = await stream.readline()
        except (ValueError, asyncio.LimitOverrunError):
            continue  # dòng dài bất thường: readline đã nuốt buffer rồi, bỏ qua
        if not line:
            break
        print(tag, line.decode(errors="replace").rstrip(), flush=True)


async def _send_video_with_retry(bot_: Bot, chat_id: int, mp4: Path,
                                 max_retries: int = 3) -> bool:
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        if not mp4.exists():
            await bot_.send_message(chat_id, "❌ File video đã bị mất trước khi gửi.")
            return False
        try:
            await bot_.send_video(chat_id, FSInputFile(mp4),
                                  caption="Video so sánh A/B của bạn ✅")
            return True
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[job] send_video attempt {attempt} failed: {e}")
            if attempt < max_retries:
                await asyncio.sleep(3 * attempt)
    await bot_.send_message(chat_id, f"⚠️ Không gửi được video sau {max_retries} lần: {last_err}")
    return False


async def main() -> None:
    # start_polling sẽ raise nếu mạng/Telegram lỗi — bọc để bot tự khởi động
    # lại polling thay vì chết hẳn (mạng VN hay flaky).
    try:
        while True:
            try:
                await dp.start_polling(bot)
                return
            except Exception as e:  # noqa: BLE001
                print(f"polling crashed: {e} — restarting in 5s...")
                await asyncio.sleep(5)
    finally:
        # Không đóng thì aiohttp connector + socket của bot bị bỏ lại khi thoát.
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())