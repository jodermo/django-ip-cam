# views.py
import os
import cv2
import time
from django.http import StreamingHttpResponse, HttpResponseServerError, JsonResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from dotenv import load_dotenv

load_dotenv()

CAMERA_URL_RAW = os.getenv("CAMERA_URL")
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

RECORD_DIR = os.path.join("media", "recordings")
os.makedirs(RECORD_DIR, exist_ok=True)

CAMERA_URL_RAW = os.getenv("CAMERA_URL")

# Parse as int if it's a digit (e.g., "0"), otherwise keep it as string
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

def gen_frames():
    cap = cv2.VideoCapture(CAMERA_URL)
    if not cap.isOpened():
        print(f"[ERROR] Could not open camera: {CAMERA_URL}")
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
        return HttpResponseServerError(f"Camera error: {e}")


@login_required
def stream_page(request):
    camera_error = None
    try:
        cap = cv2.VideoCapture(CAMERA_URL)
        if not cap.isOpened():
            camera_error = "Cannot open camera"
    except Exception as e:
        camera_error = str(e)
    return render(request, "cameraapp/stream.html", {"camera_error": camera_error})


@login_required
def record_video(request):
    duration = int(request.GET.get("duration", 5))  # seconds

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"clip_{timestamp}.mp4"
    filepath = os.path.join(RECORD_DIR, filename)

    cap = cv2.VideoCapture(CAMERA_URL)
    if not cap.isOpened():
        return JsonResponse({"status": "error", "message": "Cannot open camera"}, status=500)

    # Video settings
    fps = 20.0
    frame_width = int(cap.get(3))
    frame_height = int(cap.get(4))
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filepath, fourcc, fps, (frame_width, frame_height))

    start = time.time()
    while time.time() - start < duration:
        ret, frame = cap.read()
        if not ret:
            break
        out.write(frame)

    cap.release()
    out.release()

    return JsonResponse({"status": "ok", "file": filepath})
