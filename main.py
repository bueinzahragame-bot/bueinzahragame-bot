# main.py
import asyncio
import json
import os
import random
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import BOT_TOKEN, ADMIN_ID, DATA_FOLDER, SCORE_FILE

# ------------- تنظیمات قابل تغییر -------------
TURN_TIMEOUT = 100           # ثانیه زمان پاسخ
SCORE_DARE = 2
SCORE_TRUTH = 1
PENALTY_NO_ANSWER = -1
MAX_CHANGES_PER_TURN = 2
AUTO_DELETE_SECONDS = 15     # مدت حذف پیام join/leave (ثانیه)
# --------------------------------------------

def qpath(name: str) -> str:
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
        except Exception:
            return {"games": {}, "scores": {}}
    return {"games": {}, "scores": {}}

def save_state(s):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

state = load_state()

# نگهداری تسک واچرها در حافظه (برای cancel)
current_tasks: dict = {}  # chat_id -> asyncio.Task

# نمونه سوال‌ها در صورت نبودن فایل
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
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(samples.get(key, ["سوال نمونه"])))

def load_questions(fn: str):
    if not fn or not os.path.exists(fn):
        return []
    with open(fn, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]

def is_admin(uid) -> bool:
    try:
        return int(uid) == int(ADMIN_ID)
    except Exception:
        return False

def init_chat(chat_id: int):
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
            "last_group_msg_id": None,
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

def mention_html(uid: int, fallback: str = "کاربر") -> str:
    return f"<a href='tg://user?id={uid}'>{fallback}</a>"

async def delete_later(bot, chat_id: int, message_id: int, delay: int = AUTO_DELETE_SECONDS):
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

def pick_random_question(qtype: str) -> Optional[str]:
    fn = FILES.get(qtype, "")
    qs = load_questions(fn)
    if not qs:
        return None
    return random.choice(qs)

# ----------------- فرمان‌ها -----------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "سلام! 🎲 ربات جرأت یا حقیقت بوئین‌زهرا\nاز دکمه‌ها استفاده کن یا دستورها رو وارد کن."
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 پیوستن به بازی", callback_data="menu|join")],
        [InlineKeyboardButton("🚪 ترک بازی", callback_data="menu|leave"),
         InlineKeyboardButton("▶️ شروع بازی (ادمین)", callback_data="menu|startgame")],
        [InlineKeyboardButton("⏹ توقف بازی (ادمین)", callback_data="menu|stopgame")],
        [InlineKeyboardButton("🏆 جدول امتیازات", callback_data="menu|leaderboard"),
         InlineKeyboardButton("🆔 آیدی من", callback_data="menu|myid")],
    ])
    if update.message:
        await update.message.reply_text(text, reply_markup=kb)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=kb)

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # سعی کنیم پیغام خصوصی بفرستیم، اگر نشد عمومی بفرست
    try:
        await context.bot.send_message(chat_id=update.effective_user.id, text=f"آیدی شما: {update.effective_user.id}")
        await update.message.reply_text("✅ پیغام به دایرکت شما ارسال شد.")
    except Exception:
        await update.message.reply_text(f"آیدی شما: {update.effective_user.id}")

async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    if user.id in g["players"]:
        try:
            await context.bot.send_message(chat_id=user.id, text="✅ شما قبلاً عضو بازی هستید.")
        except Exception:
            await update.message.reply_text("✅ شما قبلاً عضو بازی هستید.")
        return
    g["players"].append(user.id)
    g["change_count"][str(user.id)] = 0
    save_state(state)
    msg = await update.message.reply_text(f"✅ {user.first_name} به بازی اضافه شد. (تعداد: {len(g['players'])})")
    asyncio.create_task(delete_later(context.bot, chat_id, msg.message_id, AUTO_DELETE_SECONDS))

async def leave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    if user.id not in g["players"]:
        await update.message.reply_text("❌ شما در لیست نیستید.")
        return
    g["players"].remove(user.id)
    g["change_count"].pop(str(user.id), None)
    save_state(state)
    msg = await update.message.reply_text(f"✅ {user.first_name} از بازی خارج شد. (تعداد: {len(g['players'])})")
    asyncio.create_task(delete_later(context.bot, chat_id, msg.message_id, AUTO_DELETE_SECONDS))

async def startgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        await update.message.reply_text("فقط ادمین می‌تواند بازی را شروع کند.")
        return
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    if not g["players"]:
        await update.message.reply_text("هیچ بازیکنی نیست. لطفاً /join کنید.")
        return
    g["started"] = True
    g["idx"] = -1
    g["change_count"] = {str(uid): 0 for uid in g["players"]}
    save_state(state)
    await update.message.reply_text(f"🎮 بازی شروع شد — شرکت‌کنندگان: {len(g['players'])}")
    await asyncio.sleep(0.2)
    await do_next_turn(chat_id, context)

async def stopgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        await update.message.reply_text("فقط ادمین می‌تواند بازی را متوقف کند.")
        return
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    g["started"] = False
    g["awaiting"] = False
    save_state(state)
    t = current_tasks.get(chat_id)
    if t:
        t.cancel()
        current_tasks.pop(chat_id, None)
    try:
        if g.get("last_group_msg_id"):
            await context.bot.delete_message(chat_id=chat_id, message_id=g["last_group_msg_id"])
            g["last_group_msg_id"] = None
            save_state(state)
    except Exception:
        pass
    await update.message.reply_text("⏹ بازی متوقف شد.")

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
    except Exception:
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
        await update.message.reply_text("✅ حذف شد.")
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
        except Exception:
            mention = str(uid)
        lines.append(f"{i}. {mention} — {sc}")
        i += 1
    await update.message.reply_text("\n".join(lines))

# ----------------- جریان بازی -----------------
async def do_next_turn(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    if not g["players"]:
        await context.bot.send_message(chat_id=chat_id, text="هیچ بازیکنی نیست. بازی متوقف می‌شود.")
        g["started"] = False
        save_state(state)
        return
    if not g.get("started"):
        return

    g["idx"] = (g["idx"] + 1) % len(g["players"])
    pid = g["players"][g["idx"]]
    g["change_count"].setdefault(str(pid), 0)
    g["awaiting"] = True
    g["current_question"] = ""
    g["current_type"] = ""
    save_state(state)

    mention_name = str(pid)
    try:
        member = await context.bot.get_chat_member(chat_id, pid)
        mention_name = member.user.username and ("@" + member.user.username) or member.user.first_name
    except Exception:
        mention_name = str(pid)

    group_text = f"👤 نوبت: {mention_html(pid, mention_name)}\nشرکت‌کنندگان: {len(g['players'])}\nنوع سوال: انتخاب کن"
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔵 حقیقت", callback_data=f"choose|truth|{pid}"),
          InlineKeyboardButton("🔴 جرأت", callback_data=f"choose|dare|{pid}")]]
    )
    try:
        msg = await context.bot.send_message(chat_id=chat_id, text=group_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        g["last_group_msg_id"] = msg.message_id
        save_state(state)
    except Exception:
        pass

    # cancel previous watcher
    prev = current_tasks.get(chat_id)
    if prev:
        try:
            prev.cancel()
        except Exception:
            pass

    async def watcher(target_pid: int):
        try:
            await asyncio.sleep(TURN_TIMEOUT)
            st = load_state()
            g_local = st.get("games", {}).get(str(chat_id))
            if g_local and g_local.get("started") and g_local.get("awaiting") and g_local.get("players") and g_local.get("players")[g_local.get("idx")] == target_pid:
                state["games"][str(chat_id)]["awaiting"] = False
                add_score(target_pid, PENALTY_NO_ANSWER)
                save_state(state)
                # try get name
                try:
                    member2 = await context.bot.get_chat_member(chat_id, target_pid)
                    mname = member2.user.username and ("@" + member2.user.username) or member2.user.first_name
                except Exception:
                    mname = str(target_pid)
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⏱ {mention_html(target_pid, mname)} فرصت پاسخ را از دست داد — {PENALTY_NO_ANSWER} امتیاز کسر شد.",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
                await asyncio.sleep(0.3)
                st2 = load_state()
                g2 = st2.get("games", {}).get(str(chat_id))
                if g2 and g2.get("started"):
                    await do_next_turn(chat_id, context)
        except asyncio.CancelledError:
            return

    task = asyncio.create_task(watcher(pid))
    current_tasks[chat_id] = task

# ----------------- هندلر CallbackQuery (منو و دکمه‌ها) -----------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    data = query.data
    parts = data.split("|")
    cmd = parts[0]

    # منوها
    if cmd == "menu":
        sub = parts[1] if len(parts) > 1 else ""
        if sub == "join":
            await join_cmd(update, context)
            return
        if sub == "leave":
            await leave_cmd(update, context)
            return
        if sub == "startgame":
            await startgame_cmd(update, context)
            return
        if sub == "stopgame":
            await stopgame_cmd(update, context)
            return
        if sub == "leaderboard":
            await leaderboard_cmd(update, context)
            return
        if sub == "myid":
            await myid_cmd(update, context)
            return

    # choose|truth|<pid>  یا choose|dare|<pid>
    if cmd == "choose":
        _type = parts[1] if len(parts) > 1 else ""
        target = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        chat_id = query.message.chat.id
        user = query.from_user
        init_chat(chat_id)
        g = state["games"][str(chat_id)]
        try:
            cur = g["players"][g["idx"]]
        except Exception:
            await query.message.reply_text("خطا در وضعیت بازی.")
            return
        if user.id != cur or target != cur:
            await query.message.reply_text("❌ نوبت شما نیست.")
            return
        if _type == "truth":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("برای پسر", callback_data=f"set|truth_boy|{cur}"),
                 InlineKeyboardButton("برای دختر", callback_data=f"set|truth_girl|{cur}")]
            ])
            await query.message.reply_text("کدام دسته؟", reply_markup=kb)
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("برای پسر", callback_data=f"set|dare_boy|{cur}"),
             InlineKeyboardButton("برای دختر", callback_data=f"set|dare_girl|{cur}")]
        ])
        await query.message.reply_text("کدام دسته؟", reply_markup=kb)
        return

    # set|<qtype>|<pid>  -> نمایش سوال **در گروه**
    if cmd == "set":
        qtype = parts[1] if len(parts) > 1 else ""
        target = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        chat_id = query.message.chat.id
        user = query.from_user
        init_chat(chat_id)
        g = state["games"][str(chat_id)]
        try:
            cur = g["players"][g["idx"]]
        except Exception:
            await query.message.reply_text("خطا در وضعیت بازی.")
            return
        if user.id != cur or target != cur:
            await query.message.reply_text("❌ نوبت شما نیست.")
            return
        q = pick_random_question(qtype)
        if not q:
            await query.message.reply_text("سوال موجود نیست؛ ادمین لطفا فایل سوال را کامل کنه.")
            return
        g["current_question"] = q
        g["current_type"] = qtype
        g["awaiting"] = True
        save_state(state)
        group_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ پاسخ دادم", callback_data=f"resp|done|{target}"),
             InlineKeyboardButton("🔄 تغییر سوال", callback_data=f"resp|change|{target}")],
            [InlineKeyboardButton("🚫 پاسخ نمیدهم", callback_data=f"resp|no|{target}")]
        ])
        # send question to group so همه ببینند
        mention_name = user.username and ("@" + user.username) or user.first_name
        try:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"📝 سوال برای {mention_html(target, mention_name)}:\n\n{q}\n\n⏳ {TURN_TIMEOUT} ثانیه فرصت دارید.",
                reply_markup=group_kb,
                parse_mode=ParseMode.HTML
            )
            g["last_group_msg_id"] = msg.message_id
            save_state(state)
        except Exception:
            # fallback: send plain
            await query.message.reply_text(f"📝 سوال:\n{q}", reply_markup=group_kb)
        return

    # resp|action|pid
    if cmd == "resp":
        action = parts[1] if len(parts) > 1 else ""
        target = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        user = query.from_user

        # ensure correct user
        if user.id != target:
            try:
                await query.answer("این دکمه برای شما نیست.", show_alert=True)
            except Exception:
                pass
            return

        # find the chat where this player is currently awaiting
        game_chat_id = None
        for cid_str, g in state.get("games", {}).items():
            if user.id in g.get("players", []) and g.get("awaiting"):
                try:
                    if g["players"][g["idx"]] == user.id:
                        game_chat_id = int(cid_str)
                        break
                except Exception:
                    continue
        if not game_chat_id:
            await query.message.reply_text("خطا: وضعیت بازی پیدا نشد.")
            return

        init_chat(game_chat_id)
        g = state["games"][str(game_chat_id)]
        # cancel watcher for this chat
        t = current_tasks.get(game_chat_id)
        if t:
            try:
                t.cancel()
            except Exception:
                pass
            current_tasks.pop(game_chat_id, None)

        if action == "done":
            qtype = g.get("current_type", "")
            if qtype.startswith("dare"):
                add_score(user.id, SCORE_DARE)
                pts = SCORE_DARE
            else:
                add_score(user.id, SCORE_TRUTH)
                pts = SCORE_TRUTH
            g["awaiting"] = False
            save_state(state)
            try:
                await context.bot.send_message(chat_id=game_chat_id, text=f"✅ {mention_html(user.id, user.first_name)} پاسخ داد — +{pts} امتیاز.", parse_mode=ParseMode.HTML)
            except Exception:
                pass
            # cleanup last group prompt if exists
            try:
                if g.get("last_group_msg_id"):
                    await context.bot.delete_message(chat_id=game_chat_id, message_id=g["last_group_msg_id"])
                    g["last_group_msg_id"] = None
                    save_state(state)
            except Exception:
                pass
            await asyncio.sleep(0.2)
            await do_next_turn(game_chat_id, context)
            return

        if action == "no":
            add_score(user.id, PENALTY_NO_ANSWER)
            g["awaiting"] = False
            save_state(state)
            try:
                await context.bot.send_message(chat_id=game_chat_id, text=f"⛔ {mention_html(user.id, user.first_name)} پاسخ نداد/نخواست — {PENALTY_NO_ANSWER} امتیاز.", parse_mode=ParseMode.HTML)
            except Exception:
                pass
            try:
                if g.get("last_group_msg_id"):
                    await context.bot.delete_message(chat_id=game_chat_id, message_id=g["last_group_msg_id"])
                    g["last_group_msg_id"] = None
                    save_state(state)
            except Exception:
                pass
            await asyncio.sleep(0.2)
            await do_next_turn(game_chat_id, context)
            return

        if action == "change":
            cnt = g["change_count"].get(str(user.id), 0)
            if cnt >= MAX_CHANGES_PER_TURN:
                await query.message.reply_text("⚠️ دیگر نمی‌توانید سوال را تغییر دهید.")
                return
            qtype = g.get("current_type", "")
            qs = load_questions(FILES.get(qtype, ""))
            if not qs:
                await query.message.reply_text("سوال موجود نیست؛ ادمین کاملش کنه.")
                return
            q_new = random.choice(qs)
            g["current_question"] = q_new
            g["change_count"][str(user.id)] = cnt + 1
            save_state(state)
            # edit last group message if possible
            try:
                if g.get("last_group_msg_id"):
                    await context.bot.edit_message_text(
                        chat_id=game_chat_id,
                        message_id=g["last_group_msg_id"],
                        text=f"📝 سوال جدید برای {mention_html(user.id, user.first_name)}:\n\n{q_new}\n(تغییر استفاده‌شده: {g['change_count'][str(user.id)]}/{MAX_CHANGES_PER_TURN})\n⏳ {TURN_TIMEOUT} ثانیه فرصت دارید.",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await context.bot.send_message(chat_id=game_chat_id, text=f"📝 سوال جدید:\n{q_new}")
            except Exception:
                await query.message.reply_text(f"سوال جدید:\n{q_new}\n(تغییر استفاده‌شده: {g['change_count'][str(user.id)]}/{MAX_CHANGES_PER_TURN})")
            # restart watcher for remaining time (we'll restart full TURN_TIMEOUT)
            task = asyncio.create_task(do_restart_watch(game_chat_id, context, user.id))
            current_tasks[game_chat_id] = task
            return

    # fallback
    try:
        await query.message.reply_text("عملیات نامشخص یا منقضی شده.")
    except Exception:
        pass

async def do_restart_watch(chat_id: int, context: ContextTypes.DEFAULT_TYPE, pid: int):
    # cancel existing
    prev = current_tasks.get(chat_id)
    if prev:
        try:
            prev.cancel()
        except Exception:
            pass
    async def watcher():
        try:
            await asyncio.sleep(TURN_TIMEOUT)
            st = load_state()
            g_local = st.get("games", {}).get(str(chat_id))
            if g_local and g_local.get("started") and g_local.get("awaiting") and g_local.get("players") and g_local.get("players")[g_local.get("idx")] == pid:
                state["games"][str(chat_id)]["awaiting"] = False
                add_score(pid, PENALTY_NO_ANSWER)
                save_state(state)
                try:
                    member2 = await context.bot.get_chat_member(chat_id, pid)
                    mname = member2.user.username and ("@" + member2.user.username) or member2.user.first_name
                except Exception:
                    mname = str(pid)
                try:
                    await context.bot.send_message(chat_id=chat_id, text=f"⏱ {mention_html(pid, mname)} فرصت پاسخ را از دست داد — {PENALTY_NO_ANSWER} امتیاز کسر شد.", parse_mode=ParseMode.HTML)
                except Exception:
                    pass
                await asyncio.sleep(0.2)
                st2 = load_state()
                g2 = st2.get("games", {}).get(str(chat_id))
                if g2 and g2.get("started"):
                    await do_next_turn(chat_id, context)
        except asyncio.CancelledError:
            return
    t = asyncio.create_task(watcher())
    current_tasks[chat_id] = t

# ----------------- بوت آپ و هَندلرها -----------------
def main():
    ensure_question_files()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", start_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CommandHandler("leave", leave_cmd))
    app.add_handler(CommandHandler("startgame", startgame_cmd))
    app.add_handler(CommandHandler("stopgame", stopgame_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))

    # callback queries (all)
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
