FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl && rm -rf /var/lib/apt/lists/*

COPY . /app

# Bootstrap foundation
RUN chmod +x bootstrap.sh && bash bootstrap.sh

# Install app deps
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir fastapi uvicorn pydantic

ENV PYTHONPATH=/app/foundation
ENV PORT=8080
# Injected at run time from the host OS keychain via scripts/docker-run.sh
# (explicit -e BASETEN_API_KEY=... also works). Never baked into the image.
ENV BASETEN_API_KEY=""

EXPOSE 8080

RUN chmod +x start.sh
CMD ["./start.sh"]
