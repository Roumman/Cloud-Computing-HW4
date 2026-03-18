#!/bin/bash

if [[ "${1}" == "celery" ]]; then
  celery --app=review2.celery:celery_app worker -l INFO
elif [[ "${1}" == "flower" ]]; then
  celery --app=review2.celery:celery_app flower --url_prefix=/flower
 fi
