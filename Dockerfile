FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY hackdigest ./hackdigest
ENV DB_PATH=/data/hackdigest.db PYTHONUNBUFFERED=1
VOLUME /data
CMD ["python", "-m", "hackdigest.bot"]
