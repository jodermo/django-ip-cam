import os
import cv2
from django.http import StreamingHttpResponse, HttpResponseServerError
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from dotenv import load_dotenv

# Load .env variables
load_dotenv()

# Kamera-URL aus .env
CAMERA_URL = os.getenv("CAMERA_URL")

# MJPEG-Stream Generator
def gen_frames():
    cap = cv2.VideoCapture(CAMERA_URL)
    if not cap.isOpened():
        raise RuntimeError("Cannot open IP camera stream")

    while True:
        success, frame = cap.read()
        if not success:
            break
        ret, buffer = cv2.imencode(".jpg", frame)
        if not ret:
            continue
        frame_bytes = buffer.tobytes()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )

# MJPEG-Stream-Response (geschützt)
@login_required
def video_feed(request):
    try:
        return StreamingHttpResponse(
            gen_frames(), content_type="multipart/x-mixed-replace; boundary=frame"
        )
    except Exception as e:
        return HttpResponseServerError(f"Stream error: {e}")

# Seite mit eingebettetem Stream (geschützt)
@login_required
def stream_page(request):
    return render(request, "cameraapp/stream.html")
