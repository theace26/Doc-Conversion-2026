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
