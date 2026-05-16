FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_PORT=5000 \
    TZ=Asia/Shanghai

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/pdfs && \
    groupadd -r appuser && useradd -r -g appuser appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')"

CMD ["python", "app.py"]
