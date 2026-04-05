FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY . .
CMD ["uvicorn", "app.main:socket_app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
