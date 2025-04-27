# cameraapp/views.py

import os
from cameraapp.recording_job import RecordingJob
import cv2
import time
import threading
import datetime
import subprocess

from django.http import (
    HttpResponse, StreamingHttpResponse, HttpResponseServerError, JsonResponse,
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


from .models import CameraSettings
from .camera_core import (
    init_camera, reset_to_default,
    apply_auto_settings, auto_adjust_from_frame,
    apply_cv_settings, get_camera_settings, get_camera_settings_safe,
    release_and_reset_camera
)
from .camera_utils import safe_restart_camera_stream, update_latest_frame
from . import globals as app_globals
from .scheduler import take_photo 


from dotenv import load_dotenv
load_dotenv()


CAMERA_URL_RAW = os.getenv("CAMERA_URL", "0")
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

# Output directories
RECORD_DIR = os.path.join(settings.MEDIA_ROOT, "recordings")
PHOTO_DIR = os.path.join(settings.MEDIA_ROOT, "photos")
os.makedirs(RECORD_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)



def logout_view(request):
    logout(request)
    return redirect("login")


def get_camera_settings():
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


@require_GET
@login_required
def camera_status(request):
    return JsonResponse({"camera_url": str(CAMERA_URL)})



def generate_frames():
    """
    Generator-Funktion, die kontinuierlich JPEG-kodierte Frames aus dem Livestream liefert.
    """
    global app_globals
    frame_fail_count = 0

    while True:
        if not app_globals.livestream_job or not app_globals.livestream_job.running:
            print("[STREAM] Livestream job not running, exiting generator.")
            break

        with app_globals.latest_frame_lock:
            frame = app_globals.latest_frame.copy() if app_globals.latest_frame is not None else None

            if frame is None:
                time.sleep(0.1)
                frame_fail_count += 1
                if frame_fail_count > 100:
                    print("[STREAM] No frames available after multiple attempts, aborting stream.")
                    break
                continue

            frame_fail_count = 0
            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret:
                print("[STREAM] Frame encoding failed.")
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" +
                buffer.tobytes() +
                b"\r\n"
            )
            time.sleep(0.03)



@login_required
def video_feed(request):
    global app_globals
    with app_globals.latest_frame_lock:
        if app_globals.latest_frame is None:
            print("[VIDEO_FEED] No frame available (latest_frame is None). Returning 503.")
            return HttpResponse("No frame", status=503)
    print("[VIDEO_FEED] Frame available. Starting streaming response.")
    return StreamingHttpResponse(
        generate_frames(),
        content_type="multipart/x-mixed-replace; boundary=frame"
    )


@login_required
def stream_page(request):
    global app_globals

    settings_obj = get_camera_settings_safe(connection)
    camera_error = None

    if not app_globals.camera or not app_globals.camera.is_available():
        print("[STREAM_PAGE] Camera is not available, initializing...")
        init_camera()

    if not app_globals.livestream_job or not app_globals.livestream_job.running:
        print("[STREAM_PAGE] Livestream not active, starting...")
        with app_globals.livestream_resume_lock:
            app_globals.livestream_job = safe_restart_camera_stream(
                frame_callback=update_latest_frame,
                camera_source=CAMERA_URL
            )
            if app_globals.livestream_job:
                globals()["livestream_job"] = app_globals.livestream_job
                print("[STREAM_PAGE] Livestream started successfully.")
            else:
                print("[STREAM_PAGE] Failed to start livestream.")
                camera_error = "Kamera konnte nicht gestartet werden."

    # Warte auf ersten Frame
    start_time = time.time()
    while time.time() - start_time < 5:
        if app_globals.livestream_job and app_globals.livestream_job.running:
            frame = app_globals.livestream_job.get_frame()
            if frame is not None:
                update_latest_frame(frame)
                print("[STREAM_PAGE] First frame received.")
                break
        time.sleep(0.2)
    else:
        print("[STREAM_PAGE] Timeout waiting for first frame.")
        camera_error = "Kein Bildsignal von Kamera erhalten."

    return render(request, "cameraapp/stream.html", {
        "camera_error": camera_error,
        "title": "Live Stream",
        "viewer_count": app_globals.active_stream_viewers,
        "settings": settings_obj
    })


@require_GET
@login_required
def record_video(request):
    print("[RECORD_VIDEO] Called via GET")
    global app_globals
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
    time.sleep(0.5)
    return redirect("settings_page")  # oder wo du zurück willst


def record_video_to_file(filepath, duration, fps, resolution, codec="mp4v"):
    print(f"[RECORD_TO_FILE] Start recording to {filepath} (duration={duration}s, fps={fps}, resolution={resolution})")
    global app_globals
    try:
        fourcc = cv2.VideoWriter_fourcc(*codec)
        out = cv2.VideoWriter(filepath, fourcc, fps, resolution)
        if not out.isOpened():
            print(f"[RECORD_TO_FILE] Error: Cannot open file {filepath}")
            return False

        frame_count = 0
        start_time = time.time()

        while time.time() - start_time < duration:
            with app_globals.latest_frame_lock:
                frame = app_globals.latest_frame.copy() if app_globals.latest_frame is not None else None

            if frame is None:
                time.sleep(0.05)
                continue

            resized_frame = cv2.resize(frame, resolution)
            out.write(resized_frame)
            frame_count += 1

            time.sleep(1.0 / fps)  # respect target fps

    except Exception as e:
        print(f"[RECORD_TO_FILE] Exception during recording: {e}")
        return False

    finally:
        out.release()
        print(f"[RECORD_TO_FILE] Recording finished: {frame_count} frames saved → {filepath}")

    return frame_count > 0




@csrf_exempt
@require_POST
@login_required
def start_recording(request):
    global app_globals
    if app_globals.recording_job and app_globals.recording_job.active:
        return JsonResponse({"status": "already recording"})

    settings_obj = get_camera_settings()
    duration = app_globals.recording_timeout
    fps = settings_obj.record_fps if settings_obj else 20.0
    resolution = (
        settings_obj.resolution_width if settings_obj else 640,
        settings_obj.resolution_height if settings_obj else 480
    )
    codec = settings_obj.video_codec if settings_obj else "mp4v"
    filepath = os.path.join(RECORD_DIR, f"clip_{time.strftime('%Y%m%d-%H%M%S')}.mp4")

    def frame_provider():
        with app_globals.latest_frame_lock:
            return app_globals.latest_frame.copy() if app_globals.latest_frame is not None else None

    app_globals.recording_job = RecordingJob(
        filepath=filepath,
        duration=duration,
        fps=fps,
        resolution=resolution,
        codec=codec,
        frame_provider=frame_provider,
        lock=app_globals.latest_frame_lock
    )
    app_globals.recording_job.start()
    return JsonResponse({"status": "started", "file": filepath})

@csrf_exempt
@require_POST
@login_required
def stop_recording(request):
    global app_globals
    if app_globals.recording_job and app_globals.recording_job.active:
        app_globals.recording_job.stop()
        return JsonResponse({"status": "stopping"})
    return JsonResponse({"status": "not active"})



@csrf_exempt
@login_required
def is_recording(request):
    global app_globals
    state = app_globals.recording_job.active if app_globals.recording_job else False
    return JsonResponse({"recording": state})


@login_required
def photo_gallery(request):
    photos = []
    if os.path.exists(PHOTO_DIR):
        for fname in sorted(os.listdir(PHOTO_DIR)):
            if fname.lower().endswith((".jpg", ".jpeg", ".png")):
                photos.append(f"/media/photos/{fname}")
    settings_obj = get_camera_settings_safe(connection) 
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


@csrf_exempt
@require_POST
@login_required
def reset_camera_settings(request):
    global app_globals

    try:
        settings_obj = get_camera_settings_safe(connection)
        if not settings_obj:
            print("[RESET_CAMERA_SETTINGS] Kein CameraSettings-Objekt gefunden.")
            return HttpResponseRedirect(reverse("settings_view"))

        print("[RESET_CAMERA_SETTINGS] Zurücksetzen auf Default-Werte...")

        settings_obj.video_brightness = 128.0
        settings_obj.video_contrast = 32.0
        settings_obj.video_saturation = 64.0
        settings_obj.video_exposure = -6.0
        settings_obj.video_gain = 4.0
        settings_obj.video_exposure_mode = "auto"
        settings_obj.save()

        print("[RESET_CAMERA_SETTINGS] Defaults gespeichert.")

    except Exception as e:
        print(f"[RESET_CAMERA_SETTINGS] Fehler beim Zurücksetzen: {e}")
        return HttpResponseRedirect(reverse("settings_view"))

    if not app_globals.livestream_job:
        print("[RESET_CAMERA_SETTINGS] Kein aktiver Livestream-Job.")
        return HttpResponseRedirect(reverse("settings_view"))

    with app_globals.camera_lock:
        try:
            app_globals.livestream_job.stop()
            app_globals.livestream_job.join(timeout=2.0)
            print("[RESET_CAMERA_SETTINGS] Livestream gestoppt.")

            release_and_reset_camera()
            print("[RESET_CAMERA_SETTINGS] Kamera freigegeben.")

            app_globals.livestream_job = safe_restart_camera_stream(
                camera_source=CAMERA_URL,
                frame_callback=lambda f: update_latest_frame(f)
            )

            if app_globals.livestream_job:
                globals()["livestream_job"] = app_globals.livestream_job
                print("[RESET_CAMERA_SETTINGS] Kamera erfolgreich neu gestartet.")
            else:
                print("[RESET_CAMERA_SETTINGS] Neustart fehlgeschlagen.")

        except Exception as e:
            print(f"[RESET_CAMERA_SETTINGS] Fehler beim Neustart: {e}")

    return HttpResponseRedirect(reverse("settings_view"))

@csrf_exempt
@require_POST
@login_required
def update_camera_settings(request):
    global app_globals

    try:
        settings_obj = get_camera_settings_safe(connection)
        if not settings_obj:
            print("[UPDATE_CAMERA_SETTINGS] No CameraSettings object found.")
            return HttpResponseRedirect(reverse("stream_page"))

        print("[UPDATE_CAMERA_SETTINGS] Request received:", dict(request.POST))

        for param in ["brightness", "contrast", "saturation", "exposure", "gain"]:
            value = request.POST.get(f"video_{param}")
            if value is not None:
                try:
                    float_value = float(value)
                    setattr(settings_obj, f"video_{param}", float_value)
                    print(f"[UPDATE_CAMERA_SETTINGS] Set video_{param} = {float_value}")
                except ValueError:
                    print(f"[UPDATE_CAMERA_SETTINGS] Invalid value for {param}: {value}")

        exposure_mode = request.POST.get("video_exposure_mode")
        if exposure_mode in ["auto", "manual"]:
            settings_obj.video_exposure_mode = exposure_mode
            print(f"[UPDATE_CAMERA_SETTINGS] Set video_exposure_mode = {exposure_mode}")

            if exposure_mode == "auto":
                settings_obj.video_exposure = -1.0
                print("[UPDATE_CAMERA_SETTINGS] Reset video_exposure to -1.0 due to auto mode")

        settings_obj.save()
        print("[UPDATE_CAMERA_SETTINGS] Settings saved.")

    except Exception as e:
        print(f"[UPDATE_CAMERA_SETTINGS] Error during settings update: {e}")
        return HttpResponseRedirect(reverse("stream_page"))

    if not app_globals.livestream_job:
        print("[UPDATE_CAMERA_SETTINGS] No livestream_job active.")
        return HttpResponseRedirect(reverse("stream_page"))

    with app_globals.camera_lock:
        try:
            app_globals.livestream_job.stop()
            app_globals.livestream_job.join(timeout=2.0)
            print("[UPDATE_CAMERA_SETTINGS] Livestream stopped.")

            release_and_reset_camera()
            print("[RELEASE] Camera released.")

            print("[DEBUG] Calling safe_restart_camera_stream...")
            app_globals.livestream_job = safe_restart_camera_stream(
                frame_callback=lambda f: update_latest_frame(f),
                camera_source=CAMERA_URL
            )
            print(f"[DEBUG] Result from restart: {app_globals.livestream_job}")

            if app_globals.livestream_job:
                globals()["livestream_job"] = app_globals.livestream_job
                print("[UPDATE_CAMERA_SETTINGS] Livestream restarted.")
            else:
                print("[UPDATE_CAMERA_SETTINGS] Restart failed — camera unavailable.")

        except Exception as e:
            print(f"[UPDATE_CAMERA_SETTINGS] Error restarting livestream: {e}")

    return HttpResponseRedirect(reverse("stream_page"))


@csrf_exempt
@require_POST
@login_required
def update_photo_settings(request):
    try:
        settings_obj = get_camera_settings_safe(connection)
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
    global app_globals
    with app_globals.livestream_resume_lock:
        if app_globals.livestream_job and app_globals.livestream_job.running:
            app_globals.livestream_job.stop()
            print("[PHOTO] Livestream was paused for photo capture.")
            time.sleep(0.5)


def resume_livestream():
    global app_globals
    with app_globals.livestream_resume_lock:
        if app_globals.livestream_job and app_globals.livestream_job.running:
            return
        print("[PHOTO] Waiting for camera release...")
        time.sleep(1.5)

        for attempt in range(3):
            with app_globals.livestream_resume_lock:
                if not app_globals.livestream_job.running:
                    app_globals.livestream_job.start()
            time.sleep(1.0)
            if app_globals.livestream_job and app_globals.livestream_job.running and app_globals.livestream_job.get_frame() is not None:
                print("[PHOTO] Livestream restarted successfully.")
                return
            print(f"[PHOTO] Livestream restart failed (attempt {attempt + 1})")
            app_globals.livestream_job.stop()
            time.sleep(1.5)

        print("[PHOTO] Livestream could not be restarted.")


@csrf_exempt
@require_POST
@login_required
def take_photo_now(request):
    global app_globals
    with app_globals.camera_lock:
        pause_livestream()
        try:
            photo_path = take_photo()
            if not photo_path or not os.path.exists(photo_path):
                return JsonResponse({"status": "Camera could not be opened."}, status=500)
            return JsonResponse({"status": "ok", "file": photo_path})

        finally:
            resume_livestream()
    return JsonResponse({"status": "ok"})

@csrf_exempt
@require_POST
@login_required
def auto_photo_settings(request):
    settings = CameraSettings.objects.first()
    if not settings:
        return JsonResponse({"success": False, "message": "No camera settings found."})

    apply_auto_settings(settings)
    return JsonResponse({"success": True, "message": "Auto settings applied."})

@csrf_exempt
@require_POST
@login_required
def auto_photo_adjust(request):
    global app_globals
    settings = get_camera_settings()

    if not settings:
        return JsonResponse({"status": "no settings found"}, status=500)

    with app_globals.latest_frame_lock:
        frame = app_globals.latest_frame.copy() if app_globals.latest_frame is not None else None

    if frame is not None:
        auto_adjust_from_frame(frame, settings)
        return JsonResponse({"status": "adjusted from live frame"})

    print("[AUTO-ADJUST] No live frame, capturing temp image.")
    if not app_globals.camera or not app_globals.camera.cap or not app_globals.camera.cap.isOpened():
        return JsonResponse({"status": "camera not available"}, status=500)

    apply_cv_settings(app_globals.camera, settings, mode="video")
    ret, temp_frame = app_globals.camera.cap.read()
    time.sleep(0.3)

    if not ret or temp_frame is None:
        return JsonResponse({"status": "could not capture frame"}, status=500)

    auto_adjust_from_frame(temp_frame, settings)
    return JsonResponse({"status": "adjusted from temp photo"})


@csrf_exempt
@login_required
def photo_settings_page(request):
    settings_obj = get_camera_settings()
    return render(request, "cameraapp/photo_settings.html", {
        "settings": settings_obj,
        "title": "Foto-Einstellungen"
    })

@csrf_exempt
@login_required
@require_POST
def manual_restart_camera(request):
    global app_globals

    app_globals.livestream_job = safe_restart_camera_stream(
        frame_callback=lambda f: update_latest_frame(f),
        camera_source=CAMERA_URL
    )

    globals()["livestream_job"] = app_globals.livestream_job
    return redirect("stream_page")


def wait_until_camera_available(device_index=0, max_attempts=5, delay=1.0):
    global app_globals
    for attempt in range(max_attempts):
        if app_globals.camera and app_globals.camera.is_available():
            print(f"[CAMERA_UTIL] CameraManager reports device available.")
            return True
        print(f"[CAMERA_UTIL] Waiting for camera... attempt {attempt+1}/{max_attempts}")
        time.sleep(delay)
    print(f"[CAMERA_UTIL] Camera not available after {max_attempts} attempts.")
    return False


