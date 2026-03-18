MODEL_PATH = "/app/data/model.pickle"
DATA_PATH = "/app/data/data.npz"

TRAIN_TASK_ID = "train_task_id"
NUM_ARTICLES = "NUM_ARTICLES_TRAIN"

TEMPLATES = {
    "error": f"main/error.html",
    "get_similar": f"main/get_similar.html",
    "index": f"main/index.html",
    "model_corrupted": f"main/model_corrupted.html",
    "need_train": f"main/need_train.html",
    "not_found": f"main/not_found.html",
    "train": f"main/train.html",
    "train_in_progress": f"main/train_in_progress.html",
}

WIKI_CSV_FILE = "/app/wiki_movie_plots_deduped.csv"
