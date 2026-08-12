# 빌드 컨텍스트는 repo root여야 한다 (bridge/, carecall_drt/, care_call_bot/를 import하므로).
# Render 블루프린트: dockerfilePath: ./main_server/Dockerfile, dockerContext: .
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt requirements-analyzer.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-analyzer.txt
COPY bridge/ ./bridge/
COPY carecall_drt/ ./carecall_drt/
COPY care_call_bot/ ./care_call_bot/
COPY main_server/ ./main_server/
COPY data/ ./data/
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
EXPOSE 8002
CMD ["sh", "-c", "python -m uvicorn main_server.app:app --host 0.0.0.0 --port ${PORT:-8002}"]
