import os
import sys


def _load_env_file() -> None:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


_load_env_file()

BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8922425438:AAHXfPwXmCuV3N5WqbvR7UjUeWpOrKxgrf8"

if not BOT_TOKEN:
    print(
        "❌ BOT_TOKEN не задан.\n"
        "   Варианты:\n"
        "   1) Создай файл .env в корне проекта и пропиши:  BOT_TOKEN=твой_токен\n"
        "   2) Или задай переменную окружения:  export BOT_TOKEN=твой_токен   (Linux/macOS)\n"
        "                                      $env:BOT_TOKEN='твой_токен'   (PowerShell)\n"
        "   Токен получаешь у @BotFather в Telegram.",
        file=sys.stderr,
    )
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LETTERS_FOLDER = os.path.join(BASE_DIR, "letters")
CACHE_FILE = os.path.join(BASE_DIR, "file_ids_cache.json")
PHRASE_CACHE_DIR = os.path.join(BASE_DIR, "phrase_cache")

FFMPEG_PATH = os.environ.get("FFMPEG_PATH") or None

RUSSIAN_LETTERS = [
    "а", "б", "в", "г", "д", "е", "ё", "ж", "з", "и", "й",
    "к", "л", "м", "н", "о", "п", "р", "с", "т", "у", "ф",
    "х", "ц", "ч", "ш", "щ", "ъ", "ы", "ь", "э", "ю", "я"
]
