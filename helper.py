import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

from config import BOT_TOKEN

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def command_start_handler(message: types.Message) -> None:
    await message.answer(
        "📥 Helper для получения FILE_ID кружков!\n\n"
        "Просто отправь или перешли мне любой кружок (video note), "
        "и я верну тебе его file_id, который нужно вставить в config.py"
    )


@dp.message()
async def video_note_handler(message: types.Message) -> None:
    if message.video_note:
        file_id = message.video_note.file_id
        await message.answer(
            f"✅ Получен кружок!\n\n"
            f"file_id = `{file_id}`\n\n"
            f"Скопируй это значение в config.py для нужной буквы.",
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Это не кружок! Отправь именно video note (кружок).")


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
