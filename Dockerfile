FROM python:3.12-slim

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Tesseract OCR
    tesseract-ocr \
    tesseract-ocr-eng \
    # Poppler (for pdf2image / pdftoppm)
    poppler-utils \
    # LibreOffice headless (minimal install for .doc → .docx and PPTX charts)
    libreoffice-writer \
    libreoffice-impress \
    # WeasyPrint C library dependencies
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    # ImageMagick for EMF/WMF conversion
    imagemagick \
    # ExifTool for Adobe file metadata extraction
    libimage-exiftool-perl \
    # ffmpeg for keyframe extraction and media processing
    ffmpeg \
    # curl for healthchecks
    curl \
    # Misc build tools
    gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories that may not exist in the repo
RUN mkdir -p input output logs data static

# Expose FastAPI port + MCP server port
EXPOSE 8000 8001

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
