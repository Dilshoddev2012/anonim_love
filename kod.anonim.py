# -*- coding: utf-8 -*-

# Anonim Love bot — PythonAnywhere uchun moslangan kod
# Kutubxona: pyTelegramBotAPI (telebot)
# Muallif: ChatGPT (sozlash: foydalanuvchi talablari bo‘yicha)

import json
import os
import threading
from telebot import TeleBot, types

# === Bot sozlamalari ===
BOT_TOKEN = "8356760594:AAFjk8-NI1p3EsWe5xCkB57gt8M3f8Fodq8"   # <-- O'zingizning tokeningizni kiriting
ADMIN_ID = 7661335658          # <-- Admin ID

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
    if partners.get(partner_id) == uid:
        partners.pop(partner_id, None)
    if notify:
        try:
            bot.send_message(uid, "Suhbat tugatildi.", reply_markup=main_menu(uid))
        except:
            pass
        try:
            bot.send_message(partner_id, "Suhbatdoshingiz chiqib ketdi.", reply_markup=main_menu(partner_id))
        except:
            pass

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
            waiting[gender].append(user_id)
            bot.send_message(user_id, "Mos suhbatdosh qidirilmoqda...")
            return

        partners[user_id] = partner_id
        partners[partner_id] = user_id

    bot.send_message(user_id, "Sizga suhbatdosh topildi! 😊", reply_markup=chat_menu())
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

# === Admin ===
@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "Faqat admin uchun.")
    bot.send_message(message.chat.id, "Admin paneli:", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == "📊 Statistika")
def admin_stats(message):
    total = len(db.get("users", {}))
    males = sum(1 for u in db["users"].values() if u.get("gender") == "male")
    females = sum(1 for u in db["users"].values() if u.get("gender") == "female")
    pairs = len({min(a, b) for a, b in partners.items() if partners.get(b) == a})
    bot.reply_to(message, f"Statistika:\nJami: {total}\nErkak: {males}\nAyol: {females}\nFaol juftliklar: {pairs}")

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == "📣 Reklama joylash")
def admin_broadcast_prompt(message):
    admin_state[message.from_user.id] = "broadcast_wait"
    bot.reply_to(message, "Reklama xabarini yuboring.")

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and admin_state.get(m.from_user.id) == "broadcast_wait", content_types=['text','photo','video','document','audio','voice','sticker','animation'])
def admin_broadcast_do(message):
    admin_state.pop(message.from_user.id, None)
    users = list(db.get("users", {}).keys())
    sent, failed = 0, 0
    for uid_str in users:
        try:
            bot.copy_message(int(uid_str), message.chat.id, message.message_id)
            sent += 1
        except:
            failed += 1
            continue
    bot.send_message(message.chat.id, f"Tayyor ✅\nYuborildi: {sent}\nXato: {failed}")

# === Tugmalar ===
@bot.message_handler(func=lambda m: m.text == "🎯 Suhbatni boshlash")
def start_chat_btn(message):
    try_match(message.from_user.id, db, bot)

@bot.message_handler(func=lambda m: m.text == "⛔️ Suhbatni tugatish")
def end_chat_btn(message):
    end_chat_for(message.from_user.id, bot)

# === Relay ===
@bot.message_handler(content_types=['text','photo','video','document','audio','voice','sticker','animation'])
def relay_all(message):
    uid = message.from_user.id
    if not is_in_chat(uid):
        return bot.send_message(uid, "Siz hozir suhbatasiz.", reply_markup=main_menu(uid))
    partner_id = partners.get(uid)
    if not partner_id:
        return
    try:
        bot.copy_message(partner_id, message.chat.id, message.message_id)
    except:
        end_chat_for(uid, bot)

# === Run ===
if __name__ == "__main__":
    print("Anonim Love bot PythonAnywhere’da ishga tushdi...")
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)