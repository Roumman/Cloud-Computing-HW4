# Kubernetes — Порядок сборки манифестов

Приложение: Django + Celery + Flower + Nginx + PostgreSQL (HA) + Redis

## Структура директорий

```
k8s/
├── 00-namespace.yaml                           # Namespace приложения
├── 01-secrets/
│   ├── 01-docker-registry-secret.yaml         # Секрет для Docker Registry
│   ├── 02-basic-auth-secret.yaml              # Секрет для Basic Auth (Ingress)
│   └── 03-app-secret.yaml                     # Секреты приложения (пароли БД)
├── 02-configmaps/
│   ├── 01-nginx-config.yaml                   # Конфигурация Nginx
│   ├── 02-postgres-init-config.yaml           # Init-скрипты PostgreSQL (репликация)
│   └── 03-tcp-services-config.yaml            # TCP-проксирование PostgreSQL через Ingress
├── 03-statefulsets/
│   ├── 01-redis-statefulset.yaml              # Redis (брокер Celery + кэш Django)
│   ├── 02-postgres-primary-statefulset.yaml   # PostgreSQL Primary (мастер)
│   └── 03-postgres-replica-statefulset.yaml   # PostgreSQL Replica (hot standby, HA)
├── 04-deployments/
│   ├── 01-django-deployment.yaml              # Django (gunicorn, 2 реплики)
│   ├── 02-celery-deployment.yaml              # Celery Worker (2 реплики)
│   ├── 03-flower-deployment.yaml              # Flower (мониторинг Celery)
│   └── 04-nginx-deployment.yaml              # Nginx (reverse proxy + статика)
├── 05-services/
│   ├── 01-redis-service.yaml                  # ClusterIP: redis:6379
│   ├── 02-postgres-primary-service.yaml       # ClusterIP: postgres-primary:5432 (headless + lb)
│   ├── 03-postgres-replica-service.yaml       # ClusterIP: postgres-replica:5432 (headless + lb)
│   ├── 04-django-service.yaml                 # ClusterIP: django:8000
│   ├── 05-flower-service.yaml                 # ClusterIP: flower:5555
│   └── 06-nginx-service.yaml                  # ClusterIP: nginx:80
├── 06-jobs/
│   ├── 01-migrate-job.yaml                    # Job: миграции Django (одноразовый)
│   └── 02-daily-cleanup-cronjob.yaml          # CronJob: ежедневная очистка (03:00 UTC)
└── 07-ingress/
    ├── 01-main-ingress.yaml                   # Ingress: app.local → nginx, django
    └── 02-flower-ingress.yaml                 # Ingress: flower.local (Basic Auth), backend.local
```

---

## Предварительные требования

### 1. Сборка и публикация Docker-образа

```bash
# Собрать образ Django-приложения
docker build -t registry.example.com/django-app:latest .

# Авторизоваться в registry
docker login registry.example.com

# Опубликовать образ
docker push registry.example.com/django-app:latest
```

> Замените `registry.example.com/django-app:latest` на реальный адрес вашего registry
> во всех файлах `04-deployments/` и `06-jobs/`.

### 2. Установка Nginx Ingress Controller

```bash
# Через kubectl
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/cloud/deploy.yaml

# Или через Helm (рекомендуется)
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.extraArgs.tcp-services-configmap=ingress-nginx/tcp-services

# Дождаться готовности
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

### 3. Настройка /etc/hosts (для локального тестирования)

```bash
# Получить IP Ingress Controller
INGRESS_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# Добавить в /etc/hosts
echo "$INGRESS_IP app.local flower.local backend.local" | sudo tee -a /etc/hosts
```

---

## Порядок применения манифестов

> **ВАЖНО**: Манифесты применяются строго в указанном порядке.
> Нарушение порядка приведёт к ошибкам (поды не найдут секреты/сервисы).

### Шаг 1: Namespace

```bash
kubectl apply -f k8s/00-namespace.yaml
```

Создаёт namespace `app`, в котором будут развёрнуты все компоненты.

---

### Шаг 2: Секреты

```bash
kubectl apply -f k8s/01-secrets/
```

**2а. Перед применением — сгенерировать реальные секреты:**

**Docker Registry Secret:**
```bash
kubectl create secret docker-registry docker-registry-secret \
  --docker-server=registry.example.com \
  --docker-username=YOUR_USERNAME \
  --docker-password=YOUR_PASSWORD \
  --namespace=app \
  --dry-run=client -o yaml > k8s/01-secrets/01-docker-registry-secret.yaml
```

**Basic Auth Secret:**
```bash
# Установить htpasswd (пакет apache2-utils или httpd-tools)
htpasswd -nb admin YOUR_SECURE_PASSWORD > auth_file

# Создать секрет
kubectl create secret generic basic-auth-secret \
  --from-file=auth=auth_file \
  --namespace=app \
  --dry-run=client -o yaml > k8s/01-secrets/02-basic-auth-secret.yaml

rm auth_file
```

**App Secret** (`03-app-secret.yaml`): при необходимости измените пароли.

---

### Шаг 3: ConfigMaps

```bash
kubectl apply -f k8s/02-configmaps/
```

Применяет:
- Конфигурацию Nginx (nginx-config)
- Init-скрипты PostgreSQL для репликации (postgres-init-config)
- TCP-сервисы для Ingress (tcp-services, в namespace `ingress-nginx`)

---

### Шаг 4: StatefulSets (базы данных)

```bash
# 4а. Redis
kubectl apply -f k8s/03-statefulsets/01-redis-statefulset.yaml

# 4б. PostgreSQL Primary (мастер)
kubectl apply -f k8s/03-statefulsets/02-postgres-primary-statefulset.yaml

# Дождаться готовности Primary перед запуском Replica!
kubectl wait --for=condition=ready pod/postgres-primary-0 \
  --namespace=app --timeout=120s

# 4в. PostgreSQL Replica (hot standby)
# Init-контейнер replica автоматически скопирует данные с primary (pg_basebackup)
kubectl apply -f k8s/03-statefulsets/03-postgres-replica-statefulset.yaml
```

> **Почему важен порядок**: Replica использует init-контейнер, который ждёт
> готовности Primary и затем запускает `pg_basebackup`. Если Primary не готов,
> Replica будет ждать (не упадёт с ошибкой, но деплой займёт больше времени).

---

### Шаг 5: Services (ClusterIP)

```bash
kubectl apply -f k8s/05-services/
```

Создаёт все ClusterIP Services. Services должны быть созданы **до** Deployments,
чтобы init-контейнеры могли резолвить DNS имена (postgres-primary, redis и т.д.).

---

### Шаг 6: Job — миграции Django

```bash
kubectl apply -f k8s/06-jobs/01-migrate-job.yaml

# Дождаться завершения миграций
kubectl wait --for=condition=complete job/django-migrate \
  --namespace=app --timeout=300s

# Проверить логи
kubectl logs -n app job/django-migrate
```

> **ВАЖНО**: Deployments Django, Celery и Flower должны быть запущены
> **ПОСЛЕ** успешного завершения этого Job. Без миграций приложение упадёт
> при попытке обратиться к БД.

---

### Шаг 7: Deployments (приложение)

```bash
kubectl apply -f k8s/04-deployments/
```

Запускает все компоненты приложения:
- Django (gunicorn, 2 реплики)
- Celery Worker (2 реплики)
- Flower (мониторинг)
- Nginx (reverse proxy)

---

### Шаг 8: CronJob — ежедневные задачи

```bash
kubectl apply -f k8s/06-jobs/02-daily-cleanup-cronjob.yaml
```

Регистрирует CronJob для ежедневной очистки истёкших сессий (03:00 UTC).

---

### Шаг 9: Ingress

```bash
kubectl apply -f k8s/07-ingress/
```

Создаёт Ingress-правила для маршрутизации внешнего трафика.

---

## Применение всем сразу (с соблюдением порядка)

```bash
#!/bin/bash
set -e

echo "=== Step 1: Namespace ==="
kubectl apply -f k8s/00-namespace.yaml

echo "=== Step 2: Secrets ==="
kubectl apply -f k8s/01-secrets/

echo "=== Step 3: ConfigMaps ==="
kubectl apply -f k8s/02-configmaps/

echo "=== Step 4a: Redis StatefulSet ==="
kubectl apply -f k8s/03-statefulsets/01-redis-statefulset.yaml

echo "=== Step 4b: PostgreSQL Primary ==="
kubectl apply -f k8s/03-statefulsets/02-postgres-primary-statefulset.yaml
kubectl wait --for=condition=ready pod/postgres-primary-0 \
  --namespace=app --timeout=120s

echo "=== Step 4c: PostgreSQL Replica (HA) ==="
kubectl apply -f k8s/03-statefulsets/03-postgres-replica-statefulset.yaml

echo "=== Step 5: Services ==="
kubectl apply -f k8s/05-services/

echo "=== Step 6: Migration Job ==="
kubectl apply -f k8s/06-jobs/01-migrate-job.yaml
kubectl wait --for=condition=complete job/django-migrate \
  --namespace=app --timeout=300s

echo "=== Step 7: Deployments ==="
kubectl apply -f k8s/04-deployments/

echo "=== Step 8: CronJob ==="
kubectl apply -f k8s/06-jobs/02-daily-cleanup-cronjob.yaml

echo "=== Step 9: Ingress ==="
kubectl apply -f k8s/07-ingress/

echo "=== Done! ==="
```

---

## Проверка состояния кластера

```bash
# Все поды в namespace app
kubectl get pods -n app

# StatefulSets (Redis, PostgreSQL)
kubectl get statefulsets -n app

# Deployments
kubectl get deployments -n app

# Services
kubectl get services -n app

# Ingress
kubectl get ingress -n app

# Jobs и CronJobs
kubectl get jobs,cronjobs -n app
```

### Ожидаемый вывод `kubectl get pods -n app`:

```
NAME                              READY   STATUS      RESTARTS   AGE
celery-worker-xxx                 1/1     Running     0          5m
celery-worker-yyy                 1/1     Running     0          5m
django-xxx                        1/1     Running     0          5m
django-yyy                        1/1     Running     0          5m
django-migrate-xxx                0/1     Completed   0          7m
flower-xxx                        1/1     Running     0          5m
nginx-xxx                         1/1     Running     0          5m
postgres-primary-0                1/1     Running     0          10m
postgres-replica-0                1/1     Running     0          8m
redis-0                           1/1     Running     0          10m
```

---

## Проверка High Availability PostgreSQL

### Статус репликации:

```bash
# На Primary — проверить список реплик
kubectl exec -n app postgres-primary-0 -- \
  psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# На Replica — проверить статус WAL receiver
kubectl exec -n app postgres-replica-0 -- \
  psql -U postgres -c "SELECT * FROM pg_stat_wal_receiver;"

# Проверить режим (primary/replica)
kubectl exec -n app postgres-primary-0 -- \
  psql -U postgres -c "SELECT pg_is_in_recovery();"
# Ожидаемый результат для primary: f (false)

kubectl exec -n app postgres-replica-0 -- \
  psql -U postgres -c "SELECT pg_is_in_recovery();"
# Ожидаемый результат для replica: t (true)
```

### Failover (продвижение реплики до primary):

```bash
# При отказе primary — продвинуть реплику
kubectl exec -n app postgres-replica-0 -- \
  pg_ctl promote -D /var/lib/postgresql/data/pgdata

# Обновить POSTGRES_HOST в секрете/конфигурации приложения
# на postgres-replica-0.postgres-replica.app.svc.cluster.local
```

---

## Доступ к приложению

| Компонент   | URL                        | Описание                      |
|-------------|----------------------------|-------------------------------|
| Frontend    | http://app.local/          | Nginx → Django (основное приложение) |
| Backend API | http://app.local/api/      | Прямой доступ к Django через Ingress |
| Flower      | http://flower.local/flower/| Мониторинг Celery (Basic Auth) |
| Backend     | http://backend.local/      | Django (Basic Auth)            |
| PostgreSQL  | app.local:5432             | TCP через Nginx Ingress (порт 5432) |
| PG Replica  | app.local:5433             | TCP через Nginx Ingress (порт 5433, read-only) |

---

## Архитектура

```
                    ┌──────────────────────────────────┐
Internet ──HTTP──→  │   Nginx Ingress Controller        │
                    │   app.local     → nginx:80        │
                    │   app.local/api → django:8000     │
                    │   flower.local  → flower:5555     │  (Basic Auth)
                    │   backend.local → django:8000     │  (Basic Auth)
                    │   :5432 TCP     → postgres-primary│
                    │   :5433 TCP     → postgres-replica│
                    └──────────────────────────────────┘
                                  │
                    ┌─────────────▼──────────────────────┐
                    │         Namespace: app              │
                    │                                     │
                    │  ┌─────────┐   ┌───────────────┐   │
                    │  │  nginx  │──→│    django     │   │
                    │  │(Deployment)│ │ (Deployment)  │   │
                    │  │  port 80│   │  port 8000    │   │
                    │  └────┬────┘   └───────┬───────┘   │
                    │       │                │            │
                    │  ┌────▼────┐   ┌───────▼───────┐   │
                    │  │  flower │   │ celery-worker │   │
                    │  │(Deployment)│ │ (Deployment)  │   │
                    │  │ port 5555│  │ 2 replicas    │   │
                    │  └─────────┘   └───────────────┘   │
                    │                        │            │
                    │              ┌─────────▼──────────┐ │
                    │              │     redis:6379      │ │
                    │              │    (StatefulSet)    │ │
                    │              └────────────────────┘ │
                    │                                     │
                    │  ┌──────────────────────────────┐   │
                    │  │     PostgreSQL HA             │   │
                    │  │  postgres-primary:5432        │   │
                    │  │  (StatefulSet, master)        │   │
                    │  │         ↕ WAL streaming       │   │
                    │  │  postgres-replica:5432        │   │
                    │  │  (StatefulSet, hot standby)   │   │
                    │  └──────────────────────────────┘   │
                    └─────────────────────────────────────┘
```

---

## Описание компонентов

### Deployments (Поды приложения)

| Компонент      | Реплики | Образ                        | Назначение                        |
|---------------|---------|------------------------------|-----------------------------------|
| django        | 2       | registry.example.com/django-app | Gunicorn WSGI сервер Django    |
| celery-worker | 2       | registry.example.com/django-app | Обработчик фоновых задач Celery |
| flower        | 1       | registry.example.com/django-app | Веб-мониторинг Celery           |
| nginx         | 1       | nginx:latest                 | Reverse proxy, раздача статики    |

### StatefulSets (Базы данных)

| Компонент        | Реплики | Образ         | Назначение                    |
|-----------------|---------|---------------|-------------------------------|
| postgres-primary | 1       | postgres:16   | PostgreSQL мастер (R/W)       |
| postgres-replica | 1       | postgres:16   | PostgreSQL реплика (RO, HA)   |
| redis           | 1       | redis:alpine  | Брокер Celery + кэш Django    |

### Services (ClusterIP)

| Сервис              | Порт | Назначение                               |
|--------------------|------|------------------------------------------|
| redis              | 6379 | Redis для Celery и кэша                  |
| postgres-primary   | 5432 | Headless service для StatefulSet         |
| postgres-master    | 5432 | ClusterIP для R/W подключений            |
| postgres-replica   | 5432 | Headless service для StatefulSet реплики |
| postgres-replica-lb| 5432 | ClusterIP для RO подключений (балансировка) |
| django             | 8000 | Django gunicorn                          |
| flower             | 5555 | Flower мониторинг                        |
| nginx              | 80   | Nginx frontend                           |

### Ingress

| Ingress         | Host          | Auth        | Backend         |
|----------------|---------------|-------------|-----------------|
| app-ingress    | app.local/    | нет         | nginx:80        |
| app-ingress    | app.local/api | нет         | django:8000     |
| flower-ingress | flower.local/ | Basic Auth  | flower:5555     |
| backend-ingress| backend.local/| Basic Auth  | django:8000     |
| tcp-services   | :5432         | нет (TCP)   | postgres-primary|
| tcp-services   | :5433         | нет (TCP)   | postgres-replica|

### Jobs

| Job             | Тип     | Расписание  | Назначение                        |
|----------------|---------|-------------|-----------------------------------|
| django-migrate  | Job     | одноразовый | Django migrate + createcachetable |
| daily-cleanup   | CronJob | 0 3 * * *   | clearsessions (очистка сессий)    |

### Секреты

| Секрет                 | Тип                             | Назначение                    |
|-----------------------|---------------------------------|-------------------------------|
| docker-registry-secret | kubernetes.io/dockerconfigjson | Pull образов из приватного registry |
| basic-auth-secret     | Opaque                          | htpasswd для Basic Auth Ingress |
| app-secret            | Opaque                          | Пароли PostgreSQL              |
