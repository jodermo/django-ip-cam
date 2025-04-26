# default
import os
import cv2
import time
import threading
import datetime
import subprocess

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
    init_camera, camera_instance, apply_photo_settings,
    apply_auto_settings, auto_adjust_from_frame, apply_cv_settings
)
from .recording_job import RecordingJob
from .livestream_job import LiveStreamJob
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

# Globals
camera_lock = threading.Lock()
active_stream_viewers = 0
last_disconnect_time = None
latest_frame = None
latest_frame_lock = threading.Lock()
recording_job = None
recording_timeout = 30

# Stream Job
livestream_job = LiveStreamJob(
    camera_source=CAMERA_URL,
    frame_callback=lambda f: update_latest_frame(f)
)

def update_latest_frame(frame):
    global latest_frame
    with latest_frame_lock:
        latest_frame = frame.copy()
    # Optionales Debugging:
    # print(f"[DEBUG] Frame updated at {time.time()}")


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

@login_required
def video_feed(request):

    with camera_lock:
        if not livestream_job.running:
            livestream_job.start()

    def stream_generator():
        frame_fail_count = 0
        while True:
            frame = livestream_job.get_frame()
            if frame is None:
                time.sleep(0.1)
                frame_fail_count += 1
                if frame_fail_count > 100:  # ca. 10 Sekunden keine Frames
                    print("[VIDEO_FEED] No frames received for 10 seconds. Aborting stream.")
                    break
                continue

            frame_fail_count = 0
            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret:
                continue
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" +
                   buffer.tobytes() + b"\r\n")
            time.sleep(0.03)  # Limit auf ~30fps

    try:
        return StreamingHttpResponse(stream_generator(),
            content_type="multipart/x-mixed-replace; boundary=frame")
    except Exception as e:
        print(f"[VIDEO_FEED] Streaming error: {e}")
        return HttpResponseServerError("Streaming error")




@login_required
def stream_page(request):
    settings_obj = get_camera_settings_safe()
    camera_error = None

    if request.method == "POST":
        for field in ["brightness", "contrast", "saturation", "exposure", "gain"]:
            val = request.POST.get(field)
            if val is not None:
                try:
                    setattr(settings_obj, field, float(val))
                except ValueError:
                    pass
        settings_obj.save()
        init_camera()  # Anwenden der neuen Settings

    if not livestream_job.running:
        livestream_job.start()

    if settings_obj is None:
        camera_error = "Settings not ready (DB table missing?)"

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
                print(f"[RECORD_VIDEO] Aufnahme fehlgeschlagen: {filepath}")
            else:
                print(f"[RECORD_VIDEO] Video gespeichert: {filepath}")

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
        print(f"[RECORD_VIDEO] Fehler: {e}")
        return JsonResponse({"error": str(e)}, status=400)



def record_video_to_file(filepath, duration, fps, resolution, codec="mp4v"):
    """
    Nimmt ein Video mit aktuellen Live-Frames auf und speichert es als Datei.

    Args:
        filepath (str): Zielpfad der Videodatei
        duration (int): Aufnahmedauer in Sekunden
        fps (float): Bilder pro Sekunde
        resolution (tuple): Zielauflösung (Breite, Höhe)
        codec (str): Video-Codec (z. B. 'mp4v', 'XVID', 'MJPG')

    Returns:
        bool: True, wenn mindestens ein Frame erfolgreich gespeichert wurde
    """
    print(f"[RECORD_TO_FILE] Start recording to {filepath} (duration={duration}s, fps={fps}, resolution={resolution})")

    try:
        fourcc = cv2.VideoWriter_fourcc(*codec)
        out = cv2.VideoWriter(filepath, fourcc, fps, resolution)
        if not out.isOpened():
            print(f"[RECORD_TO_FILE] Fehler: Kann Datei {filepath} nicht öffnen.")
            return False

        frame_count = 0
        start_time = time.time()

        while time.time() - start_time < duration:
            with latest_frame_lock:
                frame = latest_frame.copy() if latest_frame is not None else None

            if frame is None:
                time.sleep(0.05)
                continue

            resized_frame = cv2.resize(frame.copy(), resolution)
            out.write(resized_frame)
            frame_count += 1

            time.sleep(1.0 / fps)  # Taktet exakt auf Ziel-FPS

    except Exception as e:
        print(f"[RECORD_TO_FILE] Ausnahme beim Schreiben: {e}")
        return False

    finally:
        out.release()
        print(f"[RECORD_TO_FILE] Aufzeichnung abgeschlossen: {frame_count} Frames gespeichert → {filepath}")

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
    """Aktualisiert Video-Kameraeinstellungen aus einem POST-Formular und wendet sie an."""
    try:
        settings_obj = CameraSettings.objects.first()
        if settings_obj:
            for param in ["brightness", "contrast", "saturation", "exposure", "gain"]:
                value = request.POST.get(param)
                if value is not None:
                    try:
                        setattr(settings_obj, f"video_{param}", float(value))
                    except ValueError:
                        print(f"[UPDATE_CAMERA_SETTINGS] Ungültiger Wert für {param}: {value}")
                        continue

            # Optional: Belichtungsmodus setzen (auto/manuell)
            exposure_mode = request.POST.get("exposure_mode")
            if exposure_mode in ["auto", "manual"]:
                settings_obj.video_exposure_mode = exposure_mode

            settings_obj.save()

            print("[UPDATE_CAMERA_SETTINGS] Neue Einstellungen gespeichert. Kamera wird neu initialisiert.")
            init_camera()
        else:
            print("[UPDATE_CAMERA_SETTINGS] Kein CameraSettings-Objekt vorhanden.")

    except Exception as e:
        print(f"[UPDATE_CAMERA_SETTINGS] Fehler beim Aktualisieren der Kameraeinstellungen: {e}")

    return HttpResponseRedirect(reverse("stream_page"))




@require_POST
@login_required
def update_photo_settings(request):
    """Aktualisiert Foto-Kameraeinstellungen aus dem Formular."""
    try:
        settings_obj = CameraSettings.objects.first()
        if not settings_obj:
            print("[UPDATE_PHOTO_SETTINGS] Kein CameraSettings-Objekt gefunden.")
            return HttpResponseRedirect(reverse("photo_settings_page"))

        for param in ["brightness", "contrast", "saturation", "exposure", "gain"]:
            value = request.POST.get(f"photo_{param}")
            if value is not None:
                try:
                    setattr(settings_obj, f"photo_{param}", float(value))
                except ValueError:
                    print(f"[UPDATE_PHOTO_SETTINGS] Ungültiger Wert für {param}: {value}")
                    continue

        # OPTIONAL: Belichtungsmodus auch für Foto speichern (falls du es implementierst)
        exposure_mode = request.POST.get("photo_exposure_mode")
        if exposure_mode in ["auto", "manual"]:
            setattr(settings_obj, "photo_exposure_mode", exposure_mode)

        settings_obj.save()
        print("[UPDATE_PHOTO_SETTINGS] Fotoeinstellungen gespeichert.")

        # Optional anwenden:
        # apply_photo_settings(camera_instance, settings_obj)

    except Exception as e:
        print(f"[UPDATE_PHOTO_SETTINGS] Fehler beim Speichern der Fotoeinstellungen: {e}")

    return HttpResponseRedirect(reverse("photo_settings_page"))




def pause_livestream():
    if livestream_job.running:
        livestream_job.stop()
        print("[PHOTO] Livestream wurde pausiert für Fotoaufnahme.")
        time.sleep(0.5)  # Kamera freigeben lassen

def resume_livestream():
    print("[PHOTO] Warte auf Freigabe der Kamera...")
    time.sleep(1.5)

    if not livestream_job.running:
        for attempt in range(3):
            livestream_job.start()
            time.sleep(1.0)
            if livestream_job.running and livestream_job.get_frame() is not None:
                print("[PHOTO] Livestream wurde wieder gestartet.")
                return
            print(f"[PHOTO] Livestream-Neustart fehlgeschlagen (Versuch {attempt + 1})")
            livestream_job.stop()
            time.sleep(1.5)

        print("[PHOTO] Livestream konnte nicht gestartet werden.")



@require_POST
@login_required
def take_photo_now(request):
    with camera_lock:
        pause_livestream()
        try:
            success = take_photo()
            if not success:
                return JsonResponse({"status": "Kamera konnte nicht geöffnet werden."}, status=500)
        finally:
            resume_livestream()
    return JsonResponse({"status": "ok"})


@require_POST
@login_required
def auto_photo_settings(request):
    settings = CameraSettings.objects.first()
    if not settings:
        return JsonResponse({"success": False, "message": "Keine Kameraeinstellungen gefunden."})

    apply_auto_settings(settings)
    return JsonResponse({"success": True, "message": "Autoeinstellungen angewendet."})

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