# models.py
from django.db import models

class Camera(models.Model):
    name = models.CharField(max_length=100)
    stream_url = models.URLField()
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name
