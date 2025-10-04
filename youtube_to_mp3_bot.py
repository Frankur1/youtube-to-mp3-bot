import os
import yt_dlp
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile

# 🔥 Твой токен
TOKEN = "7975956634:AAGn28QsJThMu1JEgjw949DQ0KF5bDvKoHs"

bot = Bot(token=TOKEN)
dp = Dispatcher()

DOWNLOAD_PATH = "downloads"
os.makedirs(DOWNLOAD_PATH, exist_ok=True)


@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer("🎵 Ուղարկիր YouTube հղումը, ես այն կվերածեմ MP3-ի և կուղարկեմ քեզ։")


@dp.message(lambda message: "youtube.com" in message.text or "youtu.be" in message.text)
async def handle_youtube_link(message: types.Message):
    url = message.text.strip()
    await message.answer("⏳ Ներբեռնում եմ վիդեոն, մի քիչ սպասիր...")

    # Настройки для yt-dlp
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'outtmpl': os.path.join(DOWNLOAD_PATH, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'nocheckcertificate': True,
        # 👇 Новые параметры для обхода блокировок YouTube
        'extractor_retries': 10,
        'skip_unavailable_fragments': True,
        'source_address': '0.0.0.0',
        'user_agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0 Safari/537.36'
        ),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            title = info_dict.get("title", "song")
            filename = os.path.join(DOWNLOAD_PATH, f"{title}.mp3")

        await message.answer("📤 Ուղարկում եմ ֆայլը...")

        audio_file = FSInputFile(filename)
        await message.answer_audio(audio_file, title=title)

        os.remove(filename)

    except Exception as e:
        await message.answer(f"⚠️ Սխալ տեղի ունեցավ:\n{e}")


async def main():
    print("🤖 Բոտը աշխատում է...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
