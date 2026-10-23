# pbw gemoy — FastAPI backend + Vue frontend in one container.
# Stage 1: build the Vue frontend (frontend/dist)
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python app; the node binary is kept because ima-skill/ima_api.cjs runs on Node
FROM python:3.13-slim
COPY --from=web /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=web /web/dist ./frontend/dist

# Hosting platforms (ModelScope / Hugging Face Docker spaces) expect port 7860.
# Secrets (IMA_OPENAPI_CLIENTID, IMA_OPENAPI_APIKEY, LLM_API_KEY, ...) are set in the platform's
# environment settings, never baked into the image.
ENV PORT=7860 \
    KB_BACKEND=ima \
    DEMO_TODAY=2026-10-23 \
    PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["python", "server.py"]