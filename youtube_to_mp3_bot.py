import os
import asyncio
import yt_dlp
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile

import ffmpeg  # ffmpeg-python

# ---------- CONFIG ----------
TOKEN = os.getenv("7975956634:AAGn28QsJThMu1JEgjw949DQ0KF5bDvKoHs", "ТВОЙ_ТОКЕН_ТУТ")  # <-- Заменить на свой токен или задать через env
DOWNLOAD_PATH = "downloads"
MAX_WORKERS = 2               # количество потоков в ThreadPool для блокирующих операций
QUEUE_MAXSIZE = 200           # макс. длина очереди
TG_MAX_BYTES = 50 * 1024 * 1024  # лимит Telegram ~50MB
COMPRESS_THRESHOLD_MB = 48    # если > этого — сжать
COMPRESSED_BITRATE = "96k"    # битрейт после сжатия
USE_COOKIES = os.path.exists("cookies.txt")  # автоматически подключаем cookies.txt, если есть
# ----------------------------

os.makedirs(DOWNLOAD_PATH, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()
# глобальная очередь задач: элементы — dict {id, user_id, chat_id, url}
task_queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


async def run_blocking(func, *args, **kwargs):
    """Запустить blocking-функцию в ThreadPoolExecutor и вернуть результат."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, lambda: func(*args, **kwargs))


def yt_download_blocking(url: str, outtmpl: str, ydl_opts: dict):
    """Блокирующая загрузка через yt-dlp (выполняется в потоке). Возвращает info dict."""
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return info


def compress_mp3_blocking(input_path: str, output_path: str, bitrate: str):
    """Сжатие через ffmpeg (блокирующая)."""
    # Здесь используем ffmpeg-python (он вызывает ffmpeg бинарь)
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
    await message.reply("Привет! Пришли ссылку на YouTube — я поставлю в очередь и пришлю MP3.")


def extract_links_from_text(text: str) -> list[str]:
    candidates = []
    parts = text.split()
    for p in parts:
        if "youtube.com" in p or "youtu.be" in p:
            # уберём возможные <> или знаки пунктуации в конце
            p = p.strip("<>.,;:()[]\"'")
            candidates.append(p)
    return candidates


@dp.message()
async def handle_any_message(message: types.Message):
    if not message.text:
        return

    links = extract_links_from_text(message.text)
    if not links:
        # опционально: игнорировать другие сообщения
        return

    responses = []
    for url in links:
        if task_queue.full():
            await message.reply("⚠️ Очередь переполнена — попробуй позже.")
            break
        # создаём задачу
        job = {
            "url": url,
            "user_id": message.from_user.id,
            "chat_id": message.chat.id,
            "from_username": message.from_user.username or message.from_user.first_name,
        }
        await task_queue.put(job)
        position = task_queue.qsize()
        responses.append(f"✅ Ссылка поставлена в очередь (позиция ~{position}): {url}")

    if responses:
        await message.reply("\n".join(responses))


async def worker_loop():
    """Фоновой воркер: вытягивает задачи и обрабатывает по очереди."""
    logger.info("Worker started")
    task_id = 0
    while True:
        job = await task_queue.get()
        task_id += 1
        url = job["url"]
        chat_id = job["chat_id"]
        username = job.get("from_username", "user")
        logger.info(f"[#{task_id}] Start job for {username}: {url}")

        try:
            await bot.send_message(chat_id, f"🔁 Начинаю обработку: {url}")

            # подготовка параметров yt-dlp
            safe_title_template = os.path.join(DOWNLOAD_PATH, "%(title)s.%(ext)s")
            ydl_opts = {
                "format": "bestaudio/best",
                "noplaylist": True,
                "outtmpl": safe_title_template,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "quiet": True,
                "nocheckcertificate": True,
                "extractor_retries": 10,
                "skip_unavailable_fragments": True,
                "source_address": "0.0.0.0",
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
            }
            if USE_COOKIES:
                ydl_opts["cookiefile"] = "cookies.txt"

            # выполняем загрузку в потоке
            info = await run_blocking(yt_download_blocking, url, safe_title_template, ydl_opts)

            title = info.get("title") or "song"
            raw_filename = os.path.join(DOWNLOAD_PATH, f"{title}.mp3")
            # yt-dlp может создавать файл с расширением .mp3 сразу (FFmpegExtractAudio)
            if not os.path.exists(raw_filename):
                # если название содержит непечатаемые символы, попробуем найти файл в папке
                candidates = [f for f in os.listdir(DOWNLOAD_PATH) if f.lower().endswith(".mp3")]
                if candidates:
                    # возьмём самый новый mp3
                    candidates_sorted = sorted(candidates, key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_PATH, f)), reverse=True)
                    raw_filename = os.path.join(DOWNLOAD_PATH, candidates_sorted[0])
                else:
                    raise FileNotFoundError("После yt-dlp не найден mp3-файл.")

            size_mb = file_size_mb(raw_filename)
            logger.info(f"[#{task_id}] Downloaded '{title}' size={size_mb:.2f} MB")

            # Если файл > COMPRESS_THRESHOLD_MB, сжимаем
            final_filename = raw_filename
            if size_mb > COMPRESS_THRESHOLD_MB:
                await bot.send_message(chat_id, f"🔊 Файл {size_mb:.1f}MB — сжимаю до {COMPRESSED_BITRATE}...")
                compressed = os.path.join(DOWNLOAD_PATH, f"{title}_small.mp3")
                await run_blocking(compress_mp3_blocking, raw_filename, compressed, COMPRESSED_BITRATE)
                # проверим размер нового
                new_mb = file_size_mb(compressed)
                logger.info(f"[#{task_id}] Compressed size={new_mb:.2f} MB")
                # заменим если всё ок
                os.remove(raw_filename)
                final_filename = compressed

            # Финальная проверка размера — Telegram не примет > TG_MAX_BYTES
            final_size = os.path.getsize(final_filename)
            if final_size > TG_MAX_BYTES:
                # если даже после сжатия > 50MB — отправляем сообщение с ошибкой и предлагаем скачать напрямую
                await bot.send_message(chat_id, "⚠️ Файл всё ещё больше 50MB после сжатия — я не могу отправить его в Telegram.")
                # можно предложить загрузку на внешний файлообменник — но этого в коде нет.
            else:
                await bot.send_message(chat_id, "📤 Отправляю аудио...")
                audio_input = FSInputFile(final_filename)
                await bot.send_audio(chat_id, audio_input, title=title)
                await bot.send_message(chat_id, "✅ Готово.")

            # Убираем файл
            try:
                if os.path.exists(final_filename):
                    os.remove(final_filename)
            except Exception as e_rm:
                logger.warning(f"Не смог удалить файл {final_filename}: {e_rm}")

        except Exception as e:
            logger.exception("Ошибка в обработке задания")
            # пошлём краткую ошибку пользователю
            try:
                await bot.send_message(chat_id, f"❌ Ошибка при обработке ссылки:\n{e}")
            except Exception:
                pass

        finally:
            task_queue.task_done()
            await asyncio.sleep(0.5)  # маленькая пауза между задачами


async def on_startup():
    # стартуем воркер(ы)
    asyncio.create_task(worker_loop())
    logger.info("Bot startup complete")


if __name__ == "__main__":
    try:
        # запускаем polling
        import signal

        # register on_startup
        dp.startup.register(on_startup)
        logger.info("Starting polling...")
        # run bot
        import asyncio
        asyncio.run(dp.start_polling(bot))
    finally:
        executor.shutdown(wait=False)
        # очищаем временные файлы, если нужно (необязательно)
        # shutil.rmtree(DOWNLOAD_PATH, ignore_errors=True)
