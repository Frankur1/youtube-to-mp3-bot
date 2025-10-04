# ---- базовый образ ----
FROM python:3.13-slim

# ---- ставим ffmpeg и зависимости ----
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

# ---- рабочая директория ----
WORKDIR /app

# ---- копируем проект ----
COPY . .

# ---- ставим зависимости ----
RUN pip install --no-cache-dir -r requirements.txt

# ---- переменная окружения (Railway сам подставит) ----
ENV TOKEN=$TOKEN

# ---- команда запуска ----
CMD ["python3", "youtube_to_mp3_bot.py"]
