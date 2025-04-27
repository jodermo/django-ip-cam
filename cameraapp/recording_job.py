# cameraapp/recording_job.py

import os
import threading
import time
import logging
import cv2
from typing import Callable

from .camera_utils import apply_cv_settings, get_camera_settings
from .globals import app_globals
from .livestream_job import LiveStreamJob
from .camera_utils import safe_restart_camera_stream, update_latest_frame

logger = logging.getLogger(__name__)


def ensure_livestream_running():
    """
    Starts the livestream if not already running.
    """
    if app_globals.livestream_job and getattr(app_globals.livestream_job, 'running', False):
        logger.debug("[RecordingJob] Livestream already running")
        return

    logger.info("[RecordingJob] Starting livestream before recording...")
    cam = app_globals.camera
    if not cam or not cam.cap or not cam.cap.isOpened():
        logger.error("[RecordingJob] Cannot start livestream – camera.cap is invalid")
        return

    settings = get_camera_settings()
    if settings:
        try:
            apply_cv_settings(cam, settings, mode="video")
        except Exception as e:
            logger.warning(f"[RecordingJob] Failed to apply video settings: {e}")

    job = LiveStreamJob(
        camera_source=0,
        frame_callback=lambda f: setattr(app_globals, 'latest_frame', f.copy()),
        shared_capture=cam.cap
    )
    job.start()
    app_globals.livestream_job = job
    logger.info("[RecordingJob] Livestream started successfully")


class RecordingJob:
    def __init__(
        self,
        filepath: str,
        duration: float,
        fps: float,
        resolution: tuple[int, int],
        codec: str,
        frame_provider: Callable[[], any],
        lock: threading.Lock
    ):
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
        ensure_livestream_running()
        self.active = True
        self.thread.start()

    def _run(self) -> None:
        logger.info(f"[RecordingJob] Opening writer: {self.filepath}")
        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        out = cv2.VideoWriter(self.filepath, fourcc, self.fps, self.resolution)

        if not out.isOpened():
            logger.error(f"[RecordingJob] Cannot open VideoWriter for {self.filepath}")
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
                    logger.debug("[RecordingJob] Waiting for first frame...")
                elif time.time() - empty_start > max_empty:
                    logger.error("[RecordingJob] No frames for too long, aborting")
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
                    logger.info(f"[RecordingJob] Wrote {self.frame_count} frames")
            except Exception as e:
                logger.error(f"[RecordingJob] Write error: {e}")
                break

        out.release()
        self.active = False
        logger.info(f"[RecordingJob] Finished: {self.frame_count} frames to {self.filepath}")

    def stop(self) -> None:
        if not self.active:
            logger.info(f"[RecordingJob] Already inactive: {self.filepath}")
            return
        logger.info(f"[RecordingJob] Stop requested: {self.filepath}")
        self.active = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
            logger.info("[RecordingJob] Thread joined after stop")
