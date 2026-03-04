FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY src /app/src
COPY README.md /app/README.md

USER app

EXPOSE 8080

CMD ["python", "-m", "omi_openclaw_bridge"]
