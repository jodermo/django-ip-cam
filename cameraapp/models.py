from django.db import models

class Camera(models.Model):
    name = models.CharField(max_length=100)
    stream_url = models.URLField()
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class CameraSettings(models.Model):
    interval_ms = models.PositiveIntegerField(default=3000)  # Zeit pro Bild (Slideshow)
    duration_sec = models.PositiveIntegerField(default=30)   # Slideshow-Dauer
    overlay_timestamp = models.BooleanField(default=True)
    default_camera_url = models.CharField(max_length=255, default="0")
    auto_play = models.BooleanField(default=False)

    # Timelapse specific parameters
    photo_interval_min = models.PositiveIntegerField(default=15)  # Zeit zwischen Timelapse-Fotos (Minuten)
    timelapse_enabled = models.BooleanField(default=True)         # Aktiviert Timelapse-Aufnahmen

    def __str__(self):
        return "Global Camera Settings"

    class Meta:
        verbose_name = "Camera Settings"
        verbose_name_plural = "Camera Settings"