import os

BOT_TOKEN = "8922425438:AAHXfPwXmCuV3N5WqbvR7UjUeWpOrKxgrf8"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LETTERS_FOLDER = os.path.join(BASE_DIR, "letters")
CACHE_FILE = os.path.join(BASE_DIR, "file_ids_cache.json")
PHRASE_CACHE_DIR = os.path.join(BASE_DIR, "phrase_cache")

RUSSIAN_LETTERS = [
    "а", "б", "в", "г", "д", "е", "ё", "ж", "з", "и", "й",
    "к", "л", "м", "н", "о", "п", "р", "с", "т", "у", "ф",
    "х", "ц", "ч", "ш", "щ", "ъ", "ы", "ь", "э", "ю", "я"
]
