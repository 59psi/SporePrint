FROM python:3.12.12-slim

RUN pip install --no-cache-dir --root-user-action=ignore --upgrade pip && \
    adduser --disabled-password --gecos "" --no-create-home appuser

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir --root-user-action=ignore .

COPY . .

USER appuser

ENV MPLCONFIGDIR=/tmp/matplotlib

EXPOSE 8000

CMD ["uvicorn", "app.main:socket_app", "--host", "0.0.0.0", "--port", "8000"]
