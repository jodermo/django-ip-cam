    # --- Base Image ---
    FROM python:3.11-slim

    # --- Set environment variables ---
    ENV PYTHONDONTWRITEBYTECODE=1
    ENV PYTHONUNBUFFERED=1
    
    # --- Working directory ---
    WORKDIR /app
    
    # --- System dependencies (OpenCV + V4L2 support) ---
    RUN apt-get update && apt-get install -y \
    v4l-utils \
    libglib2.0-0 libsm6 libxrender1 libxext6 libopencv-dev gcc \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

    # --- Install dependencies ---
    COPY requirements.txt .
    RUN pip install --upgrade pip
    RUN pip install --no-cache-dir -r requirements.txt
    
    # --- Copy project files ---
    COPY . .
    
    # --- Collect static files ---
    RUN python manage.py collectstatic --noinput
    
    # --- Expose port ---
    EXPOSE 8000
    