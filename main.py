# main.py
import asyncio
import json
import os
import random
import sys
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import BOT_TOKEN, ADMIN_ID, DATA_FOLDER, SCORE_FILE

TURN_TIMEOUT = 90

def qpath(name):
    return os.path.join(DATA_FOLDER, name) if DATA_FOLDER else name

FILES = {
    "truth_boy": qpath("truth_boys.txt"),
    "truth_girl": qpath("truth_girls.txt"),
    "dare_boy": qpath("dare_boys.txt"),
    "dare_girl": qpath("dare_girls.txt"),
}

STATE_PATH = "state.json"

def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"games": {}, "scores": {}}
    return {"games": {}, "scores": {}}

def save_state(s):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

state = load_state()

def ensure_question_files():
    samples = {
        "truth_boy": [
            "برای اینکه جذاب به نظر برسی چه کار می‌کنی؟",
            "در حال حاضر از کی خوشت میاد؟",
            "تا به حال عاشق شدی؟",
        ],
        "truth_girl": [
            "دوست داری چند تا بچه داشته باشی؟",
            "اولین عشقت کی بود؟",
            "چه چیزی در مورد من رو دوست داری؟",
        ],
        "dare_boy": [
            "یک آهنگ کوتاه بخون",
            "تا یک دقیقه ادا و شکل یک حیوان رو دربیار",
            "اسم یکی از کراش‌هات رو با صدای بلند بگو",
        ],
        "dare_girl": [
            "یک شعر یا آهنگ بخون",
            "یک راز کوچک بگو",
            "یک عکس خنده‌دار از گالری بفرست",
        ],
    }
    for key, path in FILES.items():
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(samples.get(key, ["سوال نمونه"])))

def load_questions(fn):
    if not os.path.exists(fn):
        return []
    with open(fn, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]

def is_admin(uid):
    try:
        return int(uid) == int(ADMIN_ID)
    except:
        return False

def init_chat(chat_id):
    games = state.get("games", {})
    if str(chat_id) not in games:
        games[str(chat_id)] = {
            "players": [],
            "idx": -1,
            "awaiting": False,
            "current_question": "",
            "current_type": "",
            "change_count": {},
            "started": False,
        }
        state["games"] = games
        save_state(state)

def add_score(uid, amount=1):
    uid = str(uid)
    if "scores" not in state:
        state["scores"] = {}
    if uid not in state["scores"]:
        state["scores"][uid] = {"score": 0}
    state["scores"][uid]["score"] += amount
    save_state(state)

def get_board(limit=10):
    items = []
    for uid, info in state.get("scores", {}).items():
        items.append((uid, info.get("score", 0)))
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:limit]

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! ربات جرأت یا حقیقت بوئین‌زهرا.\nدستورات: /join /leave /startgame /stopgame /remove <id> /leaderboard /myid")

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"آیدی شما: {update.effective_user.id}")

async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    if user.id in g["players"]:
        await update.message.reply_text("شما قبلاً عضو بازی هستید.")
        return
    g["players"].append(user.id)
    g["change_count"][str(user.id)] = 0
    save_state(state)
    await update.message.reply_text(f"{user.first_name} به بازی اضافه شد.")

async def leave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    if user.id not in g["players"]:
        await update.message.reply_text("شما در لیست نیستید.")
        return
    g["players"].remove(user.id)
    g["change_count"].pop(str(user.id), None)
    save_state(state)
    await update.message.reply_text(f"{user.first_name} از بازی خارج شد.")

async def startgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        await update.message.reply_text("فقط ادمین می‌تواند بازی را شروع کند.")
        return
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    if not g["players"]:
        await update.message.reply_text("هیچ بازیکنی نیست. /join")
        return
    g["started"] = True
    g["idx"] = -1
    save_state(state)
    await update.message.reply_text("بازی شروع شد!")
    await do_next_turn(chat_id, context)

async def stopgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        await update.message.reply_text("فقط ادمین می‌تواند متوقف کند.")
        return
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    g["started"] = False
    save_state(state)
    await update.message.reply_text("بازی متوقف شد.")

async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("فقط ادمین می‌تواند حذف کند.")
        return
    if not context.args:
        await update.message.reply_text("مثال: /remove 123456789")
        return
    try:
        tid = int(context.args[0])
    except:
        await update.message.reply_text("آیدی عددی وارد کنید.")
        return
    removed = False
    for cid, g in state.get("games", {}).items():
        if tid in g.get("players", []):
            g["players"].remove(tid)
            g["change_count"].pop(str(tid), None)
            removed = True
    if removed:
        save_state(state)
        await update.message.reply_text("حذف شد.")
    else:
        await update.message.reply_text("آن کاربر در بازی نیست.")

async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = get_board(10)
    if not items:
        await update.message.reply_text("هیچ امتیازی ثبت نشده.")
        return
    lines = ["🏆 جدول امتیازات:"]
    i = 1
    for uid, sc in items:
        mention = str(uid)
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, int(uid))
            mention = member.user.username and ("@" + member.user.username) or member.user.first_name
        except:
            mention = str(uid)
        lines.append(f"{i}. {mention} — {sc}")
        i += 1
    await update.message.reply_text("\n".join(lines))

async def do_next_turn(chat_id, context: ContextTypes.DEFAULT_TYPE):
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    if not g["players"]:
        await context.bot.send_message(chat_id=chat_id, text="هیچ بازیکنی نیست. بازی متوقف می‌شود.")
        g["started"] = False
        save_state(state)
        return
    g["idx"] = (g["idx"] + 1) % len(g["players"])
    pid = g["players"][g["idx"]]
    g["change_count"][str(pid)] = 0
    g["awaiting"] = True
    save_state(state)
    mention = str(pid)
    try:
        member = await context.bot.get_chat_member(chat_id, pid)
        mention = member.user.username and ("@" + member.user.username) or member.user.first_name
    except:
        mention = str(pid)
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔵 حقیقت", callback_data="choose|truth"),
          InlineKeyboardButton("🔴 جرأت", callback_data="choose|dare")]]
    )
    await context.bot.send_message(chat_id=chat_id, text=f"👤 نوبت: {mention}\nنوع سوال: انتخاب کن", reply_markup=kb)
    async def watcher():
        await asyncio.sleep(TURN_TIMEOUT)
        st = load_state()
        g_local = st.get("games", {}).get(str(chat_id))
        if g_local and g_local.get("awaiting"):
            state["games"][str(chat_id)]["awaiting"] = False
            save_state(state)
            await context.bot.send_message(chat_id=chat_id, text="⏱ زمان پاسخ تموم شد.")
            await do_next_turn(chat_id, context)
    asyncio.create_task(watcher())

async def callback_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user = query.from_user
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    try:
        cur = g["players"][g["idx"]]
    except:
        await query.message.reply_text("خطا در وضعیت بازی.")
        return
    if user.id != cur:
        await query.message.reply_text("❌ نوبت شما نیست.")
        return
    if query.data.endswith("truth"):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("برای پسر", callback_data="set|truth_boy"),
                                   InlineKeyboardButton("برای دختر", callback_data="set|truth_girl")]])
        await query.message.reply_text("کدام دسته؟", reply_markup=kb)
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("برای پسر", callback_data="set|dare_boy"),
                                InlineKeyboardButton("برای دختر", callback_data="set|dare_girl")]])
    await query.message.reply_text("کدام دسته؟", reply_markup=kb)

async def callback_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user = query.from_user
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    try:
        cur = g["players"][g["idx"]]
    except:
        await query.message.reply_text("خطا در وضعیت بازی.")
        return
    if user.id != cur:
        await query.message.reply_text("❌ نوبت شما نیست.")
        return
    _, qtype = query.data.split("|")
    qs = load_questions(FILES.get(qtype, ""))
    if not qs:
        await query.message.reply_text("سوال موجود نیست؛ ادمین کاملش کنه.")
        return
    q = random.choice(qs)
    g["current_question"] = q
    g["current_type"] = qtype
    g["awaiting"] = True
    save_state(state)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ پاسخ دادم", callback_data="resp|done"),
                                InlineKeyboardButton("🔄 تغییر سوال", callback_data="resp|change")]])
    mention = user.username and ("@" + user.username) or user.first_name
    await query.message.reply_text(f"👤 نوبت: {mention}\n📝 سوال: {q}\n⏳ {TURN_TIMEOUT} ثانیه فرصت داری", reply_markup=kb)

async def callback_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user = query.from_user
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    try:
        cur = g["players"][g["idx"]]
    except:
        await query.message.reply_text("خطا در وضعیت بازی.")
        return
    if user.id != cur:
        await query.message.reply_text("❌ نوبت شما نیست.")
        return
    if query.data.endswith("done"):
        add_score(user.id, 1)
        g["awaiting"] = False
        save_state(state)
        await query.message.reply_text("✅ امتیاز ثبت شد.")
        await do_next_turn(chat_id, context)
        return
    cnt = g["change_count"].get(str(user.id), 0)
    if cnt >= 2:
        await query.message.reply_text("⚠️ دیگر نمی‌توانید سوال را تغییر دهید.")
        return
    qtype = g.get("current_type")
    qs = load_questions(FILES.get(qtype, ""))
    if not qs:
        await query.message.reply_text("سوال موجود نیست؛ ادمین کاملش کنه.")
        return
    q = random.choice(qs)
    g["current_question"] = q
    g["change_count"][str(user.id)] = cnt + 1
    save_state(state)
    await query.message.reply_text(f"سوال جدید:\n📝 {q}\n(تعداد تغییر باقی‌مانده: {2 - g['change_count'][str(user.id)]})")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/join /leave /startgame /stopgame /remove <id> /leaderboard /myid")

def main():
    ensure_question_files()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CommandHandler("leave", leave_cmd))
    app.add_handler(CommandHandler("startgame", startgame_cmd))
    app.add_handler(CommandHandler("stopgame", stopgame_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    app.add_handler(CallbackQueryHandler(callback_choose, pattern=r"^choose\|"))
    app.add_handler(CallbackQueryHandler(callback_set, pattern=r"^set\|"))
    app.add_handler(CallbackQueryHandler(callback_response, pattern=r"^resp\|"))
    print("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()