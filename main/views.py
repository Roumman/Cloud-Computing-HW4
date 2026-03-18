import os
import requests
from celery.result import AsyncResult

from django.shortcuts import render, redirect
import wikipedia
import bs4

from main import MODEL_PATH, DATA_PATH, TRAIN_TASK_ID, TEMPLATES
from main.tasks import train_model_task, get_similar_task


def index(request):
    if TRAIN_TASK_ID in os.environ:
        existing_train_task_id = os.environ[TRAIN_TASK_ID]
        existing_train_task = AsyncResult(existing_train_task_id)

        if existing_train_task.state in ["PENDING", "STARTED", "PROGRESS"]:
            return render(
                request, TEMPLATES["train_in_progress"], context={"a": os.listdir()}
            )
        elif existing_train_task.state == "FAILURE":
            return render(request, TEMPLATES["model_corrupted"])

    if os.path.exists(MODEL_PATH) and os.path.exists(DATA_PATH):
        return render(request, TEMPLATES["index"])
    elif TRAIN_TASK_ID not in os.environ:
        return render(request, TEMPLATES["need_train"])
    else:
        return render(
            request, TEMPLATES["model_corrupted"], context={"a": os.listdir()}
        )


def train(request):
    """
    Поддерживаем только одну обучающуюся модель за раз.
    Здесь celery позволит нам сразу не дожидаться выполнения
    задачи, а отправить ее в очередь для выполнения.
    """
    if TRAIN_TASK_ID in os.environ:
        existing_train_task_id = os.environ[TRAIN_TASK_ID]
        existing_train_task = AsyncResult(existing_train_task_id)

        if existing_train_task.state in ["PENDING", "STARTED", "PROGRESS"]:
            return redirect("/")

    train_task = train_model_task.delay()
    os.environ[TRAIN_TASK_ID] = train_task.id

    return redirect("/")


def get_similar(request):
    """
    Так как у нас нигде не фиксируется, что сессия уникальна,
    мы будем сразу же дожидаться результата исполнения таски.
    Здесь celery позволит немного распараллеливать выполнения инференса.
    """
    try:
        url = request.GET["url"]
        cnt = int(request.GET["cnt"])
        response = requests.get(url)
    except Exception as e:
        return render(request, TEMPLATES["error"])
    if response:
        html = bs4.BeautifulSoup(response.text, "html.parser")
        title = html.select("#firstHeading")[0].text
    else:
        context = {"url": url}
        return render(request, TEMPLATES["not_found"], context)
    try:
        page = wikipedia.page(title)
        content = page.content
        title = page.title
    except Exception as e:
        return render(request, TEMPLATES["error"])
    if not os.path.exists(MODEL_PATH) or not os.path.exists(DATA_PATH):
        return render(request, TEMPLATES["need_train"])

    context = get_similar_task.delay(cnt, content, title).get()

    return render(request, TEMPLATES["get_similar"], context)
