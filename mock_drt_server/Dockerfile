FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
EXPOSE 8000
CMD ["sh", "-c", "python scripts/initialize_db.py && python scripts/run_server.py"]
