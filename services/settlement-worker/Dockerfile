FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY worker.py .

RUN chgrp -R 0 /app && chmod -R g=u /app

USER 1001

CMD ["python", "worker.py"]
