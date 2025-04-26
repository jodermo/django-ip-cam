import threading

camera_lock = threading.Lock()
latest_frame = None
latest_frame_lock = threading.Lock()
