# views.py
import os
import cv2
import time
import threading
import datetime
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
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from .recording_job import RecordingJob
from .livestream_job import LiveStreamJob

from dotenv import load_dotenv
load_dotenv()

livestream_job = LiveStreamJob(
    camera_source=CAMERA_URL,
    frame_callback=lambda f: update_latest_frame(f)  # zum Teilen mit Recorder
)

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

recording_job = None
recording_thread = None
recording_active = False
recording_lock = threading.Lock()
recording_timeout = 30  # Sekunden Fallback
latest_frame = None  
latest_frame_lock = threading.Lock()

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

def update_latest_frame(frame):
    global latest_frame
    with latest_frame_lock:
        latest_frame = frame.copy()


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
    global active_stream_viewers, last_disconnect_time, latest_frame
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
                cv2.putText(
                    frame, timestamp,
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (255, 255, 255), 2
                )

            # Update latest_frame for recorder
            with latest_frame_lock:
                latest_frame = frame.copy()

            # Encode and stream
            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret:
                print("[GEN_FRAMES] Encoding failed.")
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" +
                buffer.tobytes() +
                b"\r\n"
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
    if not livestream_job.running:
        livestream_job.start()

    def frame_generator():
        while True:
            frame = livestream_job.get_frame()
            if frame is None:
                time.sleep(0.1)
                continue
            _, buffer = cv2.imencode(".jpg", frame)
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" +
                   buffer.tobytes() + b"\r\n")
    return StreamingHttpResponse(frame_generator(),
        content_type="multipart/x-mixed-replace; boundary=frame")



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

def record_video_to_file(filepath, duration, fps, resolution, codec="mp4v"):
    print(f"[RECORD_TO_FILE] Begin recording: {filepath}")
    print(f"[RECORD_TO_FILE] Settings → Duration: {duration}s, FPS: {fps}, Resolution: {resolution}, Codec: {codec}")

    # Prepare the VideoWriter
    fourcc = cv2.VideoWriter_fourcc(*codec)
    out = cv2.VideoWriter(filepath, fourcc, fps, resolution)
    if not out.isOpened():
        print("[RECORD_TO_FILE] Error: Failed to open VideoWriter.")
        return False

    frame_count = 0
    start_time = time.time()

    while time.time() - start_time < duration:
        with latest_frame_lock:
            frame = latest_frame.copy() if latest_frame is not None else None

        if frame is None:
            print(f"[RECORD_TO_FILE] Warning: No frame captured at {frame_count}. Retrying...")
            time.sleep(0.05)
            continue

        try:
            resized = cv2.resize(frame, resolution)
            out.write(resized)
            frame_count += 1

            if frame_count % 10 == 0:
                print(f"[RECORD_TO_FILE] Info: {frame_count} frames written so far...")
        except Exception as e:
            print(f"[RECORD_TO_FILE] Error writing frame {frame_count}: {e}")
            break

    out.release()
    duration_recorded = time.time() - start_time
    print(f"[RECORD_TO_FILE] Recording complete. Total frames: {frame_count}, Time: {duration_recorded:.2f}s")

    return frame_count > 0



@login_required
def record_video(request):
    print("[RECORD_VIDEO] Called via GET")

    settings_obj = get_camera_settings()
    duration = int(request.GET.get("duration", settings_obj.duration_sec if settings_obj else 5))
    fps = float(request.GET.get("fps", settings_obj.record_fps if settings_obj else 20.0))
    resolution = (
        int(request.GET.get("width", settings_obj.resolution_width if settings_obj else 640)),
        int(request.GET.get("height", settings_obj.resolution_height if settings_obj else 480)),
    )
    codec = request.GET.get("codec", settings_obj.video_codec if settings_obj else "mp4v")

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"clip_{timestamp}.mp4"
    filepath = os.path.join(RECORD_DIR, filename)

    print(f"[RECORD_VIDEO] Async start to file: {filepath}")

    def async_record():
        record_video_to_file(filepath, duration, fps, resolution, codec)

    threading.Thread(target=async_record).start()

    return JsonResponse({"status": "recording started", "file": filepath})



@csrf_exempt
@require_POST
@login_required
def start_recording(request):
    global recording_job

    if recording_job and recording_job.active:
        return JsonResponse({"status": "already recording"})

    settings_obj = get_camera_settings()
    duration = recording_timeout
    fps = settings_obj.record_fps if settings_obj else 20.0
    resolution = (
        settings_obj.resolution_width if settings_obj else 640,
        settings_obj.resolution_height if settings_obj else 480,
    )
    codec = settings_obj.video_codec if settings_obj else "mp4v"
    filepath = os.path.join(RECORD_DIR, f"clip_{time.strftime('%Y%m%d-%H%M%S')}.mp4")

    def frame_provider():
        return latest_frame.copy() if latest_frame is not None else None

    job = RecordingJob(
        filepath=filepath,
        duration=duration,
        fps=fps,
        resolution=resolution,
        codec=codec,
        frame_provider=frame_provider,
        lock=latest_frame_lock
    )

    recording_job = job
    job.start()

    return JsonResponse({"status": "started", "file": filepath})




@csrf_exempt
@require_POST
@login_required
def stop_recording(request):
    global recording_job
    if recording_job and recording_job.active:
        recording_job.stop()
        return JsonResponse({"status": "stopping"})
    return JsonResponse({"status": "not active"})


@csrf_exempt
@login_required
def is_recording(request):
    global recording_job
    state = recording_job.active if recording_job else False
    return JsonResponse({"recording": state})


@login_required
def media_browser(request):
    media_tree = []

    def collect_files(base_url, base_path):
        result = []
        if os.path.exists(base_path):
            for fname in sorted(os.listdir(base_path)):
                full_path = os.path.join(base_path, fname)
                url_path = f"{base_url}/{fname}"
                if os.path.isdir(full_path):
                    result.append({
                        "type": "dir",
                        "name": fname,
                        "children": collect_files(url_path, full_path)
                    })
                else:
                    ext = fname.split(".")[-1].lower()
                    file_type = "video" if ext in ["mp4", "avi", "mov"] else "image"
                    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(full_path))
                    result.append({
                        "type": file_type,
                        "name": fname,
                        "url": url_path,
                        "mtime": mtime
                    })
        return result

    media_tree.append({
        "label": "Recordings",
        "path": "/media/recordings",
        "content": collect_files("/media/recordings", RECORD_DIR)
    })

    media_tree.append({
        "label": "Photos",
        "path": "/media/photos",
        "content": collect_files("/media/photos", PHOTO_DIR)
    })

    return render(request, "cameraapp/media_browser.html", {
        "media_tree": media_tree,
        "title": "Media Browser"
    })
