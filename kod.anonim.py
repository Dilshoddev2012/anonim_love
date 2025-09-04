# -*- coding: utf-8 -*-
# Anonim Love bot — VPS uchun
# Kutubxona: pyTelegramBotAPI (telebot) + Gemini (AI javoblari uchun)

import json
import os
import threading
from telebot import TeleBot, types
import google.generativeai as genai

# === Sozlamalar ===
BOT_TOKEN = "7549325175:AAF9teSMeEffbIG3Z0SKfhf1WGHWmYr2Cg8"   # BotFather'dan olgan token
ADMIN_ID = 7661335658        # Admin ID
GEMINI_API_KEY = "AIzaSyADSb9q_JshLD2XfeXAjXHeKWyMgyNwcK8"  # Gemini API kalit

genai.configure(api_key=GEMINI_API_KEY)

# === Doimiylar ===
DB_FILE = "anon_love_db.json"
LOCK = threading.RLock()
partners = {}  # user_id -> partner_id
waiting = {"male": [], "female": []}
admin_state = {}  # admin vaqtinchalik holati

# === Yordamchi funksiyalar ===
def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}}

def save_db(db):
    with LOCK:
        tmp = DB_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DB_FILE)

def get_user(db, uid):
    return db["users"].get(str(uid))

def set_gender(db, uid, gender):
    uid = str(uid)
    if uid not in db["users"]:
        db["users"][uid] = {}
    db["users"][uid]["gender"] = gender
    save_db(db)

def get_gender(db, uid):
    u = get_user(db, uid)
    if not u:
        return None
    return u.get("gender")

def is_in_chat(uid):
    return uid in partners

def end_chat_for(uid, bot: TeleBot, notify=True):
    if uid not in partners:
        return
    partner_id = partners.pop(uid)

    # AI bilan bo‘lsa, faqat foydalanuvchini chiqaramiz
    if partner_id != 0:
        if partners.get(partner_id) == uid:
            partners.pop(partner_id, None)

    if notify:
        try:
            bot.send_message(uid, "Suhbat tugatildi.", reply_markup=main_menu(uid))
        except:
            pass
        if partner_id != 0:
            try:
                bot.send_message(partner_id, "Suhbatdoshingiz chiqib ketdi.", reply_markup=main_menu(partner_id))
            except:
                pass

# === Matching (AI qo‘shilgan) ===
def try_match(user_id, db, bot: TeleBot):
    if is_in_chat(user_id):
        bot.send_message(user_id, "Siz allaqachon suhbatasiz.")
        return
    gender = get_gender(db, user_id)
    if gender not in ("male", "female"):
        ask_gender(bot, user_id)
        return
    preferred = "female" if gender == "male" else "male"
    with LOCK:
        partner_id = None
        if waiting[preferred]:
            partner_id = waiting[preferred].pop(0)
        elif waiting[gender]:
            partner_id = waiting[gender].pop(0)
        else:
            # Agar foydalanuvchi topilmasa — AI qizga ulash
            partner_id = 0
            partners[user_id] = partner_id
            partners[partner_id] = user_id
            bot.send_message(user_id, "Sizga suhbatdosh topildi! 😊 (Shahlo bilan)", reply_markup=chat_menu())
            return

        partners[user_id] = partner_id
        if partner_id != 0:
            partners[partner_id] = user_id

    bot.send_message(user_id, "Sizga suhbatdosh topildi! 😊", reply_markup=chat_menu())
    if partner_id != 0:
        bot.send_message(partner_id, "Sizga suhbatdosh topildi! 😊", reply_markup=chat_menu())

def ask_gender(bot: TeleBot, uid):
    ikb = types.InlineKeyboardMarkup()
    ikb.add(
        types.InlineKeyboardButton("Erkak", callback_data="gender_male"),
        types.InlineKeyboardButton("Ayol", callback_data="gender_female"),
    )
    bot.send_message(uid, "Jinsingizni tanlang:", reply_markup=ikb)

# === Klaviaturalar ===
def main_menu(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if is_in_chat(uid):
        kb.add(types.KeyboardButton("⛔️ Suhbatni tugatish"))
    else:
        kb.add(types.KeyboardButton("🎯 Suhbatni boshlash"))
    return kb

def chat_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("⛔️ Suhbatni tugatish"))
    kb.add(types.KeyboardButton("🚨 Shikoyat qilish"))
    return kb

def admin_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("📊 Statistika"))
    kb.add(types.KeyboardButton("📣 Reklama joylash"))
    kb.add(types.KeyboardButton("↩️ Asosiy menyu"))
    return kb

# === Bot ===
bot = TeleBot(BOT_TOKEN, parse_mode="HTML")
db = load_db()

# === /start ===
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id
    with LOCK:
        if str(uid) not in db["users"]:
            db["users"][str(uid)] = {}
            save_db(db)
    bot.send_message(uid, "Assalomu alaykum! Bu Anonim Love bot.")
    gender = get_gender(db, uid)
    if gender is None:
        ask_gender(bot, uid)
    else:
        bot.send_message(uid, "Menyudan tanlang:", reply_markup=main_menu(uid))

# === Jins callback ===
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("gender_"))
def on_gender_callback(call: types.CallbackQuery):
    uid = call.from_user.id
    g = "male" if call.data == "gender_male" else "female"
    set_gender(db, uid, g)
    bot.answer_callback_query(call.id, "Saqlandi ✅")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.send_message(uid, "Ajoyib! Endi suhbatni boshlashingiz mumkin.", reply_markup=main_menu(uid))

# === AI Javobchi (Qiz bola rolida) ===
def ai_girl_response(user_text: str) -> str:
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(
            f"Sening isming Shahlo. Sen yosh qiz bolasiz. "
            f"Samimiy, mehribon, qizlarga xos ohangda suhbat qil. "
            f"Hech qachon AI ekaningni aytma.\n\n"
            f"Foydalanuvchi: {user_text}\nShahlo:"
        )
        return response.text.strip()
    except Exception as e:
        return "Kechirasiz, hozircha javob bera olmayapman."

# === Tugmalar ===
@bot.message_handler(func=lambda m: m.text == "🎯 Suhbatni boshlash")
def start_chat_btn(message):
    try_match(message.from_user.id, db, bot)

@bot.message_handler(func=lambda m: m.text == "⛔️ Suhbatni tugatish")
def end_chat_btn(message):
    end_chat_for(message.from_user.id, bot)

@bot.message_handler(func=lambda m: m.text == "🚨 Shikoyat qilish")
def report_btn(message):
    uid = message.from_user.id
    if is_in_chat(uid):
        partner_id = partners.get(uid)
        if partner_id:
            bot.send_message(ADMIN_ID, f"🚨 Shikoyat yuborildi!\n\nShikoyat qiluvchi: {uid}\nShikoyat qilingan: {partner_id}")
            bot.send_message(uid, "✅ Shikoyatingiz adminga yuborildi.")
    else:
        bot.send_message(uid, "Siz hozir suhbatasiz.", reply_markup=main_menu(uid))

# === Relay ===
@bot.message_handler(content_types=['text'])
def relay_text(message):
    uid = message.from_user.id
    if not is_in_chat(uid):
        return bot.send_message(uid, "Siz hozir suhbatasiz.", reply_markup=main_menu(uid))
    partner_id = partners.get(uid)
    if not partner_id:
        return
    
    # Agar partner "AI qiz" bo'lsa
    if partner_id == 0:  # AI uchun maxsus ID
        reply = ai_girl_response(message.text)
        bot.send_message(uid, reply)
    else:
        try:
            bot.copy_message(partner_id, message.chat.id, message.message_id)
        except:
            end_chat_for(uid, bot)

# === Run ===
if __name__ == "__main__":
    print("Anonim Love bot VPS’da ishga tushdi...")
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
