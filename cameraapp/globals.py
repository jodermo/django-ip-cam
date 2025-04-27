# cameraapp/globals.py

import threading


class AppGlobals:
    def __init__(self):
        self.camera_lock = threading.Lock()
        self.latest_frame = None
        self.latest_frame_lock = threading.Lock()
        self.livestream_resume_lock = threading.Lock()
        self.livestream_lock = threading.Lock()
        self.livestream_job = None
        self.taking_foto = False
        self.recording_job = None
        self.active_stream_viewers = 0
        self.last_disconnect_time = None
        self.recording_timeout = 30
        self.camera = None


# Singleton Instanz für globale App-Zustände
app_globals = AppGlobals()
