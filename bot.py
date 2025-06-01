import os
import logging
from typing import Optional
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ChatMemberOwner, ChatMemberAdministrator
from aiogram.filters import CommandStart
from langdetect import detect
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_NAME = "google/gemini-2.0-flash-exp:free"

HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json"
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

blocked_users = set()

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "Bot is running"}), 200

def analyze_content(text: str) -> dict:
    print(f"[DEBUG] Анализируем текст: {text}")
    prompt = (
        "Проанализируй это сообщение на наличие:\n"
        "- Мата или нецензурной лексики\n"
        "- Рекламы или спама\n"
        "- Приглашений в сторонние каналы, чаты, группы\n"
        "Ответ должен быть строго в формате JSON:\n"
        "{\n"
        "  \"contains_prohibited\": true/false,\n"
        "  \"reason\": \"причина блокировки\",\n"
        "  \"language\": \"язык сообщения\"\n"
        "}\n"
        "Текст для проверки: "
        f"{text}"
    )

    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 200
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=HEADERS, json=payload)
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        analysis = eval(content)
        print(f"[DEBUG] Результат анализа: {analysis}")
        return analysis
    except Exception as e:
        print(f"[ERROR] Ошибка при анализе текста: {e}")
        return {"contains_prohibited": False, "reason": "Ошибка анализа", "language": "unknown"}

async def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return isinstance(member, (ChatMemberOwner, ChatMemberAdministrator))
    except Exception as e:
        print(f"[ERROR] Не удалось проверить админа: {e}")
        return False

@dp.message()
async def log_all_messages(message: Message):
    print(f"[DEBUG] Получено сообщение от {message.from_user.id}: {message.text or '[не текстовое сообщение]'}")

@dp.message(F.text)
async def handle_message(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text

    print(f"[INFO] Обработка сообщения от {user_id} в чате {chat_id}: {text}")

    if await is_admin(chat_id, user_id):
        print(f"[INFO] Пользователь {user_id} — администратор. Пропускаем.")
        return

    if user_id in blocked_users:
        print(f"[INFO] Пользователь {user_id} уже заблокирован. Удаляем сообщение.")
        await message.delete()
        return

    analysis = analyze_content(text)

    if analysis["contains_prohibited"]:
        print(f"[ACTION] Нарушение найдено. Блокируем пользователя {user_id}. Причина: {analysis['reason']}")
        try:
            await message.delete()
            await bot.ban_chat_member(chat_id, user_id)
            reason = analysis["reason"]
            lang = analysis["language"]
            await bot.send_message(
                chat_id,
                f"🚫 Пользователь {user_id} был заблокирован.\n"
                f"Причина: {reason} ({lang})"
            )
            blocked_users.add(user_id)
        except Exception as e:
            print(f"[ERROR] Не удалось заблокировать пользователя: {e}")
            await bot.send_message(chat_id, "⚠️ Не удалось заблокировать пользователя.")
    else:
        print(f"[INFO] Сообщение безопасно.")

@dp.message(CommandStart())
async def start(message: Message):
    print(f"[INFO] Получена команда /start от {message.from_user.id}")
    await message.answer("Привет! Я бот-модератор. Я буду следить за порядком в чате.")

async def run_bot():
    await dp.start_polling(bot)

if __name__ == "__main__":
    from threading import Thread
    import asyncio

    def run_flask():
        port = int(os.getenv("PORT", 10000))
        app.run(host="0.0.0.0", port=port)

    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    print("[BOOT] Запуск Telegram-бота...")
    asyncio.run(run_bot())
