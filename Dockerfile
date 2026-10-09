FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
# шрифт с кириллицей для картинки-таймлайна
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY hackdigest ./hackdigest
ENV DB_PATH=/data/hackdigest.db PYTHONUNBUFFERED=1
VOLUME /data
CMD ["python", "-m", "hackdigest.bot"]
