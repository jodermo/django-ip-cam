from django.db import models

class Camera(models.Model):
    name = models.CharField(max_length=100)
    stream_url = models.URLField()
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class CameraSettings(models.Model):
    # Slideshow
    interval_ms = models.PositiveIntegerField(default=3000)
    duration_sec = models.PositiveIntegerField(default=30)
    overlay_timestamp = models.BooleanField(default=True)
    default_camera_url = models.CharField(max_length=255, default="0")
    auto_play = models.BooleanField(default=False)

    # Timelapse
    photo_interval_min = models.PositiveIntegerField(default=15)
    timelapse_enabled = models.BooleanField(default=True)

    # Recording
    record_fps = models.FloatField(default=20.0)
    resolution_width = models.PositiveIntegerField(default=640)
    resolution_height = models.PositiveIntegerField(default=480)
    video_codec = models.CharField(max_length=10, default="mp4v")  # z. B. "mp4v", "XVID", "MJPG"

    def __str__(self):
        return "Global Camera Settings"

    class Meta:
        verbose_name = "Camera Settings"
        verbose_name_plural = "Camera Settings"
