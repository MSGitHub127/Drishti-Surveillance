FROM python:3.12-slim

WORKDIR /app

# Install system runtime dependencies for OpenCV & PostGIS client
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download and cache EasyOCR model weights at build time (prevents runtime cold-start stall)
RUN python -c "import easyocr; easyocr.Reader(['en'], gpu=False, verbose=False)"

# Copy models and application source code
COPY yolov8n.pt ./yolov8n.pt
COPY license_plate_detector.pt ./license_plate_detector.pt
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY data/ ./data/
COPY test-footage/ ./test-footage/

ENV PYTHONPATH=/app/backend
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "backend/run.py"]
