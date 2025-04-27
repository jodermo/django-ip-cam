# cameraapp/recording_job.py

import threading
import time
import cv2
import os

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

    def stop(self):
        print(f"[RecordingJob] Stop requested for: {self.filepath}")
        self.active = False
