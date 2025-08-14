# main.py
import asyncio
import json
import os
import random
from datetime import datetime
from typing import Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import BOT_TOKEN, ADMIN_ID, DATA_FOLDER, SCORE_FILE

# ------- تنظیمات بازی -------
TURN_TIMEOUT = 100  # ثانیه
SCORE_DARE = 2
SCORE_TRUTH = 1
PENALTY_NO_ANSWER = -1
MAX_CHANGES_PER_TURN = 2

# مسیر فایل‌ها
def qpath(name):
    return os.path.join(DATA_FOLDER, name) if DATA_FOLDER else name

FILES = {
    "truth_boy": qpath("truth_boys.txt"),
    "truth_girl": qpath("truth_girls.txt"),
    "dare_boy": qpath("dare_boys.txt"),
    "dare_girl": qpath("dare_girls.txt"),
}

STATE_PATH = "state.json"

# ------- state persistence -------
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

# ------- helper: ensure sample question files exist -------
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
            if os.path.dirname(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(samples.get(key, ["سوال نمونه"])))

# ------- questions loader -------
def load_questions(fn):
    if not fn or not os.path.exists(fn):
        return []
    with open(fn, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]

# ------- admin check -------
def is_admin(uid):
    try:
        return int(uid) == int(ADMIN_ID)
    except Exception:
        return False

# ------- init chat entry -------
def init_chat(chat_id):
    games = state.get("games", {})
    if str(chat_id) not in games:
        games[str(chat_id)] = {
            "players": [],            # list of user ids
            "idx": -1,                # current index in players
            "awaiting": False,        # waiting for answer
            "current_question": "",
            "current_type": "",
            "change_count": {},       # per-user change count this turn
            "started": False,
            "last_group_msg_id": None, # message id of the last group prompt (for deletion)
        }
        state["games"] = games
        save_state(state)

# ------- scoring -------
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


def mention_html(uid, fallback="کاربر"):
    return f"<a href='tg://user?id={uid}'>{fallback}</a>"

# ------- in-memory runtime control (not persisted) -------
current_tasks = {}  # chat_id -> asyncio.Task

# ------- utility: pick a random question given qtype -------
def pick_random_question(qtype: str):
    fn = FILES.get(qtype, "")
    qs = load_questions(fn)
    if not qs:
        return None
    return random.choice(qs)

# ------- START command with menu -------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "سلام! 🎲 ربات جرأت یا حقیقت بوئین‌زهرا\nاز دکمه‌ها استفاده کن یا دستورها رو وارد کن."
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎯 پیوستن به بازی", callback_data="menu|join")],
            [InlineKeyboardButton("🚪 ترک بازی", callback_data="menu|leave"),
             InlineKeyboardButton("▶️ شروع بازی (ادمین)", callback_data="menu|startgame")],
            [InlineKeyboardButton("⏹ توقف بازی (ادمین)", callback_data="menu|stopgame")],
            [InlineKeyboardButton("🏆 جدول امتیازات", callback_data="menu|leaderboard"),
             InlineKeyboardButton("🆔 آیدی من", callback_data="menu|myid")],
        ]
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=kb)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=kb)

# ------- myid -------
async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(chat_id=update.effective_user.id, text=f"آیدی شما: {update.effective_user.id}")
        # Also give a small public acknowledgement (non-spammy)
        await update.message.reply_text("✅ پیغام به دایرکت شما ارسال شد.")
    except Exception:
        await update.message.reply_text(f"آیدی شما: {update.effective_user.id}")

# ------- join / leave -------
async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    init_chat(chat_id)
    g = state["games"][str(chat_id)]
    if user.id in g["players"]:
        # send private note instead of public spam
        try:
            await context.bot.send_message(chat_id=user.id, text="✅ شما قبلاً عضو بازی هستید.")
        except Exception:
            await update.message.reply_text("شما قبلاً عضو بازی هستید.")
        return
    g["players"].append(user.id)
    g["change_count"][str(user.id)] = 0
    save_state(state)
    await update.message.reply_text(f"✅ {user.first_name} به بازی اضافه شد. (تعداد: {len(g['players'])})")

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
    await update.message.reply_text(f"✅ {user.first_name} از بازی خارج شد. (تعداد: {len(g['players'])})")

# ------- startgame / stopgame -------
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
    # reset change_count for safety
    g["change_count"] = {str(uid): 0 for uid in g["players"]}
    save_state(state)
    await update.message.reply_text(f"🎮 بازی شروع شد — شرکت‌کنندگان: {len(g['players'])}")
    await asyncio.sleep(0.3)
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
    # cancel any running task
    t = current_tasks.get(chat_id)
    if t:
        t.cancel()
        current_tasks.pop(chat_id, None)
    # try delete group prompt message
    try:
        if g.get("last_group_msg_id"):
            await context.bot.delete_message(chat_id=chat_id, message_id=g["last_group_msg_id"])
            g["last_group_msg_id"] = None
            save_state(state)
    except Exception:
        pass
    await update.message.reply_text("⏹ بازی متوقف شد.")

# ------- remove (admin) -------
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

# ------- leaderboard -------
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

# ------- core: proceed to next turn -------
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

    # advance index
    g["idx"] = (g["idx"] + 1) % len(g["players"])
    pid = g["players"][g["idx"]]
    # reset change counter for that player this turn (if not exist)
    g["change_count"][str(pid)] = g.get("change_count", {}).get(str(pid), 0)
    g["awaiting"] = True
    # clear current question fields
    g["current_question"] = ""
    g["current_type"] = ""
    save_state(state)

    # get name/mention
    mention_name = str(pid)
    try:
        member = await context.bot.get_chat_member(chat_id, pid)
        mention_name = member.user.username and ("@" + member.user.username) or member.user.first_name
    except Exception:
        mention_name = str(pid)

    # group prompt
    group_text = f"👤 نوبت: {mention_html(pid, mention_name)}\nشرکت‌کنندگان: {len(g['players'])}\nنوع سوال: انتخاب کن"
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔵 حقیقت", callback_data=f"choose|truth|{pid}"),
          InlineKeyboardButton("🔴 جرأت", callback_data=f"choose|dare|{pid}")]]
    )
    # send prompt and store id for deletion later
    try:
        msg = await context.bot.send_message(chat_id=chat_id, text=group_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        g["last_group_msg_id"] = msg.message_id
        save_state(state)
    except Exception:
        pass

    # start timeout watcher for this turn
    async def watcher(target_pid):
        try:
            await asyncio.sleep(TURN_TIMEOUT)
            st = load_state()
            g_local = st.get("games", {}).get(str(chat_id))
            if g_local and g_local.get("started") and g_local.get("awaiting") and g_local.get("players") and g_local.get("players")[g_local.get("idx")] == target_pid:
                # apply penalty
                state["games"][str(chat_id)]["awaiting"] = False
                add_score(target_pid, PENALTY_NO_ANSWER)
                save_state(state)
                # notify
                try:
                    await context.bot.send_message(chat_id=chat_id, text=f"⏱ زمان پاسخ تموم شد.\n{mention_html(target_pid)} امتیاز {PENALTY_NO_ANSWER} گرفت.")
                except Exception:
                    pass
                # move to next
                await do_next_turn(chat_id, context)
        except asyncio.CancelledError:
            return

    # cancel previous task if exists
    prev = current_tasks.get(chat_id)
    if prev:
        try:
            prev.cancel()
        except Exception:
            pass
    task = asyncio.create_task(watcher(pid))
    current_tasks[chat_id] = task

# ------- unified callback handler -------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    data = query.data
    parts = data.split("|")
    cmd = parts[0]

    # menu commands (from /start menu)
    if cmd == "menu":
        sub = parts[1] if len(parts) > 1 else ""
        # emulate the command handlers
        if sub == "join":
            # call join logic
            class FakeMsg: pass
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

    # choose|truth|<pid> or choose|dare|<pid>
    if cmd == "choose":
        _type = parts[1] if len(parts) > 1 else ""
        target = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        chat_id = query.message.chat.id
        user = query.from_user
        init_chat(chat_id)
        g = state["games"][str(chat_id)]
        # verify turn
        try:
            cur = g["players"][g["idx"]]
        except Exception:
            await query.message.reply_text("خطا در وضعیت بازی.")
            return
        if user.id != cur or target != cur:
            await query.message.reply_text("❌ نوبت شما نیست.")
            return
        # Now ask gender choice (boy/girl)
        if _type == "truth":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("برای پسر", callback_data=f"set|truth_boy|{cur}"),
                 InlineKeyboardButton("برای دختر", callback_data=f"set|truth_girl|{cur}")]
            ])
            await query.message.reply_text("کدام دسته؟", reply_markup=kb)
            return
        # dare
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("برای پسر", callback_data=f"set|dare_boy|{cur}"),
             InlineKeyboardButton("برای دختر", callback_data=f"set|dare_girl|{cur}")]
        ])
        await query.message.reply_text("کدام دسته؟", reply_markup=kb)
        return

    # set|<qtype>|<pid>
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
        # pick question
        q = pick_random_question(qtype)
        if not q:
            await query.message.reply_text("سوال موجود نیست؛ ادمین لطفا فایل سوال را کامل کنه.")
            return
        # store in state
        g["current_question"] = q
        g["current_type"] = qtype
        g["awaiting"] = True
        save_state(state)
        # prepare private keyboard with target check
        private_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ پاسخ دادم", callback_data=f"resp|done|{target}")],
            [InlineKeyboardButton("🔄 تغییر سوال", callback_data=f"resp|change|{target}")],
            [InlineKeyboardButton("🚫 پاسخ نمیدهم", callback_data=f"resp|no|{target}")],
        ])
        mention_name = user.username and ("@" + user.username) or user.first_name
        # send privately
        sent_private = False
        try:
            await context.bot.send_message(chat_id=target, text=f"📝 سوال شما ({'جرأت' if qtype.startswith('dare') else 'حقیقت'}):\n\n{q}\n\n⏳ {TURN_TIMEOUT} ثانیه فرصت دارید.", reply_markup=private_kb)
            sent_private = True
            # Notify group briefly
            await context.bot.send_message(chat_id=chat_id, text=f"📨 سوال به صورت خصوصی برای {mention_html(target, mention_name)} ارسال شد.")
        except Exception:
            # fallback to group if PM fails
            await query.message.reply_text(f"❗️ ارسال خصوصی نشد؛ سوال در گروه نمایش داده می‌شود.\n\n📝 سوال: {q}", reply_markup=private_kb)
        return

    # resp|<action>|<pid>
    if cmd == "resp":
        action = parts[1] if len(parts) > 1 else ""
        target = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        user = query.from_user
        chat = update.effective_chat
        # ensure the button is pressed by the correct user
        if user.id != target:
            try:
                await query.answer("این دکمه برای شما نیست.", show_alert=True)
            except Exception:
                pass
            return
        # load game
        # find which chat this belongs to: the message might be private -> we must search games to find chat containing this player and is awaiting
        game_chat_id = None
        for cid_str, g in state.get("games", {}).items():
            if user.id in g.get("players", []) and g.get("awaiting"):
                # ensure index points to this user
                try:
                    if g["players"][g["idx"]] == user.id:
                        game_chat_id = int(cid_str)
                        break
                except Exception:
                    continue
        if not game_chat_id:
            # can't find game context
            await query.message.reply_text("خطا: وضعیت بازی پیدا نشد.")
            return
        init_chat(game_chat_id)
        g = state["games"][str(game_chat_id)]
        # cancel timeout task
        t = current_tasks.get(game_chat_id)
        if t:
            t.cancel()
            current_tasks.pop(game_chat_id, None)
        # perform actions
        if action == "done":
            # award points based on type
            qtype = g.get("current_type", "")
            if qtype.startswith("dare"):
                add_score(user.id, SCORE_DARE)
                points = SCORE_DARE
            else:
                add_score(user.id, SCORE_TRUTH)
                points = SCORE_TRUTH
            g["awaiting"] = False
            save_state(state)
            # delete last group prompt to reduce clutter
            try:
                if g.get("last_group_msg_id"):
                    await context.bot.delete_message(chat_id=game_chat_id, message_id=g["last_group_msg_id"])
                    g["last_group_msg_id"] = None
                    save_state(state)
            except Exception:
                pass
            await query.message.reply_text(f"✅ ثبت شد. امتیاز شما +{points}")
            # announce briefly in group
            try:
                await context.bot.send_message(chat_id=game_chat_id, text=f"✅ {mention_html(user.id)} پاسخ داد — امتیاز +{points}")
            except Exception:
                pass
            # next turn
            await do_next_turn(game_chat_id, context)
            return

        if action == "no":
            # penalty
            add_score(user.id, PENALTY_NO_ANSWER)
            g["awaiting"] = False
            save_state(state)
            try:
                if g.get("last_group_msg_id"):
                    await context.bot.delete_message(chat_id=game_chat_id, message_id=g["last_group_msg_id"])
                    g["last_group_msg_id"] = None
                    save_state(state)
            except Exception:
                pass
            await query.message.reply_text(f"🚫 ثبت شد. امتیاز {PENALTY_NO_ANSWER} اعمال شد.")
            try:
                await context.bot.send_message(chat_id=game_chat_id, text=f"⏱ {mention_html(user.id)} پاسخ نداد/نخواست — امتیاز {PENALTY_NO_ANSWER}")
            except Exception:
                pass
            await do_next_turn(game_chat_id, context)
            return

        if action == "change":
            cnt = g.get("change_count", {}).get(str(user.id), 0)
            if cnt >= MAX_CHANGES_PER_TURN:
                await query.answer("⚠️ دیگر نمی‌توانید سوال را تغییر دهید.", show_alert=True)
                return
            # pick new question of same type
            qtype = g.get("current_type", "")
            if not qtype:
                await query.answer("خطا: نوع سوال مشخص نیست.", show_alert=True)
                return
            q = pick_random_question(qtype)
            if not q:
                await query.message.reply_text("سوال موجود نیست؛ ادمین لطفا فایل سوال را کامل کنه.")
                return
            # update
            g["current_question"] = q
            g["change_count"][str(user.id)] = cnt + 1
            save_state(state)
            # restart timeout watcher
            async def restart_watcher(pid_for):
                try:
                    await asyncio.sleep(TURN_TIMEOUT)
                    st = load_state()
                    g_local = st.get("games", {}).get(str(game_chat_id))
                    if g_local and g_local.get("started") and g_local.get("awaiting") and g_local.get("players") and g_local.get("players")[g_local.get("idx")] == pid_for:
                        state["games"][str(game_chat_id)]["awaiting"] = False
                        add_score(pid_for, PENALTY_NO_ANSWER)
                        save_state(state)
                        try:
                            await context.bot.send_message(chat_id=game_chat_id, text=f"⏱ زمان پاسخ تموم شد.\n{mention_html(pid_for)} امتیاز {PENALTY_NO_ANSWER} گرفت.")
                        except Exception:
                            pass
                        await do_next_turn(game_chat_id, context)
                except asyncio.CancelledError:
                    return

            # cancel prev task and start new
            prevt = current_tasks.get(game_chat_id)
            if prevt:
                try:
                    prevt.cancel()
                except Exception:
                    pass
            newt = asyncio.create_task(restart_watcher(user.id))
            current_tasks[game_chat_id] = newt

            # send new question privately
            try:
                await context.bot.send_message(chat_id=user.id, text=f"🔁 سوال جدید:\n\n{q}\n\n(تعداد تغییر استفاده‌شده: {g['change_count'][str(user.id)]})", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ پاسخ دادم", callback_data=f"resp|done|{user.id}")],
                    [InlineKeyboardButton("🔄 تعویض سوال", callback_data=f"resp|change|{user.id}")],
                    [InlineKeyboardButton("🚫 پاسخ نمیدهم", callback_data=f"resp|no|{user.id}")]
                ]))
                await query.message.reply_text("🔁 سوال تعویض شد و برای شما ارسال شد.")
            except Exception:
                await query.message.reply_text(f"🔁 سوال تعویض شد:\n\n{q}")
            return

    # unknown: ignore
    await query.message.reply_text("دستوری شناسایی نشد.")

# ------- help -------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/join /leave /startgame /stopgame /remove <id> /leaderboard /myid")

# ------- main app -------
def main():
    ensure_question_files()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CommandHandler("leave", leave_cmd))
    app.add_handler(CommandHandler("startgame", startgame_cmd))
    app.add_handler(CommandHandler("stopgame", stopgame_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))

    # callback handler for all inline callbacks
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
