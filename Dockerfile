FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY scripts ./scripts

RUN mkdir -p /app/data
# PaaS（Render/Railway/Fly）会注入 PORT 并要求监听该端口；本地/云服务器默认 8010
ENV PORT=8010
EXPOSE 8010
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8010}"]
