# Используем минимальный официальный Python
FROM python:3.13-slim

# Обновляем пакеты и ставим ffmpeg
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем всё содержимое проекта
COPY . .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Задаем переменную окружения для токена (Railway сам подставит)
ENV TOKEN=$TOKEN

# Запускаем бота
CMD ["python3", "youtube_to_mp3_bot.py"]
