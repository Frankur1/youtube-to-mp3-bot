FROM python:3.13-slim
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python3", "youtube_to_mp3_bot.py"]
