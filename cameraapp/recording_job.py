# cameraapp/recording_job.py

import threading
import time
import cv2
import os
from .livestream_job import LiveStreamJob
from .camera_utils import try_open_camera, apply_cv_settings, get_camera_settings
from .globals import camera_lock, latest_frame, latest_frame_lock, livestream_resume_lock, livestream_job, taking_foto, camera_capture, active_stream_viewers, last_disconnect_time, recording_timeout
from . import globals

def safe_restart_livestream():
    global livestream_job
    if livestream_job and livestream_job.running:
        livestream_job.stop()
        livestream_job.join(timeout=2.0)

    time.sleep(1.0)
    settings = get_camera_settings()
    cap = try_open_camera(int(os.getenv("CAMERA_URL", "0")), retries=3, delay=1.0)
    if cap and cap.isOpened():
        apply_cv_settings(cap, settings, mode="video")
        livestream_job = LiveStreamJob(
            int(os.getenv("CAMERA_URL", "0")),
            frame_callback=lambda f: setattr(__import__('cameraapp.globals'), 'latest_frame', f.copy()),
            shared_capture=cap
        )
        livestream_job.start()
        print("[RECORDING] Livestream restarted.")
    else:
        print("[RECORDING] Failed to restart livestream.")

class RecordingJob:
    def __init__(self, filepath, duration, fps, resolution, codec, frame_provider, lock):
        self.filepath = filepath
        self.duration = duration
        self.fps = fps
        self.resolution = resolution
        self.codec = codec
        self.frame_provider = frame_provider
        self.lock = lock
        self.thread = threading.Thread(target=self.run)
        self.active = False
        self.frame_count = 0

    def start(self):
        print(f"[RecordingJob] Starting job: {self.filepath}")
        self.active = True
        self.thread.start()

    def run(self):
        print(f"[RecordingJob] Opening VideoWriter: {self.filepath}")
        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        out = cv2.VideoWriter(self.filepath, fourcc, self.fps, self.resolution)
        if not out.isOpened():
            print("[RecordingJob] Error: VideoWriter failed to open.")
            self.active = False
            return

        start_time = time.time()
        max_empty_wait = 5  # seconds without frames before abort
        empty_start = None

        print("[RecordingJob] Recording loop started.")
        while time.time() - start_time < self.duration and self.active:
            with self.lock:
                frame = self.frame_provider()

            if frame is None:
                if empty_start is None:
                    empty_start = time.time()
                    print("[RecordingJob] No frame received, starting empty wait timer.")
                elif time.time() - empty_start > max_empty_wait:
                    print("[RecordingJob] No frames received for too long. Aborting.")
                    break
                time.sleep(0.05)
                continue
            else:
                if empty_start is not None:
                    print("[RecordingJob] Frame received after empty wait.")
                empty_start = None

            try:
                resized = cv2.resize(frame, self.resolution)
                out.write(resized)
                self.frame_count += 1
                if self.frame_count % 10 == 0:
                    print(f"[RecordingJob] Wrote {self.frame_count} frames...")
            except Exception as e:
                print(f"[RecordingJob] Frame write error: {e}")
                break

        print("[RecordingJob] Releasing VideoWriter...")
        out.release()
        self.active = False
        print(f"[RecordingJob] Finished: {self.filepath}, total frames: {self.frame_count}")
        safe_restart_livestream()

    def stop(self):
        print(f"[RecordingJob] Stop requested for: {self.filepath}")
        self.active = False
