FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl xz-utils libx11-6 libxi6 libxrender1 libxrandr2 libxfixes3 libxcursor1 libxinerama1 libglib2.0-0 libsm6 libice6 libgl1 \
  && rm -rf /var/lib/apt/lists/*

# Blender 4.1.1 Linux x64
RUN curl -L -o /tmp/blender.tar.xz https://download.blender.org/release/Blender4.1/blender-4.1.1-linux-x64.tar.xz \
 && mkdir -p /opt/blender \
 && tar -xf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 \
 && rm /tmp/blender.tar.xz

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker.py tasks.py /app/
COPY blender /app/blender

CMD ["python", "worker.py"]
