from django.urls import path
from . import views


urlpatterns = [
    path("", views.stream_page, name="stream_page"),
    path("video_feed/", views.video_feed, name="video_feed"),
    path("record_video/", views.record_video, name="record_video"),
    path("gallery/", views.photo_gallery, name="photo_gallery"),
]
