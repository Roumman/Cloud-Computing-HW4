import os
from heapq import heappush, heappop
import pickle

from celery import shared_task
from sklearn.feature_extraction.text import TfidfVectorizer
import scipy.sparse
import pandas as pd

from main import MODEL_PATH, DATA_PATH, NUM_ARTICLES, WIKI_CSV_FILE
from main.models import Article
from review2.celery import celery_app


@shared_task
def train_model_task():
    Article.objects.all().delete()

    max_articles_train = int(os.environ.get(NUM_ARTICLES, 1000))
    data = pd.read_csv(WIKI_CSV_FILE).sample(max_articles_train)
    text_corpus = list(data.Plot)

    articles = [
        Article(
            number=i,
            title=data.iloc[i].Title[:100],
            url=data.iloc[i]["Wiki Page"][:100],
            summary=data.iloc[i].Plot[:4000],
        )
        for i in range(data.shape[0])
    ]

    Article.objects.bulk_create(articles)

    model = TfidfVectorizer(
        analyzer="word", stop_words="english", strip_accents="ascii"
    )
    param_matrix = model.fit_transform(text_corpus)

    if os.path.exists(MODEL_PATH):
        os.remove(MODEL_PATH)

    if os.path.exists(DATA_PATH):
        os.remove(DATA_PATH)

    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)

    scipy.sparse.save_npz(DATA_PATH, param_matrix)


@celery_app.task
def get_similar_task(cnt, content, title):

    with open(MODEL_PATH, "rb") as model_file:
        model = pickle.load(model_file)
    data = scipy.sparse.load_npz(DATA_PATH)
    film_summary_vector = model.transform([content]).toarray()
    row_number = 0
    top = []
    for row in data:
        vec = row.toarray()
        dist = scipy.spatial.distance.euclidean(
            vec.reshape(-1), film_summary_vector.reshape(-1)
        )
        heappush(top, (-dist, row_number))
        if len(top) > cnt:
            heappop(top)
        row_number += 1

    top = sorted(top, reverse=True)

    films = []
    for dist, num in top:
        film = Article.objects.filter(number=num).first()
        films.append({"url": film.url, "title": film.title, "summary": film.summary})

    context = {"films": films, "query_film": title}
    return context
