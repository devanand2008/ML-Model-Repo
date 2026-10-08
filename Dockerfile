FROM node:22-bookworm-slim AS frontend
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 ffmpeg && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app/backend
COPY training /app/training
COPY scripts /app/scripts
COPY documentation /app/documentation
COPY --from=frontend /web/dist /app/frontend/dist
RUN useradd --create-home visionx && mkdir -p /app/weights /app/uploads /app/outputs /app/reports /app/data && chown -R visionx:visionx /app
USER visionx
ENV DATABASE_URL=sqlite+aiosqlite:////app/data/visionx.db APP_HOST=0.0.0.0 TRANSIT_FORECAST_DIR=/app/data/forecasting TRANSIT_DEMAND_DATASET=/app/data/synthetic/transit_demand.csv.gz
EXPOSE 8000
CMD ["uvicorn", "main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
