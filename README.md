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

your_user_name ALL=(ALL) NOPASSWD: /usr/sbin/reboot
```bash
chmod +x scripts/reboot-host.sh
sudo visudo
your-server-name ALL=(ALL) NOPASSWD: /sbin/reboot
your-server-name ALL=(ALL) NOPASSWD: /usr/sbin/reboot
your-server-name ALL=(ALL) NOPASSWD: /usr/local/bin/reboot-host.sh
www-data ALL=(ALL) NOPASSWD: /usr/local/bin/reboot-server








# run:
sudo nano /usr/local/bin/reboot-host.sh

# add:

#!/bin/bash
echo "[REBOOT SCRIPT] Rebooting the host..."
/sbin/reboot

# run:
sudo chmod +x /usr/local/bin/reboot-host.sh


```

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

## Docker

### Build and run with Docker Compose

1. Create a `.env` file in the root directory (same format as above)

2. Build the image:

    ```bash
    docker-compose build
    ```

3. Run the services:

    ```bash
    docker-compose up
    ```

4. The app will be available at:

    ```
    http://localhost:8000/
    ```





### Run migrations manually (optional)

```bash
docker-compose run web python manage.py migrate
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
│   ├── __init__.py
│   ├── admin.py                 Admin registration for Camera model
│   ├── apps.py                  App config and optional signal loading
│   ├── models.py                Camera model (name, stream_url, active)
│   ├── tests.py                 Test login protection and stream access
│   ├── urls.py                  URL routes for camera view and video stream
│   ├── views.py                 IP camera streaming logic (requires login)
│   └── templates/
│       └── cameraapp/
│           └── stream.html      Camera stream page with embedded MJPEG
├── ipcam_project/
│   ├── __init__.py
│   ├── settings.py              Django settings with .env support and auth config
│   ├── urls.py                  Root URL routing with login/logout and app include
│   ├── wsgi.py                  WSGI entry point for Gunicorn or other servers
│   └── asgi.py                  ASGI entry point for future async support
├── templates/
│   └── registration/
│       └── login.html           Login form used by Django auth system
├── static/                      Static files directory for CSS or JS
├── .env                         Environment variables (secret key, camera URL, debug)
├── .env.example                 Template for .env file
├── .gitignore                   Ignore rules for Git (env files, cache, venv)
├── db.sqlite3                   Default SQLite database file
├── manage.py                    Django management entry script
├── requirements.txt             Python dependencies for Django, OpenCV, dotenv, gunicorn
├── Dockerfile                   Docker build file for the application
├── docker-compose.yml           Compose configuration for running Django and migrations
└── .dockerignore                Ignore rules during Docker build (like .env and staticfiles)

```

```bash
sudo chmod -R 755 ./nginx/certbot/conf
sudo chown -R $USER:$USER ./nginx/certbot/conf


sudo chown -R $USER:$USER ./nginx/certbot/conf
sudo chmod -R u+rw ./nginx/certbot/conf

```
sudo chmod -R 777 ./nginx/certbot/conf

sudo chown -R $USER:$USER nginx/certbot
chmod -R 755 nginx/certbot
sudo chmod -R 755 nginx/certbot/conf/archive

start cert bot for the first time
```bash
docker-compose run --rm certbot
```

run nginx 
```bash
docker-compose up -d nginx django
```

restart nginx 
```bash
docker-compose restart nginx
```
stop nginx 
```bash
docker-compose stop nginx
```

Renew cert
```bash
docker-compose run --rm certbot renew
```


```bash
docker-compose exec django python manage.py makemigrations
docker-compose exec django python manage.py migrate


docker-compose exec django python manage.py createsuperuser
```