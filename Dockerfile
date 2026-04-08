# ============================================================
#  MarkFlow Application Image
#  Builds on top of markflow-base:latest (system deps).
#
#  If you haven't built the base yet, run:
#    docker build -f Dockerfile.base -t markflow-base:latest .
#
#  Then:  docker compose up -d --build
# ============================================================
FROM markflow-base:latest

WORKDIR /app

# v0.22.14: Ghostscript was added to Dockerfile.base for EPS conversion
# via Pillow. The line below installs it on top of the existing base
# image so this version can ship without a 25-min base rebuild. The
# next time the base image is rebuilt, this becomes a no-op (apt-get
# will report ghostscript already installed). Safe to leave indefinitely.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ghostscript \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (layer cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories that may not exist in the repo
RUN mkdir -p input output logs data static

# NVIDIA OpenCL ICD — tells the OpenCL loader about the NVIDIA GPU.
# Docker --gpus mounts libnvidia-opencl.so at runtime, but the container
# needs this vendor file for hashcat/clinfo to discover it. Harmless without GPU.
RUN mkdir -p /etc/OpenCL/vendors \
    && echo "libnvidia-opencl.so.1" > /etc/OpenCL/vendors/nvidia.icd

# Expose FastAPI port + MCP server port
EXPOSE 8000 8001

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
