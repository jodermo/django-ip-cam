# Use the official opencv-python image
FROM opencv-python:latest

# Install any additional dependencies
RUN apt-get update && apt-get install -y \
    v4l-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy the camera stream script to the container
COPY camera_stream_script.py /app/

# Set the working directory
WORKDIR /app

# Command to run the camera stream script
CMD ["python", "camera_stream_script.py"]
