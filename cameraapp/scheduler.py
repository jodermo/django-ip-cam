# scheduler.py
import os
import time
from datetime import datetime
from django.conf import settings
from django.apps import apps
from django.db import connections

# Import global Kameraobjekte und Methoden aus views
from cameraapp.views import camera_lock, camera_instance, read_frame, is_camera_open, init_camera

# Verzeichnis für Fotos
PHOTO_DIR = os.path.join(settings.MEDIA_ROOT, "photos")
os.makedirs(PHOTO_DIR, exist_ok=True)

def get_camera_settings():
    """Lädt die aktuellen Kameraeinstellungen aus der Datenbank."""
    CameraSettings = apps.get_model("cameraapp", "CameraSettings")
    return CameraSettings.objects.first()

def take_photo():
    """Nimmt ein Foto auf und speichert es mit Zeitstempel."""
    with camera_lock:
        if not is_camera_open():
            init_camera()

        frame = read_frame()
        if frame is None:
            print("[PHOTO] Fehler: Kein Bild aufgenommen.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp}.jpg"
        filepath = os.path.join(PHOTO_DIR, filename)
        success = cv2.imwrite(filepath, frame)

        if success:
            print(f"[PHOTO] Gespeichert: {filepath}")
        else:
            print(f"[PHOTO] Fehler beim Speichern von: {filepath}")

def wait_for_table(table_name, db_alias="default", timeout=30):
    """Wartet darauf, dass die Datenbanktabelle verfügbar ist (z. B. nach Container-Start)."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with connections[db_alias].cursor() as cursor:
                cursor.execute(f"SELECT 1 FROM {table_name} LIMIT 1")
            return
        except Exception:
            time.sleep(1)
    print(f"[ERROR] Timeout: Tabelle {table_name} nicht verfügbar nach {timeout} Sekunden.")

def start_photo_scheduler():
    """Startet den Endlosschleifen-Fototimer, sofern Timelapse aktiviert ist."""
    print("[SCHEDULER] Initialisiere Timelapse...")
    wait_for_table("cameraapp_camerasettings")

    while True:
        settings_obj = get_camera_settings()
        if settings_obj and settings_obj.timelapse_enabled:
            take_photo()
            interval_min = settings_obj.photo_interval_min
        else:
            interval_min = 15  # Fallback
        time.sleep(interval_min * 60)
