# default
import os
import cv2
import time
import threading
import datetime
import subprocess
# views.py


# Django
from django.http import (
    StreamingHttpResponse, HttpResponseServerError, JsonResponse,
    HttpResponseRedirect
)
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse
from django.conf import settings
from django import forms
from django.apps import apps
from django.db import connection
from django.contrib.auth import logout

# project
from .models import CameraSettings
from .camera_core import (
    init_camera, camera_instance, reset_to_default, try_open_camera, get_camera_settings, apply_photo_settings,
    apply_auto_settings, auto_adjust_from_frame, apply_cv_settings
)
from .recording_job import RecordingJob


from .scheduler import take_photo 
from .globals import camera_lock, latest_frame, latest_frame_lock

from dotenv import load_dotenv
load_dotenv()


CAMERA_URL_RAW = os.getenv("CAMERA_URL", "0")
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

# Output directories
RECORD_DIR = os.path.join(settings.MEDIA_ROOT, "recordings")
PHOTO_DIR = os.path.join(settings.MEDIA_ROOT, "photos")
os.makedirs(RECORD_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)

# Globals
active_stream_viewers = 0
last_disconnect_time = None
recording_job = None
recording_timeout = 30

livestream_job = None



def get_livestream_job(camera_source, frame_callback=None, shared_capture=None):
    global livestream_job
    from cameraapp.livestream_job import LiveStreamJob
    livestream_job = LiveStreamJob(camera_source, frame_callback, shared_capture)
    return livestream_job


def update_latest_frame(frame):
    global latest_frame
    with latest_frame_lock:
        latest_frame = frame.copy()

livestream_job = get_livestream_job(
    camera_source=CAMERA_URL,
    frame_callback=lambda f: update_latest_frame(f),
    shared_capture=camera_instance
)

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
        try:
            subprocess.Popen(["/usr/local/bin/reboot-host.sh"])
        except FileNotFoundError as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
        return render(request, "cameraapp/rebooting.html")
    return redirect("settings_view")

@csrf_exempt 
def reset_camera_settings(request):
    if request.method == "POST":
        reset_to_default()
        init_camera()
    return redirect("settings_view")

@login_required
def video_feed(request):



    with camera_lock:
        if livestream_job and not livestream_job.running:
            livestream_job.start()

    def stream_generator():
        frame_fail_count = 0
        while True:
            frame = livestream_job.get_frame()
            if frame is None:
                time.sleep(0.1)
                frame_fail_count += 1
                if frame_fail_count > 100:
                    break
                continue

            frame_fail_count = 0
            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret:
                continue
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" +
                   buffer.tobytes() + b"\r\n")
            time.sleep(0.03)

    try:
        return StreamingHttpResponse(stream_generator(),
            content_type="multipart/x-mixed-replace; boundary=frame")
    except Exception as e:
        return HttpResponseServerError("Streaming error")


def apply_video_settings(cap):
    settings = CameraSettings.objects.first()
    if not cap or not cap.isOpened() or not settings:
        return

    cap.set(cv2.CAP_PROP_BRIGHTNESS, settings.video_brightness)
    cap.set(cv2.CAP_PROP_CONTRAST, settings.video_contrast)
    cap.set(cv2.CAP_PROP_SATURATION, settings.video_saturation)
    cap.set(cv2.CAP_PROP_EXPOSURE, settings.video_exposure)
    cap.set(cv2.CAP_PROP_GAIN, settings.video_gain)

    # Optionally log actual values
    print("[VIDEO] Set brightness =", settings.video_brightness, "→ actual =", cap.get(cv2.CAP_PROP_BRIGHTNESS))

@login_required
def stream_page(request):
    global livestream_job

    settings_obj = get_camera_settings_safe()
    camera_error = None

    if request.method == "POST":
        # ... settings speichern ...
        with camera_lock:
            if livestream_job:
                livestream_job.stop()
            time.sleep(1.0)

            if camera_instance and camera_instance.isOpened():
                camera_instance.release()

            init_camera()
            if livestream_job:
                livestream_job.start()

    livestream_job = get_livestream_job(
        camera_source=CAMERA_URL,
        frame_callback=lambda f: update_latest_frame(f),
        shared_capture=camera_instance
    )

    if livestream_job and not livestream_job.running:
        livestream_job.start()

    return render(request, "cameraapp/stream.html", {
        "camera_error": camera_error,
        "title": "Live Stream",
        "viewer_count": active_stream_viewers,
        "settings": settings_obj
    })


@require_GET
@login_required
def record_video(request):
    print("[RECORD_VIDEO] Called via GET")

    settings_obj = get_camera_settings()
    if not settings_obj:
        return JsonResponse({"error": "No camera settings found."}, status=500)

    try:
        duration = int(request.GET.get("duration", settings_obj.duration_sec))
        fps = float(request.GET.get("fps", settings_obj.record_fps))
        width = int(request.GET.get("width", settings_obj.resolution_width))
        height = int(request.GET.get("height", settings_obj.resolution_height))
        codec = request.GET.get("codec", settings_obj.video_codec)

        resolution = (width, height)
        filepath = os.path.join(RECORD_DIR, f"clip_{time.strftime('%Y%m%d-%H%M%S')}.mp4")

        def async_record():
            success = record_video_to_file(filepath, duration, fps, resolution, codec)
            if not success:
                print(f"[RECORD_VIDEO] Recording failed: {filepath}")
            else:
                print(f"[RECORD_VIDEO] Video saved: {filepath}")

        threading.Thread(target=async_record, daemon=True).start()

        return JsonResponse({
            "status": "recording started",
            "file": filepath,
            "duration": duration,
            "fps": fps,
            "resolution": resolution,
            "codec": codec
        })

    except Exception as e:
        print(f"[RECORD_VIDEO] Error: {e}")
        return JsonResponse({"error": str(e)}, status=400)



def reset_camera_view(request):
    reset_to_default()
    init_camera()
    return redirect("settings_page")  # oder wo du zurück willst

def record_video_to_file(filepath, duration, fps, resolution, codec="mp4v"):
    print(f"[RECORD_TO_FILE] Starting recording to {filepath} (duration={duration}s, fps={fps}, resolution={resolution})")

    try:
        fourcc = cv2.VideoWriter_fourcc(*codec)
        out = cv2.VideoWriter(filepath, fourcc, fps, resolution)
        if not out.isOpened():
            print(f"[RECORD_TO_FILE] Error: Cannot open file {filepath} for writing.")
            return False

        frame_count = 0
        start_time = time.time()

        while time.time() - start_time < duration:
            with latest_frame_lock:
                frame = latest_frame.copy() if latest_frame is not None else None

            if frame is None:
                print("[RECORD_TO_FILE] No frame available, retrying...")
                time.sleep(0.05)
                continue

            try:
                resized_frame = cv2.resize(frame.copy(), resolution)
                out.write(resized_frame)
                frame_count += 1
                if frame_count % 10 == 0:
                    print(f"[RECORD_TO_FILE] {frame_count} frames written...")
            except Exception as frame_err:
                print(f"[RECORD_TO_FILE] Frame write failed: {frame_err}")
                break

            time.sleep(1.0 / fps)

    except Exception as e:
        print(f"[RECORD_TO_FILE] Exception during recording: {e}")
        return False

    finally:
        out.release()
        print(f"[RECORD_TO_FILE] Recording complete: {frame_count} frames saved → {filepath}")

    return frame_count > 0



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
        settings_obj.resolution_height if settings_obj else 480
    )
    codec = settings_obj.video_codec if settings_obj else "mp4v"
    filepath = os.path.join(RECORD_DIR, f"clip_{time.strftime('%Y%m%d-%H%M%S')}.mp4")

    def frame_provider():
        with latest_frame_lock:
            return latest_frame.copy() if latest_frame is not None else None

    recording_job = RecordingJob(
        filepath=filepath,
        duration=duration,
        fps=fps,
        resolution=resolution,
        codec=codec,
        frame_provider=frame_provider,
        lock=latest_frame_lock
    )
    recording_job.start()
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
        "settings": settings_obj,  # <-- hinzugefügt
        "title": "Gallery"
    })


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
    return render(request, "cameraapp/settings.html", {"form": form, "title": "Settings"})

class CameraSettingsForm(forms.ModelForm):
    class Meta:
        model = CameraSettings
        fields = '__all__'
        widgets = {
            'video_brightness': forms.NumberInput(attrs={'step': 0.1}),
            'photo_brightness': forms.NumberInput(attrs={'step': 0.1}),
            'video_exposure_mode': forms.Select(),
        }

@login_required
def media_browser(request):
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

    media_tree = [
        {"label": "Recordings", "path": "/media/recordings", "content": collect_files("/media/recordings", RECORD_DIR)},
        {"label": "Photos", "path": "/media/photos", "content": collect_files("/media/photos", PHOTO_DIR)}
    ]
    return render(request, "cameraapp/media_browser.html", {"media_tree": media_tree, "title": "Media Browser"})


@require_POST
@login_required
def update_camera_settings(request):
    global camera_instance
    global livestream_job 

    try:
        settings_obj = get_camera_settings_safe()
        if settings_obj:
            print("[UPDATE_CAMERA_SETTINGS] Request received:", dict(request.POST))

            for param in ["brightness", "contrast", "saturation", "exposure", "gain"]:
                value = request.POST.get(f"video_{param}")
                if value is not None:
                    try:
                        setattr(settings_obj, f"video_{param}", float(value))
                        print(f"[UPDATE_CAMERA_SETTINGS] Set video_{param} = {value}")
                    except ValueError:
                        print(f"[UPDATE_CAMERA_SETTINGS] Invalid value for {param}: {value}")

            exposure_mode = request.POST.get("video_exposure_mode")
            if exposure_mode in ["auto", "manual"]:
                settings_obj.video_exposure_mode = exposure_mode
                print(f"[UPDATE_CAMERA_SETTINGS] Set video_exposure_mode = {exposure_mode}")

            settings_obj.save()
            print("[UPDATE_CAMERA_SETTINGS] Settings saved.")

        else:
            print("[UPDATE_CAMERA_SETTINGS] No CameraSettings object found.")
            return HttpResponseRedirect(reverse("stream_page"))

    except Exception as e:
        print(f"[UPDATE_CAMERA_SETTINGS] Error saving settings: {e}")
        return HttpResponseRedirect(reverse("stream_page"))

    if not livestream_job:
        return

    with camera_lock:
        livestream_job.stop()
        livestream_job.join(timeout=2.0)

        if camera_instance and camera_instance.isOpened():
            camera_instance.release()
            print("[UPDATE_CAMERA_SETTINGS] Released camera.")

        new_cap = try_open_camera(CAMERA_URL)
        if new_cap and new_cap.isOpened():
            camera_instance = new_cap
            apply_cv_settings(camera_instance, settings_obj, mode="video")
            print("[UPDATE_CAMERA_SETTINGS] Camera reconfigured.")
        else:
            print("[UPDATE_CAMERA_SETTINGS] Failed to reopen camera.")

        livestream_job = get_livestream_job(
            camera_source=CAMERA_URL,
            frame_callback=lambda f: update_latest_frame(f),
            shared_capture=camera_instance
        )
        globals()["livestream_job"] = livestream_job
        livestream_job.start()
        print("[UPDATE_CAMERA_SETTINGS] Livestream restarted.")

    return HttpResponseRedirect(reverse("stream_page"))



@require_POST
@login_required
def update_photo_settings(request):
    try:
        settings_obj = get_camera_settings_safe()
        if not settings_obj:
            print("[UPDATE_PHOTO_SETTINGS] No CameraSettings object found.")
            return HttpResponseRedirect(reverse("photo_settings_page"))

        for param in ["brightness", "contrast", "saturation", "exposure", "gain"]:
            value = request.POST.get(f"photo_{param}")
            if value is not None:
                try:
                    setattr(settings_obj, f"photo_{param}", float(value))
                except ValueError:
                    print(f"[UPDATE_PHOTO_SETTINGS] Invalid value for {param}: {value}")
                    continue

        exposure_mode = request.POST.get("photo_exposure_mode")
        if exposure_mode in ["auto", "manual"]:
            settings_obj.photo_exposure_mode = exposure_mode

        settings_obj.save()
        print("[UPDATE_PHOTO_SETTINGS] Photo settings saved.")

    except Exception as e:
        print(f"[UPDATE_PHOTO_SETTINGS] Error while saving photo settings: {e}")

    return HttpResponseRedirect(reverse("photo_settings_page"))



def pause_livestream():
    if livestream_job.running:
        livestream_job.stop()
        print("[PHOTO] Livestream was paused for photo capture.")
        time.sleep(0.5)


def resume_livestream():
    print("[PHOTO] Waiting for camera release...")
    time.sleep(1.5)

    if not livestream_job.running:
        for attempt in range(3):
            livestream_job.start()
            time.sleep(1.0)
            if livestream_job.running and livestream_job.get_frame() is not None:
                print("[PHOTO] Livestream restarted successfully.")
                return
            print(f"[PHOTO] Livestream restart failed (attempt {attempt + 1})")
            livestream_job.stop()
            time.sleep(1.5)

        print("[PHOTO] Livestream could not be restarted.")



@require_POST
@login_required
def take_photo_now(request):
    with camera_lock:
        pause_livestream()
        try:
            success = take_photo()
            if not success:
                return JsonResponse({"status": "Camera could not be opened."}, status=500)
        finally:
            resume_livestream()
    return JsonResponse({"status": "ok"})


@require_POST
@login_required
def auto_photo_settings(request):
    settings = CameraSettings.objects.first()
    if not settings:
        return JsonResponse({"success": False, "message": "No camera settings found."})

    apply_auto_settings(settings)
    return JsonResponse({"success": True, "message": "Auto settings applied."})


@require_POST
@login_required
def auto_photo_adjust(request):
    settings = get_camera_settings()

    if not settings:
        return JsonResponse({"status": "no settings found"}, status=500)

    with latest_frame_lock:
        frame = latest_frame.copy() if latest_frame is not None else None

    if frame is not None:
        auto_adjust_from_frame(frame, settings)
        return JsonResponse({"status": "adjusted from live frame"})

    # Fallback: temporäres Foto machen
    print("[AUTO-ADJUST] No live frame, capturing temp image.")
    cap = cv2.VideoCapture(CAMERA_URL)
    if not cap.isOpened():
        return JsonResponse({"status": "camera not available"}, status=500)

    # Wende vorab aktuelle Video-Settings an
    apply_cv_settings(cap, settings, mode="video")
    time.sleep(0.3)  # kleine Pause für Stabilisierung

    ret, temp_frame = cap.read()
    cap.release()

    if not ret or temp_frame is None:
        return JsonResponse({"status": "could not capture frame"}, status=500)

    auto_adjust_from_frame(temp_frame, settings)
    return JsonResponse({"status": "adjusted from temp photo"})

@login_required
def photo_settings_page(request):
    settings_obj = get_camera_settings()
    return render(request, "cameraapp/photo_settings.html", {
        "settings": settings_obj,
        "title": "Foto-Einstellungen"
    })