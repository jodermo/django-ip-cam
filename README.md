# django-ip-cam

A Django-based web application for streaming live video from an IP camera (RTSP or MJPEG), including user authentication and access protection.

---

## Features

- Live IP camera stream (RTSP/MJPEG)
- User authentication (login/logout)
- Protected stream access for logged-in users only
- `.env`-based configuration (camera URL, secrets, etc.)
- Ready for deployment and extension

---

## Requirements
pi
- Python 3.8+
- Django
- OpenCV (`opencv-python`)
- `python-dotenv`

---

## Installation

1. Clone the repository:

    ```bash
    git clone https://github.com/jodermo/django-ip-cam.git
    cd django-ip-cam
    ```

2. Create and activate a virtual environment:

    ```bash
    python -m venv venv
    source venv/bin/activate  # Windows: venv\Scripts\activate
    ```

3. Install dependencies:

    ```bash
    pip install -r requirements.txt
    ```

4. Create a .env file in the project root:
    ```bash
    CAMERA_URL=rtsp://username:password@192.168.1.100:554/stream
    DJANGO_SECRET_KEY=your-django-secret-key
    DEBUG=True
    ```

5. Run migrations and create a superuser:

    ```bash
    python manage.py migrate
    python manage.py createsuperuser
    ```

6. Start the development server:
    ```bash
    python manage.py runserver
    ```

7. Open in browser:
    ```bash
    http://127.0.0.1:8000/
    ```




## Scripts

```bash
python manage.py runserver
python manage.py migrate
python manage.py createsuperuser
```

## Project Structure

```bash
django-ip-cam/
├── cameraapp/
│   ├── views.py
│   ├── urls.py
│   └── templates/
│       └── cameraapp/
│           └── stream.html
├── ipcam_project/
│   ├── settings.py
│   ├── urls.py
├── .env
├── manage.py
└── requirements.txt
```