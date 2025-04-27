# cameraapp/recording_job.py

import os
import threading
import time
import logging
import cv2
from .camera_utils import try_open_camera, apply_cv_settings, get_camera_settings
from . import globals as app_globals

logger = logging.getLogger(__name__)


def safe_restart_livestream():
    """
    Stop any running livestream and restart it using shared globals.
    """
    if app_globals.livestream_job and getattr(app_globals.livestream_job, 'running', False):
        logger.info("[RECORDING] Stopping existing livestream...")
        try:
            app_globals.livestream_job.stop()
            app_globals.livestream_job.join(timeout=2.0)
        except Exception as e:
            logger.warning(f"[RECORDING] Error stopping livestream: {e}")

    time.sleep(1.0)
    settings = get_camera_settings()
    cap = try_open_camera(int(os.getenv("CAMERA_URL", "0")), retries=3, delay=1.0)
    if not cap or not cap.isOpened():
        logger.error("[RECORDING] Failed to reopen camera for livestream.")
        return

    apply_cv_settings(cap, settings, mode="video")
    from .livestream_job import LiveStreamJob
    job = LiveStreamJob(
        camera_source=int(os.getenv("CAMERA_URL", "0")),
        frame_callback=lambda f: setattr(app_globals, 'latest_frame', f.copy()),
        shared_capture=cap
    )
    job.start()
    app_globals.livestream_job = job
    logger.info("[RECORDING] Livestream restarted successfully.")


class RecordingJob:
    def __init__(self, filepath: str, duration: float, fps: float, resolution: tuple[int,int], 
                 codec: str, frame_provider: callable, lock: threading.Lock):
        self.filepath = filepath
        self.duration = duration
        self.fps = fps
        self.resolution = resolution
        self.codec = codec
        self.frame_provider = frame_provider
        self.lock = lock
        self.thread = threading.Thread(target=self._run, name="RecordingJob", daemon=True)
        self.active = False
        self.frame_count = 0

    def start(self) -> None:
        logger.info(f"[RecordingJob] Starting: {self.filepath}")
        self.active = True
        self.thread.start()

    def _run(self) -> None:
        logger.info(f"[RecordingJob] Opening writer: {self.filepath}")
        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        out = cv2.VideoWriter(self.filepath, fourcc, self.fps, self.resolution)
        if not out.isOpened():
            logger.error("[RecordingJob] Cannot open VideoWriter.")
            self.active = False
            return

        start_time = time.time()
        empty_start = None
        max_empty = 5

        while self.active and (time.time() - start_time) < self.duration:
            with self.lock:
                frame = self.frame_provider()

            if frame is None:
                if empty_start is None:
                    empty_start = time.time()
                    logger.debug("[RecordingJob] No frame yet, waiting...")
                elif (time.time() - empty_start) > max_empty:
                    logger.error("[RecordingJob] No frames for too long, aborting.")
                    break
                time.sleep(0.05)
                continue
            else:
                empty_start = None

            try:
                resized = cv2.resize(frame, self.resolution)
                out.write(resized)
                self.frame_count += 1
                if self.frame_count % 10 == 0:
                    logger.info(f"[RecordingJob] Wrote {self.frame_count} frames...")
            except Exception as e:
                logger.error(f"[RecordingJob] Write error: {e}")
                break

        out.release()
        self.active = False
        logger.info(f"[RecordingJob] Finished: {self.frame_count} frames to {self.filepath}")
        safe_restart_livestream()

    def stop(self) -> None:
        logger.info(f"[RecordingJob] Stop requested: {self.filepath}")
        self.active = False