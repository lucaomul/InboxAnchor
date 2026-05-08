FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml requirements.txt README.md ./
COPY inboxanchor ./inboxanchor
COPY tests ./tests

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000 8501

CMD ["python", "-m", "uvicorn", "inboxanchor.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
