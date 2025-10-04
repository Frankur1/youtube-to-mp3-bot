import os
import asyncio
import yt_dlp
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
import ffmpeg

# ====== НАСТРОЙКИ ======
TOKEN = "7975956634:AAGn28QsJThMu1JEgjw949DQ0KF5bDvKoHs"
DOWNLOAD_PATH = "downloads"
MAX_WORKERS = 2
QUEUE_MAXSIZE = 200
TG_MAX_BYTES = 50 * 1024 * 1024
COMPRESS_THRESHOLD_MB = 48
COMPRESSED_BITRATE = "96k"
USE_COOKIES = os.path.exists("cookies.txt")
# ========================

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()
task_queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


async def run_blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, lambda: func(*args, **kwargs))


def yt_download_blocking(url: str, outtmpl: str, ydl_opts: dict):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return info


def compress_mp3_blocking(input_path: str, output_path: str, bitrate: str):
    (
        ffmpeg
        .input(input_path)
        .output(output_path, audio_bitrate=bitrate, vn=None)
        .run(overwrite_output=True, quiet=True)
    )


def file_size_mb(path: str) -> float:
    return os.path.getsize(path) / (1024 * 1024)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply("🎶 Привет! Отправь одну или несколько YouTube ссылок — я превращу их в MP3.")


def extract_links_from_text(text: str) -> list[str]:
    links = []
    for part in text.split():
        if "youtube.com" in part or "youtu.be" in part:
            part = part.strip("<>.,;:()[]\"'")
            links.append(part)
    return links


@dp.message()
async def handle_message(message: types.Message):
    if not message.text:
        return

    links = extract_links_from_text(message.text)
    if not links:
        return

    added = 0
    for url in links:
        if task_queue.full():
            await message.reply("⚠️ Очередь переполнена. Попробуй позже.")
            return
        job = {"url": url, "chat_id": message.chat.id}
        await task_queue.put(job)
        added += 1

    if added == 1:
        await message.reply("🎧 Песня добавлена в очередь, скоро будет готово.")
    else:
        await message.reply(f"🎵 Добавлено {added} песен. Начинаю загрузку...")


async def worker_loop():
    logger.info("Worker started")
    while True:
        job = await task_queue.get()
        url = job["url"]
        chat_id = job["chat_id"]

        try:
            safe_template = os.path.join(DOWNLOAD_PATH, "%(title)s.%(ext)s")
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": safe_template,
                "noplaylist": True,
                "quiet": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            }
            if USE_COOKIES:
                ydl_opts["cookiefile"] = "cookies.txt"

            info = await run_blocking(yt_download_blocking, url, safe_template, ydl_opts)
            title = info.get("title", "audio")
            mp3_path = os.path.join(DOWNLOAD_PATH, f"{title}.mp3")

            if not os.path.exists(mp3_path):
                files = [f for f in os.listdir(DOWNLOAD_PATH) if f.endswith(".mp3")]
                if files:
                    mp3_path = os.path.join(DOWNLOAD_PATH, max(files, key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_PATH, f))))

            size = file_size_mb(mp3_path)
            final_path = mp3_path

            if size > COMPRESS_THRESHOLD_MB:
                compressed = os.path.join(DOWNLOAD_PATH, f"{title}_small.mp3")
                await run_blocking(compress_mp3_blocking, mp3_path, compressed, COMPRESSED_BITRATE)
                os.remove(mp3_path)
                final_path = compressed

            if os.path.getsize(final_path) > TG_MAX_BYTES:
                await bot.send_message(chat_id, f"⚠️ {title} слишком большой (>{TG_MAX_BYTES//1024//1024}MB).")
            else:
                await bot.send_audio(chat_id, FSInputFile(final_path), title=title)

            os.remove(final_path)

        except Exception as e:
            logger.error(f"Ошибка: {e}")
            try:
                await bot.send_message(chat_id, f"❌ Ошибка при обработке: {e}")
            except:
                pass

        finally:
            task_queue.task_done()
            await asyncio.sleep(0.5)


async def on_startup():
    asyncio.create_task(worker_loop())
    logger.info("Бот запущен.")


if __name__ == "__main__":
    dp.startup.register(on_startup)
    asyncio.run(dp.start_polling(bot))
