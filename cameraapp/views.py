import os
import cv2
import time
import threading
from django.http import StreamingHttpResponse, HttpResponseServerError, JsonResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from dotenv import load_dotenv
from django.conf import settings

# Load environment variables
load_dotenv()

# Parse CAMERA_URL from env
CAMERA_URL_RAW = os.getenv("CAMERA_URL")
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

# Output directory
RECORD_DIR = os.path.join("media", "recordings")
os.makedirs(RECORD_DIR, exist_ok=True)

# Global camera instance + lock
camera_lock = threading.Lock()
camera_instance = cv2.VideoCapture(CAMERA_URL)

def is_camera_open():
    return camera_instance and camera_instance.isOpened()

def read_frame():
    with camera_lock:
        if not is_camera_open():
            return None
        ret, frame = camera_instance.read()
        return frame if ret else None

def gen_frames():
    while True:
        frame = read_frame()
        if frame is None:
            time.sleep(1)
            continue
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
            gen_frames(),
            content_type="multipart/x-mixed-replace; boundary=frame"
        )
    except Exception as e:
        return HttpResponseServerError(f"Camera error: {e}")

@login_required
def stream_page(request):
    camera_error = None
    if not is_camera_open():
        camera_error = "Cannot open camera"
    return render(request, "cameraapp/stream.html", {"camera_error": camera_error})

@login_required
def record_video(request):
    duration = int(request.GET.get("duration", 5))  # seconds
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"clip_{timestamp}.mp4"
    filepath = os.path.join(RECORD_DIR, filename)

    with camera_lock:
        if not is_camera_open():
            return JsonResponse({"status": "error", "message": "Cannot open camera"}, status=500)

        # Setup video writer
        fps = 20.0
        frame_width = int(camera_instance.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(camera_instance.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(filepath, fourcc, fps, (frame_width, frame_height))

        start = time.time()
        while time.time() - start < duration:
            frame = read_frame()
            if frame is None:
                break
            out.write(frame)

        out.release()

    return JsonResponse({"status": "ok", "file": filepath})


@login_required
def photo_gallery(request):
    photo_dir = os.path.join(settings.MEDIA_ROOT, "photos")
    photos = []

    if os.path.exists(photo_dir):
        for fname in sorted(os.listdir(photo_dir)):
            if fname.lower().endswith((".jpg", ".jpeg", ".png")):
                photos.append(f"/media/photos/{fname}")

    return render(request, "cameraapp/gallery.html", {"photos": photos})
