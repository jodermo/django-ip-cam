# cameraapp/views.py

import os
from cameraapp.recording_job import RecordingJob
import cv2
import time
import threading
import datetime
import subprocess
import glob

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
from django.contrib import messages


from .models import CameraSettings
from .camera_core import (
    init_camera, reset_to_default,
    apply_auto_settings, auto_adjust_from_frame,
    apply_cv_settings, get_camera_settings, get_camera_settings_safe,
    release_and_reset_camera
)
from .camera_utils import safe_restart_camera_stream, update_latest_frame
from .globals import app_globals
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
    global app_globals
    while True:
        frame = app_globals.camera.get_latest_frame()
        if frame is None:
            time.sleep(0.05)
            continue

        ret, buffer = cv2.imencode(".jpg", frame)
        if not ret:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
        )
        time.sleep(0.05)



@csrf_exempt
def video_feed(request):
    global app_globals

    def frame_generator():
        while True:
            frame = app_globals.camera.get_latest_frame()
            if frame is not None:
                ret, jpeg = cv2.imencode('.jpg', frame)
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
            time.sleep(0.04)  # 25 FPS max

    return StreamingHttpResponse(
        frame_generator(),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )


@login_required
def stream_page(request):
    global app_globals

    settings_obj = get_camera_settings_safe(connection)
    camera_error = None

    # ========== [1] ALTE STREAMS STOPPEN ==========
    if app_globals.livestream_job and app_globals.livestream_job.running:
        print("[STREAM_PAGE] Existing livestream found → stopping it.")
        try:
            app_globals.livestream_job.stop()
            app_globals.livestream_job.join(timeout=2.0)
        except Exception as e:
            print(f"[STREAM_PAGE] Error stopping previous stream: {e}")
        app_globals.livestream_job = None

    # ========== [2] KAMERA NEU INITIALISIEREN ==========
    try:
        release_and_reset_camera()
        print("[STREAM_PAGE] Camera initialized successfully.")
    except Exception as e:
        print(f"[STREAM_PAGE] Failed to initialize camera: {e}")
        camera_error = "Kamera konnte nicht initialisiert werden."
        return render(request, "cameraapp/video_view.html", {
            "camera_error": camera_error,
            "title": "Live Stream",
            "viewer_count": app_globals.active_stream_viewers,
            "settings": settings_obj
        })

    # ========== [3] NEUEN LIVESTREAM STARTEN ==========
    try:
        with app_globals.livestream_resume_lock:
            app_globals.livestream_job = safe_restart_camera_stream(
                frame_callback=update_latest_frame,
                camera_source=CAMERA_URL
            )
            if not app_globals.livestream_job:
                raise RuntimeError("Livestream konnte nicht gestartet werden.")
            print("[STREAM_PAGE] Livestream started successfully.")
    except Exception as e:
        print(f"[STREAM_PAGE] Livestream konnte nicht gestartet werden: {e}")
        camera_error = "Kamera konnte nicht gestartet werden."
        return render(request, "cameraapp/video_view.html", {
            "camera_error": camera_error,
            "title": "Live Stream",
            "viewer_count": app_globals.active_stream_viewers,
            "settings": settings_obj
        })

    # ========== [4] AUF ERSTEN FRAME WARTEN ==========
    start_time = time.time()
    first_frame_received = False

    while time.time() - start_time < 5:
        if app_globals.livestream_job and app_globals.livestream_job.running:
            frame = app_globals.livestream_job.get_frame()
            if frame is not None:
                update_latest_frame(frame)
                print("[STREAM_PAGE] First frame received from stream.")
                first_frame_received = True
                break
        time.sleep(0.2)

    if not first_frame_received:
        print("[STREAM_PAGE] Timeout: Kein Frame empfangen.")
        camera_error = "Kein Bildsignal von Kamera erhalten."

    return render(request, "cameraapp/video_view.html", {
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
        return app_globals.camera.get_latest_frame() if app_globals.camera else None

    app_globals.recording_job = RecordingJob(
        filepath=filepath,
        duration=duration,
        fps=fps,
        resolution=resolution,
        codec=codec,
        frame_provider=frame_provider
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
def photo_view(request):
    photo_dir = os.path.join(settings.MEDIA_ROOT, "photos")
    manual_photos = []

    if os.path.exists(photo_dir):
        for fname in sorted(os.listdir(photo_dir)):
            full_path = os.path.join(photo_dir, fname)

            # skip 'timelapse/' folder and nested files
            if os.path.isdir(full_path) and fname == "timelapse":
                continue

            if os.path.isfile(full_path) and fname.lower().endswith((".jpg", ".jpeg", ".png")):
                manual_photos.append(f"/media/photos/{fname}")

    settings_obj = get_camera_settings_safe()

    return render(request, "cameraapp/photo_view.html", {
        "photos": manual_photos,
        "interval": settings_obj.interval_ms if settings_obj else 3000,
        "duration": settings_obj.duration_sec if settings_obj else 30,
        "autoplay": settings_obj.auto_play if settings_obj else False,
        "overlay": settings_obj.overlay_timestamp if settings_obj else True,
        "settings": settings_obj,
        "title": "Photos"
    })

@login_required
def timelaps_view(request):
    timelapse_dir = os.path.join(settings.MEDIA_ROOT, "photos", "timelapse")
    photos = []

    if os.path.exists(timelapse_dir):
        for fname in sorted(os.listdir(timelapse_dir)):
            if fname.lower().endswith((".jpg", ".jpeg", ".png")):
                photos.append(f"/media/photos/timelapse/{fname}")

    settings_obj = get_camera_settings_safe()
    
    return render(request, "cameraapp/timelaps_view.html", {
        "photos": photos,
        "interval": settings_obj.interval_ms if settings_obj else 3000,
        "duration": settings_obj.duration_sec if settings_obj else 30,
        "autoplay": settings_obj.auto_play if settings_obj else False,
        "overlay": settings_obj.overlay_timestamp if settings_obj else True,
        "settings": settings_obj,
        "title": "Timelapse"
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
    layout_mode = request.GET.get("view", "list")  # default = list

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
                    size = os.path.getsize(full_path)
                    result.append({
                        "type": file_type,
                        "name": fname,
                        "url": url_path,
                        "mtime": mtime,
                        "size": size,
                        "path": full_path,
                    })
        return result

    media_tree = [
        {"label": "Recordings", "path": "/media/recordings", "content": collect_files("/media/recordings", RECORD_DIR)},
        {"label": "Photos", "path": "/media/photos", "content": collect_files("/media/photos", PHOTO_DIR)},
        {"label": "Timelapse", "path": "/media/photos/timelapse", "content": collect_files("/media/photos/timelapse", os.path.join(PHOTO_DIR, "timelapse"))}
    ]

    return render(request, "cameraapp/media_browser.html", {
        "media_tree": media_tree,
        "layout_mode": layout_mode,
        "title": "Media Browser"
    })


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
            init_camera() 
            print("[DEBUG] Calling safe_restart_camera_stream...")
            app_globals.livestream_job = safe_restart_camera_stream(
                frame_callback=lambda f: update_latest_frame(f),
                camera_source=CAMERA_URL
            )
            print(f"[DEBUG] Result from restart: {app_globals.livestream_job}")

            if app_globals.livestream_job:
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
            return HttpResponseRedirect(reverse("photo_view"))

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

    return HttpResponseRedirect(reverse("photo_view"))



def pause_livestream():
    print("[PHOTO] pause_livestream")
    global app_globals
    with app_globals.livestream_resume_lock:
        if app_globals.livestream_job and app_globals.livestream_job.running:
            app_globals.livestream_job.stop()
            print("[PHOTO] Livestream was paused for photo capture.")
            time.sleep(0.5)

def resume_livestream():
    print("[PHOTO] resume_livestream")
    global app_globals

    if not app_globals.livestream_resume_lock.acquire(timeout=5):
        print("[PHOTO] Timeout acquiring livestream_resume_lock – skipping resume.")
        return

    try:
        print("[PHOTO] Attempting to resume livestream...")

        if app_globals.livestream_job:
            app_globals.livestream_job.stop()
            app_globals.livestream_job.join(timeout=2.0)

        # Kamera bei Bedarf reinitialisieren
        if not app_globals.camera or not app_globals.camera.is_available():
            print("[PHOTO] Reinitializing CameraManager...")
            try:
                init_camera()
            except Exception as e:
                print(f"[PHOTO] Failed to reinitialize CameraManager: {e}")
                return

        # === Warten, bis cap wirklich offen ist ===

        for attempt in range(15):  # statt 6 Versuche
            if app_globals.camera and app_globals.camera.cap and app_globals.camera.cap.isOpened():
                break
            print(f"[PHOTO] Waiting for camera reopen... attempt {attempt + 1}/15")
            time.sleep(1.0)
        else:
            print("[PHOTO] Camera still not available. Aborting resume.")
            return

        print("[PHOTO] Forcing camera reset and re-init...")
        release_and_reset_camera()
        init_camera()

        # Livestream starten
        app_globals.livestream_job = safe_restart_camera_stream(
            frame_callback=update_latest_frame,
            camera_source=CAMERA_URL
        )

        if app_globals.livestream_job and app_globals.livestream_job.running:
            print("[PHOTO] Livestream restarted successfully.")
        else:
            print("[PHOTO] Failed to restart livestream.")

    finally:
        app_globals.livestream_resume_lock.release()

    if not app_globals.camera or not app_globals.camera.cap.isOpened():
        print("Camera is not open after resume attempt. Forcing full reset.")
        release_and_reset_camera() 
        wait_until_camera_available(timeout=5)



@csrf_exempt
def single_frame(request):
    from django.http import HttpResponse
    from .globals import app_globals
    import cv2
    if not app_globals.camera:
        init_camera()

    with app_globals.latest_frame_lock:
        frame = app_globals.latest_frame.copy() if app_globals.latest_frame is not None else None

    if frame is None:
        return HttpResponse(status=204)

    ret, buffer = cv2.imencode(".jpg", frame)
    if not ret:
        return HttpResponse(status=500)

    return HttpResponse(buffer.tobytes(), content_type="image/jpeg")


def resume_livestream_safe():
    
    try:
        print("[PHOTO] resume_livestream_safe: Thread started")
        resume_livestream()
        print("[PHOTO] resume_livestream_safe: Stream resumed successfully")
    except Exception as e:
        print(f"[PHOTO] resume_livestream_safe: ERROR: {e}")
        # Optional: hier Fehlerstatus in globalem Flag setzen, z. B. für Anzeige im UI
        # app_globals.last_resume_error = str(e)


@csrf_exempt
@require_POST
@login_required
def take_photo_now(request):
    global app_globals
    photo_path = None

    print("[PHOTO] take_photo_now")

    try:
        pause_livestream()

        # === [1] Warten, bis Kamera bereit ist ===
        for attempt in range(6):
            if app_globals.camera and app_globals.camera.cap and app_globals.camera.cap.isOpened():
                print(f"[PHOTO] Camera ready on attempt {attempt + 1}")
                break
            print(f"[PHOTO] Waiting for camera... attempt {attempt + 1}/6")
            time.sleep(1.0)
        else:
            print("[PHOTO] Camera not ready after retries.")
            return JsonResponse({"status": "camera not ready after retries"}, status=500)

        # === [2] Foto machen (take_photo hat eigenen Lock) ===
        photo_path = take_photo(mode="manual")

        if not photo_path:
            print("[PHOTO] take_photo() returned None")
            return JsonResponse({"status": "photo capture failed"}, status=500)

        if not os.path.exists(photo_path):
            print(f"[PHOTO] File not found after capture: {photo_path}")
            return JsonResponse({"status": "photo file missing"}, status=500)

        print(f"[PHOTO] Photo taken and saved: {photo_path}")
        return JsonResponse({"status": "ok", "file": photo_path})

    except Exception as e:
        print(f"[PHOTO] EXCEPTION during take_photo_now: {e}")
        return JsonResponse({"status": "internal error", "error": str(e)}, status=500)

    finally:
        print("[PHOTO] Spawning resume_livestream thread")
        threading.Thread(target=resume_livestream_safe, daemon=True).start()


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
    max_attempts = 5
    for attempt in range(max_attempts):
        if app_globals.camera and app_globals.camera.cap and app_globals.camera.cap.isOpened():
            break
        print(f"[PHOTO] Waiting for camera... attempt {attempt + 1}/{max_attempts}")
        time.sleep(1.0)
    else:
        return JsonResponse({"status": "camera not available after wait"}, status=500)

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



@csrf_exempt
def delete_media_file(request):
    if request.method == "POST":
        rel_path = request.POST.get("file_path")
        if not rel_path:
            messages.warning(request, "No file path provided.")
            return redirect("media_browser")

        # Auflösen in absoluten Pfad
        abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)

        if os.path.exists(abs_path):
            try:
                os.remove(abs_path)
                messages.success(request, f"{os.path.basename(abs_path)} deleted.")
            except Exception as e:
                messages.error(request, f"Failed to delete {abs_path}: {e}")
        else:
            messages.warning(request, f"File not found: {rel_path}")

    return redirect("media_browser")


def delete_all_images(request):
    base_path = os.path.join(settings.MEDIA_ROOT, "photos")
    for f in glob.glob(os.path.join(base_path, "*.jpg")):
        os.remove(f)
    return redirect("media_browser")

def delete_all_videos(request):
    base_path = os.path.join(settings.MEDIA_ROOT, "videos")
    for f in glob.glob(os.path.join(base_path, "*.mp4")):
        os.remove(f)
    return redirect("media_browser")
