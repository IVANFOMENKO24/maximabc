import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile

from config import BOT_TOKEN, CACHE_FILE, LETTERS_FOLDER, RUSSIAN_LETTERS

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "messages.db")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def init_db() -> None:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            text TEXT NOT NULL,
            timestamp DATETIME NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            first_seen DATETIME NOT NULL,
            message_count INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def log_message(user_id: int, username: str | None, first_name: str | None, text: str) -> None:
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        cursor.execute("INSERT INTO messages (user_id, username, first_name, text, timestamp) VALUES (?, ?, ?, ?, ?)",
                       (user_id, username, first_name, text, now))

        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE users SET message_count = message_count + 1, username = ?, first_name = ? WHERE user_id = ?",
                           (username, first_name, user_id))
        else:
            cursor.execute("INSERT INTO users (user_id, username, first_name, first_seen, message_count) VALUES (?, ?, ?, ?, 1)",
                           (user_id, username, first_name, now))

        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB error: {e}")


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Не удалось сохранить кэш: {e}")


CACHE = load_cache()


def get_letter_file_path(letter: str) -> str | None:
    possible_names = [
        f"{letter}.mp4",
        f"{letter.upper()}.mp4",
    ]
    for name in possible_names:
        path = os.path.join(LETTERS_FOLDER, name)
        if os.path.isfile(path):
            return path
    return None


@dp.message(CommandStart())
async def command_start_handler(message: types.Message) -> None:
    cached_count = sum(1 for l in RUSSIAN_LETTERS if l in CACHE)
    await message.answer(
        "здарова бродяга, отправь мне любой текст, и я отправлю тебе кружки с буквами, "
        "отрпавишь кенту, пока разраб бота включил ноут. "
        "Если чо первая отправка буквы будет чуть медленне, потом будет быстрее из-за кэша! хехе\n\n"
        f"⚡ В кэше уже: {cached_count} из {len(RUSSIAN_LETTERS)} букв"
    )


@dp.message(Command("stats"))
async def command_stats_handler(message: types.Message) -> None:
    parts = (message.text or "").strip().split()
    if len(parts) < 2 or parts[1] != "56890":
        return

    try:
        await message.delete()
    except Exception:
        pass

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM messages")
        total_messages = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("""
            SELECT text, COUNT(*) as cnt
            FROM messages
            GROUP BY text
            ORDER BY cnt DESC
            LIMIT 10
        """)
        top_words = cursor.fetchall()

        cursor.execute("""
            SELECT first_name, username, message_count
            FROM users
            ORDER BY message_count DESC
            LIMIT 10
        """)
        top_users = cursor.fetchall()

        cursor.execute("""
            SELECT m.first_name, m.username, m.text, m.timestamp
            FROM messages m
            ORDER BY m.timestamp DESC
            LIMIT 15
        """)
        recent = cursor.fetchall()

        conn.close()

        reply = "📊 Статистика бота:\n\n"
        reply += f"👥 Всего пользователей: {total_users}\n"
        reply += f"💬 Всего сообщений: {total_messages}\n\n"

        reply += "🔥 Топ-10 слов/фраз:\n"
        if top_words:
            for i, (text, cnt) in enumerate(top_words, 1):
                display_text = text[:30] + ("..." if len(text) > 30 else "")
                reply += f"{i}. «{display_text}» — {cnt} раз\n"
        else:
            reply += "Пока пусто\n"

        reply += "\n🏆 Топ-10 пользователей:\n"
        if top_users:
            for i, (fname, uname, cnt) in enumerate(top_users, 1):
                name = fname or uname or str("Аноним")
                reply += f"{i}. {name} — {cnt} сообщений\n"
        else:
            reply += "Пока пусто\n"

        reply += "\n🕐 Последние 15 сообщений:\n"
        if recent:
            for i, (fname, uname, text, ts) in enumerate(recent, 1):
                name = fname or uname or "Аноним"
                try:
                    dt = datetime.fromisoformat(ts).strftime("%H:%M")
                except Exception:
                    dt = ts[:5]
                display_text = text[:25] + ("..." if len(text) > 25 else "")
                reply += f"{i}. [{dt}] {name}: «{display_text}»\n"
        else:
            reply += "Пока пусто\n"

        await message.answer(reply)
    except Exception as e:
        logging.error(f"Stats error: {e}")
        try:
            await message.answer(f"Ошибка при получении статистики: {e}")
        except Exception:
            pass


@dp.message()
async def text_handler(message: types.Message) -> None:
    text = message.text or message.caption
    if not text:
        await message.answer("Отправь мне текст!")
        return

    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    first_name = message.from_user.first_name if message.from_user else None

    if not text.startswith("/"):
        log_message(user_id, username, first_name, text)

    if text.startswith("/"):
        return

    text_lower = text.lower()
    tasks = []

    for char in text_lower:
        if char == " ":
            continue
        if char not in RUSSIAN_LETTERS:
            continue
        tasks.append(char)

    if not tasks:
        await message.answer("В тексте не найдено русских букв для отправки.")
        return

    status_msg = await message.answer(f"Подготавливаю {len(tasks)} кружков...")
    cache_changed = False
    success_count = 0

    for idx, letter in enumerate(tasks, start=1):
        try:
            if letter in CACHE:
                await bot.send_video_note(
                    chat_id=message.chat.id,
                    video_note=CACHE[letter]
                )
            else:
                file_path = get_letter_file_path(letter)
                if not file_path:
                    await message.answer(f"⚠️ Файл для буквы '{letter}' не найден в папке!")
                    continue

                input_file = FSInputFile(file_path)
                sent = await bot.send_video_note(
                    chat_id=message.chat.id,
                    video_note=input_file
                )

                if sent.video_note:
                    new_file_id = sent.video_note.file_id
                    CACHE[letter] = new_file_id
                    cache_changed = True
                    logging.info(f"Сохранен file_id для буквы '{letter}': {new_file_id}")

            success_count += 1

            if idx < len(tasks):
                await asyncio.sleep(0.6)

        except Exception as e:
            logging.error(f"Ошибка с буквой '{letter}': {e}")
            await message.answer(f"❌ Ошибка при отправке буквы '{letter}': {e}")

    if cache_changed:
        save_cache(CACHE)

    try:
        await status_msg.edit_text(f"Готово! Отправлено {success_count} из {len(tasks)} кружков.")
    except Exception:
        pass


async def main() -> None:
    init_db()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
