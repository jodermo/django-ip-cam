# views.py
import os
import cv2
import time
import threading
from django.http import StreamingHttpResponse, HttpResponseServerError, JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django import forms
from .models import CameraSettings
from django.apps import apps
from django.db import connection
from django.contrib.auth import logout
import subprocess
from django.views.decorators.csrf import csrf_exempt

from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt



from dotenv import load_dotenv
load_dotenv()

CAMERA_URL_RAW = os.getenv("CAMERA_URL", "0")
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

# Output directories
RECORD_DIR = os.path.join(settings.MEDIA_ROOT, "recordings")
PHOTO_DIR = os.path.join(settings.MEDIA_ROOT, "photos")
os.makedirs(RECORD_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)

# Global camera instance + lock
camera_lock = threading.Lock()
camera_instance = None

active_stream_viewers = 0
last_disconnect_time = None
disconnect_timeout_sec = 10  # Shutdown after 10 seconds of inactivity

recording_thread = None
recording_active = False
recording_lock = threading.Lock()
recording_timeout = 30  # Sekunden Fallback

def logout_view(request):
    logout(request)
    return redirect("login")

def get_camera_settings():
    return CameraSettings.objects.first()

def get_camera_settings_safe():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM cameraapp_camerasettings LIMIT 1")
    except Exception:
        return None

    CameraSettings = apps.get_model("cameraapp", "CameraSettings")
    return CameraSettings.objects.first()


@login_required
@csrf_exempt
def reboot_pi(request):
    if request.method == "POST":
        print("[REBOOT] Executing system reboot...")

        try:
            # Direktes Aufrufen des Skripts (ohne sudo), falls korrekt gemounted
            subprocess.Popen(["/usr/local/bin/reboot-host.sh"])
        except FileNotFoundError as e:
            print(f"[REBOOT ERROR] {e}")
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

        return render(request, "cameraapp/rebooting.html")
    return redirect("settings_view")


def init_camera():
    global camera_instance
    if camera_instance:
        camera_instance.release()
    camera_instance = cv2.VideoCapture(CAMERA_URL)
    print(f"[CAM INIT] Opened camera from .env: {CAMERA_URL}")
    if not camera_instance.isOpened():
        print("[CAM INIT] Failed to open camera.")
        camera_instance = None

def is_camera_open():
    return camera_instance and camera_instance.isOpened()

def read_frame():
    global camera_instance
    with camera_lock:
        if not is_camera_open():
            print("[READ_FRAME] Camera not open, trying to reinitialize...")
            init_camera()
            if not is_camera_open():
                print("[READ_FRAME] Reinitialization failed.")
                return None
        ret, frame = camera_instance.read()
        if not ret:
            print("[READ_FRAME] Failed to read frame.")
        return frame if ret else None



def gen_frames():
    global active_stream_viewers, last_disconnect_time
    print("[GEN_FRAMES] Start streaming loop.")

    with camera_lock:
        active_stream_viewers += 1
        print(f"[STREAM] Viewer connected. Active: {active_stream_viewers}")

    try:
        settings_obj = get_camera_settings()
        overlay = settings_obj.overlay_timestamp if settings_obj else True

        while True:
            frame = read_frame()
            if frame is None:
                print("[GEN_FRAMES] No frame, trying to reinit camera...")
                init_camera()
                time.sleep(1)
                continue

            if overlay:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                cv2.putText(frame, timestamp, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret:
                print("[GEN_FRAMES] Encoding failed.")
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
            )
    finally:
        with camera_lock:
            active_stream_viewers -= 1
            print(f"[STREAM] Viewer disconnected. Active: {active_stream_viewers}")
            if active_stream_viewers <= 0:
                last_disconnect_time = time.time()
                threading.Thread(target=delayed_camera_release).start()


def delayed_camera_release():
    global last_disconnect_time, camera_instance
    time.sleep(disconnect_timeout_sec)
    with camera_lock:
        if active_stream_viewers == 0 and last_disconnect_time and (time.time() - last_disconnect_time >= disconnect_timeout_sec):
            print("[CAMERA] No viewers for a while. Releasing camera.")
            if camera_instance:
                camera_instance.release()
                camera_instance = None  # <--- Wichtig



@login_required
def video_feed(request):
    with camera_lock:
        if not is_camera_open():
            print("[VIDEO_FEED] Camera not open. Trying to initialize...")
            init_camera()
    try:
        return StreamingHttpResponse(
            gen_frames(),
            content_type="multipart/x-mixed-replace; boundary=frame"
        )
    except Exception as e:
        return HttpResponseServerError(f"Camera error: {e}")


@login_required
def stream_page(request):
    print("[STREAM PAGE] Checking camera status...")

    settings_obj = get_camera_settings_safe()

    with camera_lock:
        if not is_camera_open():
            print("[STREAM PAGE] Camera is NOT open, trying to init.")
            init_camera()

    camera_error = None
    if not is_camera_open():
        camera_error = "Cannot open camera"
    elif settings_obj is None:
        camera_error = "Settings not ready (DB table missing?)"

    return render(request, "cameraapp/stream.html", {
        "camera_error": camera_error,
        "title": "Live Stream",
        "viewer_count": active_stream_viewers  # <-- HIER
    })


@login_required
def record_video(request):
    settings_obj = get_camera_settings()
    default_duration = 5
    default_fps = 20.0

    duration = int(request.GET.get("duration", settings_obj.duration_sec if settings_obj else default_duration))
    fps = float(request.GET.get("fps", settings_obj.record_fps if settings_obj and settings_obj.record_fps else default_fps))
    resolution_w = int(request.GET.get("width", settings_obj.resolution_width if settings_obj and settings_obj.resolution_width else 640))
    resolution_h = int(request.GET.get("height", settings_obj.resolution_height if settings_obj and settings_obj.resolution_height else 480))
    codec = request.GET.get("codec", settings_obj.video_codec if settings_obj and settings_obj.video_codec else "mp4v")

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"clip_{timestamp}.mp4"
    filepath = os.path.join(RECORD_DIR, filename)

    with camera_lock:
        if not is_camera_open():
            init_camera()
        if not is_camera_open():
            return JsonResponse({"status": "error", "message": "Cannot open camera"}, status=500)

        fourcc = cv2.VideoWriter_fourcc(*codec)
        out = cv2.VideoWriter(filepath, fourcc, fps, (resolution_w, resolution_h))

        start = time.time()
        while time.time() - start < duration:
            frame = read_frame()
            if frame is None:
                break
            out.write(cv2.resize(frame, (resolution_w, resolution_h)))

        out.release()

    return JsonResponse({"status": "ok", "file": filepath})

@login_required
def photo_gallery(request):
    photos = []
    if os.path.exists(PHOTO_DIR):
        for fname in sorted(os.listdir(PHOTO_DIR)):
            if fname.lower().endswith((".jpg", ".jpeg", ".png")):
                photos.append(f"/media/photos/{fname}")

    settings_obj = get_camera_settings()

    return render(request, "cameraapp/gallery.html", {
        "photos": photos,
        "interval": settings_obj.interval_ms if settings_obj else 3000,
        "duration": settings_obj.duration_sec if settings_obj else 30,
        "autoplay": settings_obj.auto_play if settings_obj else False,
        "overlay": settings_obj.overlay_timestamp if settings_obj else True,
        "title": "Gallery"
    })

class CameraSettingsForm(forms.ModelForm):
    class Meta:
        model = CameraSettings
        fields = "__all__"

@login_required
def settings_view(request):
    settings_obj, _ = CameraSettings.objects.get_or_create(pk=1)

    if request.method == "POST":
        form = CameraSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            return redirect("settings_view")
    else:
        form = CameraSettingsForm(instance=settings_obj)

    return render(request, "cameraapp/settings.html", {
        "form": form,
        "title": "Settings"
    })





@csrf_exempt
@require_POST
@login_required
def start_recording(request):
    global recording_thread, recording_active

    def record_with_timeout():
        nonlocal recording_active
        print("[RECORD] Recording started.")
        start_time = time.time()
        try:
            record_video(request)
        finally:
            with recording_lock:
                recording_active = False
                print("[RECORD] Recording stopped.")
    
    with recording_lock:
        if recording_active:
            return JsonResponse({"status": "already recording"})
        recording_active = True
        recording_thread = threading.Thread(target=record_with_timeout)
        recording_thread.start()

    return JsonResponse({"status": "started"})

@csrf_exempt
@require_POST
@login_required
def stop_recording(request):
    global recording_active
    with recording_lock:
        recording_active = False
    return JsonResponse({"status": "stopped"})
