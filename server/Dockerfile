FROM python:3.12.12-slim

RUN pip install --no-cache-dir --upgrade pip && \
    adduser --disabled-password --no-create-home appuser

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir --root-user-action=ignore .

COPY . .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:socket_app", "--host", "0.0.0.0", "--port", "8000"]
