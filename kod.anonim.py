# bot.py  — tozalangan versiya
import os
import time
import sqlite3
from datetime import datetime, timedelta
import threading
import signal
import sys
import logging
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

TOKEN = os.getenv("ANONIM_TOKEN", "7549325175:AAF9teSMeEffbIG3Z0SKfhf1WGHWmYr2Cg8")
ADMIN_ID = int(os.getenv("ANONIM_ADMIN_ID", "7661335658"))
DB_FILE = os.getenv("ANONIM_DB_FILE", "anonim_love2.db")
USERS_TXT = os.getenv("ANONIM_USERS_FILE", "users.txt")

bot = telebot.TeleBot(TOKEN)

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cur = conn.cursor()

def init_db():
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    gender TEXT,
                    joined_at TEXT,
                    muted_until TEXT,
                    slow_mode_until TEXT,
                    preference TEXT DEFAULT 'random',
                    message_count INTEGER DEFAULT 0,
                    last_find_request TEXT
                )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS partners (
                    user_id INTEGER PRIMARY KEY,
                    partner_id INTEGER,
                    connected_at TEXT
                )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reporter_id INTEGER,
                    target_id INTEGER,
                    reason TEXT,
                    created_at TEXT,
                    handled INTEGER DEFAULT 0
                )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS ads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    text TEXT,
                    created_at TEXT
                )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )""")
    conn.commit()

init_db()

message_timestamps = {}
slow_mode = {}
lock = threading.Lock()
admin_states = {}
admin_temp = {}

def now_iso():
    return datetime.utcnow().isoformat()

def save_users_file():
    try:
        cur.execute("SELECT user_id FROM users")
        rows = cur.fetchall()
        with open(USERS_TXT, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(str(r[0]) + "\n")
    except Exception as e:
        logging.exception("save_users_file error: %s", e)

def set_user_gender(user_id, gender):
    ensure_user_row(user_id)
    cur.execute("UPDATE users SET gender=? WHERE user_id=?", (gender, user_id))
    conn.commit()

def ensure_user_row(user_id):
    """Ensure user exists. Returns True if newly created, False otherwise."""
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users(user_id, gender, joined_at, muted_until, slow_mode_until, preference, message_count, last_find_request) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, "", now_iso(), "", "", "random", 0, ""))
        conn.commit()
        # update users file
        save_users_file()
        return True
    return False

def set_user_preference(user_id, pref):
    ensure_user_row(user_id)
    cur.execute("UPDATE users SET preference=? WHERE user_id=?", (pref, user_id))
    conn.commit()

def get_user_preference(user_id):
    ensure_user_row(user_id)
    cur.execute("SELECT preference FROM users WHERE user_id=?", (user_id,))
    r = cur.fetchone()
    return r[0] if r and r[0] else "random"

def get_user(user_id):
    cur.execute("SELECT user_id, gender, joined_at, muted_until, slow_mode_until, preference, message_count, last_find_request FROM users WHERE user_id=?", (user_id,))
    return cur.fetchone()

def connect_partners(a, b):
    cur.execute("INSERT OR REPLACE INTO partners(user_id, partner_id, connected_at) VALUES (?, ?, ?)", (a, b, now_iso()))
    cur.execute("INSERT OR REPLACE INTO partners(user_id, partner_id, connected_at) VALUES (?, ?, ?)", (b, a, now_iso()))
    conn.commit()

def disconnect_user(u):
    cur.execute("DELETE FROM partners WHERE user_id=?", (u,))
    conn.commit()

def get_partner(u):
    cur.execute("SELECT partner_id FROM partners WHERE user_id=?", (u,))
    r = cur.fetchone()
    return r[0] if r else None

def add_report(reporter, target, reason):
    cur.execute("INSERT INTO reports(reporter_id, target_id, reason, created_at) VALUES (?, ?, ?, ?)",
                (reporter, target, reason, now_iso()))
    conn.commit()
    rid = cur.lastrowid
    notify_admin_report(rid, reporter, target, reason)
    return rid

def get_reports(limit=50):
    cur.execute("SELECT id, reporter_id, target_id, reason, created_at, handled FROM reports ORDER BY id DESC LIMIT ?", (limit,))
    return cur.fetchall()

def save_ad(admin_id, text):
    cur.execute("INSERT INTO ads(admin_id, text, created_at) VALUES (?, ?, ?)", (admin_id, text, now_iso()))
    conn.commit()
    return cur.lastrowid

def get_all_user_ids():
    cur.execute("SELECT user_id FROM users")
    return [r[0] for r in cur.fetchall()]

def increment_message_count(user_id):
    cur.execute("UPDATE users SET message_count = COALESCE(message_count,0)+1 WHERE user_id=?", (user_id,))
    conn.commit()

def set_last_find_request(user_id):
    ensure_user_row(user_id)
    cur.execute("UPDATE users SET last_find_request=? WHERE user_id=?", (now_iso(), user_id))
    conn.commit()

def get_unmatched_users_within(hours=24):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    cutoff_iso = cutoff.isoformat()
    cur.execute("SELECT user_id, last_find_request FROM users WHERE last_find_request>? AND user_id NOT IN (SELECT user_id FROM partners)", (cutoff_iso,))
    return cur.fetchall()

def meta_set(key, value):
    cur.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
    conn.commit()

def meta_get(key):
    cur.execute("SELECT value FROM meta WHERE key=?", (key,))
    r = cur.fetchone()
    return r[0] if r else None

def register_message_timestamp(user_id):
    ts = time.time()
    with lock:
        arr = message_timestamps.get(user_id, [])
        arr.append(ts)
        arr = [t for t in arr if ts - t <= 10]
        message_timestamps[user_id] = arr
        recent = [t for t in arr if ts - t <= 3]
        if len(recent) >= 5:
            until = datetime.utcnow() + timedelta(minutes=30)
            slow_mode[user_id] = until
            cur.execute("UPDATE users SET slow_mode_until=? WHERE user_id=?", (until.isoformat(), user_id))
            conn.commit()
            return True
        return False

def is_in_slow_mode(user_id):
    with lock:
        if user_id in slow_mode:
            if datetime.utcnow() < slow_mode[user_id]:
                return True
            else:
                del slow_mode[user_id]
                cur.execute("UPDATE users SET slow_mode_until=? WHERE user_id=?", ("", user_id))
                conn.commit()
                return False
        row = get_user(user_id)
        if row and row[4]:
            try:
                until = datetime.fromisoformat(row[4])
                if datetime.utcnow() < until:
                    slow_mode[user_id] = until
                    return True
            except:
                return False
        return False

def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🔎 Juft topish", "🔧 Sozlamalar")
    kb.row("❗ Shikoyat", "ℹ️ Yordam")
    return kb

def gender_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("👤 Men erkakman", "👩 Men ayolman")
    kb.row("🔙 Bekor qilish")
    return kb

def in_chat_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    kb.row("🔚 Suhbatni yakunlash", "❗ Shikoyat")
    return kb

def settings_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("👩 Faqat ayol", "👤 Faqat erkak")
    kb.row("🔀 Random", "🔄 Jinsni o‘zgartirish")
    kb.row("🔙 Orqaga")
    return kb

def admin_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📊 Statistika", "📝 Shikoyatlar")
    kb.row("📋 Juft topolmaganlar", "📣 Reklama")
    kb.row("☎ AdminCall", "🔙 Orqaga")
    return kb

def notify_admin_report(rid, reporter, target, reason):
    try:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔇 Mute 3 kun", callback_data=f"mute3_{rid}_{target}"))
        kb.add(types.InlineKeyboardButton("⛔ Ban", callback_data=f"ban_{rid}_{target}"))
        kb.add(types.InlineKeyboardButton("✅ Mark handled", callback_data=f"handled_{rid}"))
        txt = f"Yangi shikoyat (id={rid})\nFrom: {reporter}\nTarget: {target}\nSabab: {reason}"
        bot.send_message(ADMIN_ID, txt, reply_markup=kb)
    except Exception as e:
        logging.exception("notify_admin_report error: %s", e)

@bot.message_handler(commands=['start'])
def handle_start(m):
    user_id = m.from_user.id
    ensure_user_row(user_id)
    row = get_user(user_id)
    if not row or not row[1]:
        bot.send_message(user_id, "Anonim Love ga xush kelibsiz! Sizning jinsingizni tanlang:", reply_markup=gender_kb())
    else:
        bot.send_message(user_id, "Xush kelibsiz! Asosiy menyu:", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text in ["👤 Men erkakman", "👩 Men ayolman"])
def handle_gender(m):
    user_id = m.from_user.id
    g = "male" if m.text == "👤 Men erkakman" else "female"
    set_user_gender(user_id, g)
    bot.send_message(user_id, "Siz muvaffaqiyatli ro'yxatdan o'tdingiz. Asosiy menyuga qayting.", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "🔧 Sozlamalar")
def handle_settings(m):
    ensure_user_row(m.from_user.id)
    bot.send_message(m.chat.id, "Sozlamalarni tanlang:", reply_markup=settings_kb())

@bot.message_handler(func=lambda m: m.text in ["👩 Faqat ayol", "👤 Faqat erkak", "🔀 Random"])
def handle_pref_change(m):
    user_id = m.from_user.id
    if m.text == "👩 Faqat ayol":
        set_user_preference(user_id, "female")
        bot.send_message(user_id, "✅ Endi faqat ayol foydalanuvchilar bilan bog‘lanasiz.", reply_markup=main_menu())
    elif m.text == "👤 Faqat erkak":
        set_user_preference(user_id, "male")
        bot.send_message(user_id, "✅ Endi faqat erkak foydalanuvchilar bilan bog‘lanasiz.", reply_markup=main_menu())
    else:
        set_user_preference(user_id, "random")
        bot.send_message(user_id, "✅ Endi random rejimda juft tanlanadi.", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "🔎 Juft topish")
def handle_find(m):
    user_id = m.from_user.id
    row = get_user(user_id)
    if not row or not row[1]:
        bot.send_message(user_id, "Avvalo jinsingizni tanlang.", reply_markup=gender_kb())
        return
    my_gender = row[1]
    pref = get_user_preference(user_id)
    set_last_find_request(user_id)
    if pref == "female":
        cur.execute("SELECT user_id FROM users WHERE user_id!=? AND user_id NOT IN (SELECT user_id FROM partners) AND gender='female' LIMIT 1", (user_id,))
    elif pref == "male":
        cur.execute("SELECT user_id FROM users WHERE user_id!=? AND user_id NOT IN (SELECT user_id FROM partners) AND gender='male' LIMIT 1", (user_id,))
    else:
        cur.execute("SELECT user_id FROM users WHERE user_id!=? AND user_id NOT IN (SELECT user_id FROM partners) AND gender!=? LIMIT 1", (user_id, my_gender))
    r = cur.fetchone()
    desired = r[0] if r else None
    if not desired:
        cur.execute("SELECT user_id FROM users WHERE user_id!=? AND user_id NOT IN (SELECT user_id FROM partners) LIMIT 1", (user_id,))
        rr = cur.fetchone()
        if rr:
            desired = rr[0]
    if desired:
        connect_partners(user_id, desired)
        bot.send_message(user_id, "🎉 Sizga juft topildi. Endi anonim chat boshlanadi.", reply_markup=in_chat_kb())
        bot.send_message(desired, "🎉 Sizga juft topildi. Endi anonim chat boshlanadi.", reply_markup=in_chat_kb())
        try:
            bot.send_message(ADMIN_ID, f"Juftlik: {user_id} <-> {desired} (anonim)")
        except:
            pass
    else:
        bot.send_message(user_id, "Hozircha mos foydalanuvchi topilmadi. Keyinroq urinib ko'ring.")

@bot.message_handler(func=lambda m: m.text == "🔚 Suhbatni yakunlash")
def handle_leave(m):
    user_id = m.from_user.id
    partner = get_partner(user_id)
    if partner:
        disconnect_user(user_id)
        disconnect_user(partner)
        bot.send_message(user_id, "Suhbat yakunlandi.", reply_markup=main_menu())
        try:
            bot.send_message(partner, "Suhbat yakunlandi. Asosiy menyuga qaytish.", reply_markup=main_menu())
        except:
            pass
    else:
        bot.send_message(user_id, "Siz hozir hech kim bilan bog'lanmagansiz.", reply_markup=main_menu())

@bot.message_handler(commands=['report'])
def handle_report_cmd(m):
    user_id = m.from_user.id
    args = m.text.split(" ", 1)
    reason = args[1] if len(args) > 1 else ""
    partner = get_partner(user_id)
    if not partner:
        bot.send_message(user_id, "Siz hozir hech kim bilan bog'lanmagansiz, shikoyat yuborish uchun partneringiz bo'lishi kerak.")
        return
    if not reason:
        bot.send_message(user_id, "Iltimos, shikoyat sababini yozing: /report sabab")
        return
    rid = add_report(user_id, partner, reason)
    bot.send_message(user_id, "Shikoyatingiz qabul qilindi. Admin ko'rib chiqadi.")

@bot.message_handler(func=lambda m: m.text == "❗ Shikoyat")
def handle_report_menu(m):
    user_id = m.from_user.id
    partner = get_partner(user_id)
    if not partner:
        bot.send_message(user_id, "Siz hozir hech kim bilan bog'lanmagansiz, shikoyat yuborish uchun suhbatda bo'ling.")
        return
    msg = bot.send_message(user_id, "Shikoyatingizni yozing. (Juda ogʻir yoki xavfli xabar bo'lsa tavsif bilan yozing.)")
    bot.register_next_step_handler(msg, process_report_text, partner)

def process_report_text(m, partner):
    reporter = m.from_user.id
    reason = m.text
    rid = add_report(reporter, partner, reason)
    bot.send_message(reporter, "Shikoyatingiz qabul qilindi. Admin ko'rib chiqadi.")

@bot.message_handler(commands=['admin'])
def admin_panel(m):
    user_id = m.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(user_id, "Bu buyruq faqat admin uchun.")
        return
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM partners")
    pairs = cur.fetchone()[0] // 2
    rep_count = cur.execute("SELECT COUNT(*) FROM reports WHERE handled=0").fetchone()[0]
    bot.send_message(user_id, f"Admin panel:\nFoydalanuvchilar: {total}\nFaol juftliklar: {pairs}\nKo'rilmagan shikoyatlar: {rep_count}", reply_markup=admin_kb())

@bot.message_handler(func=lambda m: m.text == "📝 Shikoyatlar")
def admin_reports(m):
    if m.from_user.id != ADMIN_ID:
        return
    reps = get_reports(50)
    if not reps:
        bot.send_message(ADMIN_ID, "Hozircha shikoyat yo'q.")
        return
    for r in reps:
        rid, reporter, target, reason, created_at, handled = r
        txt = f"ID:{rid}\nFrom:{reporter}\nTarget:{target}\nTime:{created_at}\nHandled:{handled}\nReason:{reason}"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔇 Mute 3 kun", callback_data=f"mute3_{rid}_{target}"))
        kb.add(types.InlineKeyboardButton("⛔ Ban", callback_data=f"ban_{rid}_{target}"))
        kb.add(types.InlineKeyboardButton("✅ Mark handled", callback_data=f"handled_{rid}"))
        bot.send_message(ADMIN_ID, txt, reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "📋 Juft topolmaganlar")
def admin_unmatched(m):
    if m.from_user.id != ADMIN_ID:
        return
    last_update = meta_get("unmatched_last_update")
    if last_update:
        try:
            last_dt = datetime.fromisoformat(last_update)
            if datetime.utcnow() - last_dt < timedelta(hours=24):
                # still allowed to show cached result; but update timestamp anyway
                pass
        except:
            pass
    meta_set("unmatched_last_update", now_iso())
    unmatched = get_unmatched_users_within(24)
    if not unmatched:
        bot.send_message(ADMIN_ID, "Oxirgi 24 soatda juft topishga urinib, lekin topa olmagan foydalanuvchi yo'q.")
        return
    for u, t in unmatched:
        txt = f"ID: {u}\nOxirgi urinish: {t}"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("☎ Call user", callback_data=f"admincall_{u}"))
        bot.send_message(ADMIN_ID, txt, reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "📣 Reklama")
def admin_ad_start(m):
    if m.from_user.id != ADMIN_ID:
        return
    admin_states[ADMIN_ID] = {"action": "awaiting_ad_text"}
    bot.send_message(ADMIN_ID, "Reklama matnini yuboring. (Yuborganingizdan so'ng reklama hozircha tasdiqsiz barcha foydalanuvchilarga jo'natiladi.)")

@bot.message_handler(func=lambda m: m.text == "📊 Statistika")
def admin_stats(m):
    if m.from_user.id != ADMIN_ID:
        return
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM partners")
    pairs = cur.fetchone()[0] // 2
    rep_count = cur.execute("SELECT COUNT(*) FROM reports WHERE handled=0").fetchone()[0]
    cur.execute("SELECT user_id, message_count FROM users ORDER BY message_count DESC LIMIT 3")
    top3 = cur.fetchall()
    top_text = ""
    for i, row in enumerate(top3, start=1):
        uid, cnt = row
        top_text += f"{i}. {uid} ({cnt})\n"
    if not top_text:
        top_text = "Hozircha activity yo'q."
    bot.send_message(ADMIN_ID, f"Statistika:\nFoydalanuvchilar: {total}\nFaol juftliklar: {pairs}\nKo'rilmagan shikoyatlar: {rep_count}\n\nTop 3 chatters:\n{top_text}", reply_markup=admin_kb())

@bot.message_handler(func=lambda m: m.text == "☎ AdminCall")
def admin_call_start(m):
    if m.from_user.id != ADMIN_ID:
        return
    admin_states[ADMIN_ID] = {"action": "admincall_ask_id"}
    bot.send_message(ADMIN_ID, "Foydalanuvchi ID sini kiriting (masalan: 123456789):")

@bot.callback_query_handler(func=lambda c: c.data is not None)
def admin_cb(c):
    data = c.data
    uid = c.from_user.id
    if uid != ADMIN_ID:
        bot.answer_callback_query(c.id, "Bu tugma faqat admin uchun.")
        return
    if data.startswith("mute3_"):
        parts = data.split("_")
        if len(parts) >= 3:
            try:
                target = int(parts[2])
                until = datetime.utcnow() + timedelta(days=3)
                cur.execute("UPDATE users SET muted_until=? WHERE user_id=?", (until.isoformat(), target))
                conn.commit()
                bot.answer_callback_query(c.id, "Target 3 kunga mute qilindi.")
                try:
                    bot.send_message(target, "Siz 3 kunga moderator tomonidan mute qilindingiz. Agar izoh bermoqchi bo'lsangiz admin bilan bog'laning.")
                except:
                    pass
            except:
                bot.answer_callback_query(c.id, "Xato target ID.")
    elif data.startswith("ban_"):
        parts = data.split("_")
        if len(parts) >= 3:
            try:
                target = int(parts[2])
                cur.execute("DELETE FROM users WHERE user_id=?", (target,))
                cur.execute("DELETE FROM partners WHERE user_id=?", (target,))
                conn.commit()
                save_users_file()
                bot.answer_callback_query(c.id, f"ID {target} ban qilindi (deleted).")
            except:
                bot.answer_callback_query(c.id, "Xato ban operatsiyasi.")
    elif data.startswith("handled_"):
        try:
            rid = int(data.split("_")[1])
            cur.execute("UPDATE reports SET handled=1 WHERE id=?", (rid,))
            conn.commit()
            bot.answer_callback_query(c.id, f"Shikoyat ID={rid} ko'rib chiqildi.")
        except:
            bot.answer_callback_query(c.id, "Xato.")
    elif data.startswith("admincall_"):
        parts = data.split("_")
        if len(parts) >= 2:
            try:
                target = int(parts[1])
                admin_states[ADMIN_ID] = {"action": "admincall_ask_msg", "target": target}
                bot.send_message(ADMIN_ID, f"Siz {target} uchun xabar yozing (keyin tasdiqlaysiz):")
                bot.answer_callback_query(c.id, "Foydalanuvchi uchun xabar yozing.")
            except:
                bot.answer_callback_query(c.id, "Xato target ID.")
    else:
        bot.answer_callback_query(c.id, "Noma'lum tugma.")

@bot.message_handler(func=lambda m: True, content_types=['text'])
def relay_or_handle(m):
    user_id = m.from_user.id
    text = m.text.strip() if m.text else ""

    # Admin flows
    if user_id == ADMIN_ID and user_id in admin_states:
        st = admin_states[user_id]
        if st.get("action") == "awaiting_ad_text":
            ad_text = text
            if not ad_text:
                bot.send_message(ADMIN_ID, "Bo'sh reklama matni qabul qilinmaydi. Iltimos matn yuboring yoki /start bilan qaytib admin menyuga.")
                return
            save_ad(ADMIN_ID, ad_text)
            uids = get_all_user_ids()
            sent = 0
            for uid in uids:
                try:
                    bot.send_message(uid, f"📣 Reklama:\n\n{ad_text}")
                    sent += 1
                except:
                    pass
            bot.send_message(ADMIN_ID, f"Reklama yuborildi. Foydalanuvchilar soni (taxmin): {sent}", reply_markup=admin_kb())
            admin_states.pop(ADMIN_ID, None)
            return
        if st.get("action") == "admincall_ask_id":
            try:
                target = int(text)
                cur.execute("SELECT 1 FROM users WHERE user_id=?", (target,))
                if not cur.fetchone():
                    bot.send_message(ADMIN_ID, f"❌ ID {target} foydalanuvchi bazada topilmadi.")
                    return
                admin_states[user_id] = {"action": "admincall_ask_msg", "target": target}
                bot.send_message(ADMIN_ID, f"Endi {target} ga yuboriladigan xabarni yozing:")
            except:
                bot.send_message(ADMIN_ID, "Iltimos to'g'ri numeric ID kiriting.")
            return
        if st.get("action") == "admincall_ask_msg":
            tgt = st.get("target")
            admin_temp["admincall_msg"] = text
            admin_states[user_id] = {"action": "admincall_confirm", "target": tgt}
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("✅ Tasdiqlash va yuborish", callback_data="admincall_send"))
            kb.add(types.InlineKeyboardButton("❌ Bekor qilish", callback_data="admincall_cancel"))
            bot.send_message(ADMIN_ID, f"ID: {tgt}\nXabar:\n\n{text}\n\nTasdiqlaysizmi?", reply_markup=kb)
            return
        if st.get("action") == "admincall_confirm":
            bot.send_message(ADMIN_ID, "Iltimos inline tugmalardan foydalaning (tasdiqlash yoki bekor qilish).")
            return

    # rate limiting
    slow_enabled_now = register_message_timestamp(user_id)
    if slow_enabled_now:
        bot.send_message(user_id, "Siz juda tez xabar yubordingiz — 30 daqiqalik slow-mode o'rnatildi. Keyinroq davom eting.")
        return
    if is_in_slow_mode(user_id):
        bot.send_message(user_id, "Siz slow-mode ostidasiz: xabarlar 3 soniyali kechikish bilan jo'natiladi. Iltimos sabr qiling.")
        time.sleep(3)

    # muted check
    row = get_user(user_id)
    if row and row[3]:
        try:
            muted_until = row[3]
            if muted_until:
                until_dt = datetime.fromisoformat(muted_until)
                if datetime.utcnow() < until_dt:
                    bot.send_message(user_id, f"Siz moderator tomonidan mute qilingan. Mute tugaguncha xabar yuborolmaysiz.")
                    return
        except:
            pass

    # admin back buttons
    if user_id == ADMIN_ID and text == "🔙 Orqaga":
        admin_states.pop(ADMIN_ID, None)
        bot.send_message(ADMIN_ID, "Admin menu:", reply_markup=admin_kb())
        return
    if text == "🔙 Orqaga":
        bot.send_message(user_id, "Asosiy menyuga qaytildi.", reply_markup=main_menu())
        return

    partner = get_partner(user_id)
    if partner:
        try:
            increment_message_count(user_id)
            increment_message_count(partner)
            bot.send_message(partner, f"{text}", reply_markup=in_chat_kb())
            bot.send_message(user_id, "Xabar yuborildi.", reply_markup=in_chat_kb())
        except Exception as e:
            bot.send_message(user_id, "Xato: xabarni yuborib bo'lmadi. Ehtimol suhbatdosh botni bloklagan yoki yo'qolgan.")
    else:
        # admin quick text commands when not in chat
        if user_id == ADMIN_ID:
            if text == "📊 Statistika":
                cur.execute("SELECT COUNT(*) FROM users")
                total = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM partners")
                pairs = cur.fetchone()[0] // 2
                rep_count = cur.execute("SELECT COUNT(*) FROM reports WHERE handled=0").fetchone()[0]
                cur.execute("SELECT user_id, message_count FROM users ORDER BY message_count DESC LIMIT 3")
                top3 = cur.fetchall()
                top_text = ""
                for i, row2 in enumerate(top3, start=1):
                    uid, cnt = row2
                    top_text += f"{i}. {uid} ({cnt})\n"
                if not top_text:
                    top_text = "Hozircha activity yo'q."
                bot.send_message(ADMIN_ID, f"Statistika:\nFoydalanuvchilar: {total}\nFaol juftliklar: {pairs}\nKo'rilmagan shikoyatlar: {rep_count}\n\nTop 3 chatters:\n{top_text}", reply_markup=admin_kb())
                return
            if text == "📝 Shikoyatlar":
                admin_reports(m)
                return
            if text == "📋 Juft topolmaganlar":
                admin_unmatched(m)
                return
            if text == "📣 Reklama":
                admin_ad_start(m)
                return
            if text == "☎ AdminCall":
                admin_call_start(m)
                return
        bot.send_message(user_id, "Asosiy menyu:", reply_markup=main_menu())

def stop_bot(signum, frame):
    logging.info("Signal %s received, stopping bot...", signum)
    try:
        bot.stop_polling()
    except:
        pass
    try:
        conn.close()
    except:
        pass
    logging.info("Bot stopped.")
    sys.exit(0)

signal.signal(signal.SIGINT, stop_bot)
signal.signal(signal.SIGTERM, stop_bot)

if __name__ == "__main__":
    logging.info("Anonim Love 2 prototype bot ishga tushmoqda...")
    try:
        # safer call - don't pass unfamiliar kwargs that may not exist in some telebot versions
        bot.infinity_polling(timeout=60)
    except TypeError:
        # fallback to simple polling if signature mismatches
        try:
            bot.infinity_polling()
        except Exception as e:
            logging.exception("Bot error: %s", e)
            time.sleep(5)
            raise
    except Exception as e:
        logging.exception("Bot error: %s", e)
        time.sleep(5)
        raise
