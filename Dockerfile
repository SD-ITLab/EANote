# Stage 1: Build Tailwind CSS
# ─────────────────────────────────
FROM node:18-alpine AS builder
WORKDIR /app

# 1) Kopiere package.json (ohne package-lock.json, falls nicht vorhanden)
COPY package.json ./

# 2) Installiere Tailwind + PostCSS
RUN npm install tailwindcss postcss autoprefixer

# 3) Kopiere Configs + Quelldatei
COPY tailwind.config.js postcss.config.js ./
COPY src/styles.css ./

# 4) Baue das CSS
RUN npx tailwindcss -i ./styles.css -o ./tailwind.css --minify



# Stage 2: Python App
# ───────────────────────────────────────────────
FROM python:3.11-slim


# System-Dependencies für pylibdmtx (distutils) und ggfs. libdmtx
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3-distutils \
      build-essential \
      libdmtx-dev \
      pkg-config \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# System-User für Sicherheit
RUN useradd -ms /bin/bash appuser

# Python-Abhängigkeiten installieren
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Gebautes Tailwind-CSS ins Static-Verzeichnis übernehmen
COPY --from=builder /app/tailwind.css app/static/css/tailwind.css

# Restlichen App-Code kopieren
COPY app .

# Als Nicht-Root ausführen
USER appuser
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]
