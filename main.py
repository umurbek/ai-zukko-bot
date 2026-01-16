import os
import io
import sqlite3
from PIL import Image
import telebot
import google.genai as genai
from dotenv import load_dotenv

# ================ LOAD ENV =====================
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
DB_PATH = os.getenv("DB_PATH", "users_history.db")

try:
    HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "10"))
except ValueError:
    HISTORY_LIMIT = 10

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN topilmadi. .env faylni tekshiring.")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY topilmadi. .env faylni tekshiring.")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

# ================ DATABASE =====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS history
        (user_id INTEGER, role TEXT, content TEXT)
    """)
    conn.commit()
    conn.close()

def save_message(user_id: int, role: str, content: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO history VALUES (?, ?, ?)", (user_id, role, content))
    conn.commit()
    conn.close()

def get_history(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # So‘nggi HISTORY_LIMIT xabarni olish uchun DESC; keyin tartibni qaytaramiz
    c.execute(
        "SELECT role, content FROM history WHERE user_id = ? ORDER BY rowid DESC LIMIT ?",
        (user_id, HISTORY_LIMIT)
    )
    rows = c.fetchall()
    conn.close()

    rows.reverse()  # eski -> yangi tartib

    history = []
    for role, content in rows:
        # Gemini chat tarixida role odatda user/model bo‘ladi
        if role == "assistant":
            role = "model"
        history.append({
            "role": role,
            "parts": [{"text": content}]
        })
    return history

# ================ START / HELP =================
@bot.message_handler(commands=['start', 'help'])
def handle_commands(message):
    user_id = message.chat.id
    text = (
        "Salom! Men Zukko Vision botman.\n\n"
        "• Menga matn yuborsangiz — Gemini javob beradi\n"
        "• Rasm yuborsangiz — rasmni tahlil qilaman"
    )
    save_message(user_id, "model", "Suhbat boshlandi")
    bot.reply_to(message, text)

# ================ VISION (PHOTO) ===============
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    bot.send_chat_action(message.chat.id, 'typing')
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    img = Image.open(io.BytesIO(downloaded_file))

    prompt = message.caption if message.caption else "Ushbu rasmda nimalarni ko'ryapsiz?"

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[{"text": prompt}, img]
        )
        text = response.text
        save_message(message.chat.id, "model", text)
    except Exception as e:
        if "RESOURCE_EXHAUSTED" in str(e):
            text = "⚠️ Gemini API quota tugadi. Iltimos, keyinroq urinib ko‘ring yoki billing yoqing."
        else:
            text = f"Rasmni tahlil qilishda xato: {e}"

    bot.reply_to(message, text)

# ================ TEXT CHAT + DB ===============
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    user_id = message.chat.id
    user_input = message.text
    history = get_history(user_id)

    if not history:
        history = [{"role": "model", "parts": [{"text": "Suhbat boshlandi"}]}]

    bot.send_chat_action(user_id, 'typing')

    try:
        chat = client.chats.create(
            model=GEMINI_MODEL,
            history=history
        )
        response = chat.send_message(user_input)
        answer = response.text
    except Exception as e:
        if "RESOURCE_EXHAUSTED" in str(e):
            answer = "⚠️ Gemini API quota tugadi. Iltimos, keyinroq urinib ko‘ring yoki billing yoqing."
        else:
            answer = f"Gemini chat xatosi: {e}"

    save_message(user_id, "user", user_input)
    save_message(user_id, "model", answer)
    bot.reply_to(message, answer)

# ================ RUN ==========================
if __name__ == "__main__":
    init_db()
    print("Zukko-AI Vision + DB ishga tushdi...")
    bot.infinity_polling()
