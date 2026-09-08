FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY webapp/backend/requirements.txt /app/webapp/backend/requirements.txt
RUN pip install --no-cache-dir \
    -r /app/requirements.txt \
    -r /app/webapp/backend/requirements.txt

COPY . /app

EXPOSE 8000
CMD ["uvicorn", "webapp.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
