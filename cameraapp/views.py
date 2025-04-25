# views.py
import os
import cv2
from django.http import StreamingHttpResponse, HttpResponseServerError
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from dotenv import load_dotenv

load_dotenv()

CAMERA_URL_RAW = os.getenv("CAMERA_URL")

# Parse as int if it's a digit (e.g., "0"), otherwise keep it as string
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

def gen_frames():
    cap = cv2.VideoCapture(CAMERA_URL)
    if not cap.isOpened():
        raise RuntimeError("Cannot open camera")

    while True:
        success, frame = cap.read()
        if not success:
            break
        ret, buffer = cv2.imencode(".jpg", frame)
        if not ret:
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
        )

@login_required
def video_feed(request):
    try:
        return StreamingHttpResponse(
            gen_frames(), content_type="multipart/x-mixed-replace; boundary=frame"
        )
    except Exception as e:
        return HttpResponseServerError(f"Stream error: {e}")

@login_required
def stream_page(request):
    return render(request, "cameraapp/stream.html")
