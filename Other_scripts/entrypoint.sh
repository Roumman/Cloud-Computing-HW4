#!/bin/sh
sleep 5

python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createcachetable
gunicorn review2.wsgi:application --bind=0.0.0.0:8000 --workers=3

exec "$@"
