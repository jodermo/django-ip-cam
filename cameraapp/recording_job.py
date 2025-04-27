# cameraapp/recording_job.py

import threading
import time
import logging
import cv2
from typing import Callable

logger = logging.getLogger(__name__)

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
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.active = False
        self.frame_count = 0

    def start(self):
        logger.info(f"[RecordingJob] Starting recording to {self.filepath}")
        self.active = True
        self.thread.start()

    def stop(self):
        logger.info("[RecordingJob] Stop requested.")
        self.active = False
        if self.thread.is_alive():
            self.thread.join(timeout=2.0)
            logger.info("[RecordingJob] Thread stopped.")

    def _run(self):
        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        out = cv2.VideoWriter(self.filepath, fourcc, self.fps, self.resolution)

        if not out.isOpened():
            logger.error(f"[RecordingJob] Failed to open file: {self.filepath}")
            self.active = False
            return

        start_time = time.time()
        max_wait = 5  # max seconds waiting for frames
        empty_frame_start = None

        while self.active and (time.time() - start_time) < self.duration:
            with self.lock:
                frame = self.frame_provider()

            if frame is None:
                if empty_frame_start is None:
                    empty_frame_start = time.time()
                elif time.time() - empty_frame_start > max_wait:
                    logger.warning("[RecordingJob] No frames for too long → abort")
                    break
                time.sleep(0.05)
                continue

            empty_frame_start = None

            try:
                resized = cv2.resize(frame, self.resolution)
                out.write(resized)
                self.frame_count += 1
            except Exception as e:
                logger.error(f"[RecordingJob] Write error: {e}")
                break

            time.sleep(1.0 / self.fps)

        out.release()
        logger.info(f"[RecordingJob] Done recording {self.frame_count} frames → {self.filepath}")
        self.active = False
