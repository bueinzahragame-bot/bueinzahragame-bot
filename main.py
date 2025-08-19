# main.py
import asyncio
import json
import os
import random
import traceback
from typing import Optional
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ---------- تنظیمات ----------
from config import BOT_TOKEN, ADMIN_ID, DATA_FOLDER, SCORE_FILE

# پارامترها (قابل تغییر)
TURN_TIMEOUT = 90           # ثانیه زمان پاسخ
SCORE_DARE = 2
SCORE_TRUTH = 1
PENALTY_NO_ANSWER = -1
MAX_CHANGES_PER_TURN = 2
AUTO_DELETE_SECONDS = 15    # حذف خودکار پیام‌های اطلاع‌رسانی join/leave

# ---------- state file ----------
STATE_FILE = SCORE_FILE  # از کانفیگ استفاده می‌کنیم

# ---------- global state ----------
state = {"games": {}, "scores": {}}
current_tasks: dict = {}  # chat_id -> asyncio.Task (واچرها)

# ---------- logging ----------
def write_log(chat_id, text):
    try:
        with open("actions.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.utcnow().isoformat()} [{chat_id}] {text}\n")
    except Exception:
        pass

# ---------- کمک‌کننده‌ها ----------
def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_state():
    global state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {"games": {}, "scores": {}}
    else:
        state = {"games": {}, "scores": {}}

def is_admin(user_id) -> bool:
    try:
        return int(user_id) == int(ADMIN_ID)
    except Exception:
        return False

def mention_html(uid: int, fallback: str = "کاربر") -> str:
    return f"<a href='tg://user?id={uid}'>{fallback}</a>"

def get_player_mention(user) -> str:
    if user and getattr(user, "username", None):
        return f"@{user.username}"
    return (user.first_name if user else "کاربر")

def qpath(name: str) -> str:
    return os.path.join(DATA_FOLDER, name) if DATA_FOLDER else name

FILES = {
    "truth_boy": qpath("truth_boys.txt"),
    "truth_girl": qpath("truth_girls.txt"),
    "dare_boy": qpath("dare_boys.txt"),
    "dare_girl": qpath("dare_girls.txt"),
}

def ensure_data_folder():
    if DATA_FOLDER and not os.path.exists(DATA_FOLDER):
        os.makedirs(DATA_FOLDER, exist_ok=True)

# ---------- سوال‌ها پیش‌فرض (اگر فایل‌ها نیستند ایجاد می‌شوند) ----------
def ensure_question_files():
    samples = {
        "truth_boy": [
            "برای اینکه جذاب به نظر برسی چه کار می‌کنی؟",
            "در حال حاضر از کی خوشت میاد؟",
            "به کی حسودی می‌کنی؟",
            "پنج پسر اولی که به نظرت جذابن رو نام ببر؟",
            "اگر می‌تونستی نامرئی بشی چکار می‌کردی؟",
            "دختر ایده‌آلت چه ویژگی‌هایی داره؟",
            "تا به حال عاشق شدی؟",
            "اگر هرچیزی که می‌خواستی رو می‌تونستی بخری، چی می‌خریدی؟",
            "اسم کسی که توی این جمع خیلی خیلی دوسش داری چیه؟",
            "زیباترین خاطرت با کیه؟",
            "به شریکت بگو که چه ویژگی هایی رو در اون دوست داری",
            "سخت‌ترین و تلخ‌ترین لحظات زندگیت با عشقت رو بازگو کن",
            "در چه مورد دوست نداری کسی با عشقت شوخی کنه؟",
            "اولین برداشت تو از عشقت چه بوده؟",
            "چه کسی تو این جمع از همه خوشگلتره؟",
            "یکی از فانتزی‌هات رو تعریف کن",
            "تا به حال مواد مخدر مصرف کردی؟",
            "تا به حال کسی پیشنهاد دوستی تو رو رد کرده؟",
            "مرد یا زن رویا‌های تو چه شکلیه؟",
            "جذاب‌ترین آدم توی این اتاق از نظر تو کیه؟",
            "تا حالا تو جمع گوزیدی؟",
            "رو کسی تو این جمع کراش داری؟",
            "آخرین دعوات کی بوده؟",
            "رلی یا سینگل؟",
            "گرون قیمت ترین چیزی که خریدی؟",
            "نظرت درباره ادمین گروه؟",
            "بزرگترین ترست چیه؟",
            "بزرگترین اشتباهی که تا حالا کردی چی بوده؟",
            "چیزی هست که از خودت پنهان کنی؟",
            "اگه میتونستی یه چیزی رو توی زندگیت تغییر بدی، چی بود؟",
            "از چی بیشتر از همه میترسی؟",
            "تاحالا به کسی دروغ گفتی؟",
            "تاحالا چیزی رو از کسی دزدیدی؟",
            "چیزی هست که ازش پشیمون باشی؟",
            "بزرگترین آرزوت چیه؟",
            "تا حالا به کسی حسودی کردی؟",
            "چیزی هست که بخوای به دوستت بگی ولی جراتشو نداشته باشی؟",
            "بهترین دوستت چه ویژگی ای داره؟",
            "اگه یه روز بتونی جای یه نفر دیگه باشی، کی رو انتخاب میکنی؟",
            "بزرگترین موفقیتت چی بوده؟",
            "تا حالا چیزی رو شکستی که خیلی با ارزش بوده؟",
            "بهترین خاطره ات از بچگی چیه؟",
            "بدترین اتفاقی که برات افتاده چی بوده؟",
            "چیزی هست که ازش خجالت بکشی؟",
            "اگه یه آرزو داشته باشی، چی از خدا میخوای؟",
        ],
        "truth_girl": [
            "دوست داری چندتا بچه داشته باشی؟",
            "بعضی از ناامنی‌هایی که تو رابطه‌ت حس می‌کنی رو نام ببر",
            "یک دروغ که توی رابطت گفتی رو تعریف کن",
            "چه چیزی در مورد ادمین رو نمی‌پسندی؟",
            "چه چیزی در مورد دوستات رو دوست داری؟",
            "اگر مجبور باشی با یکی از پسر‌ها / دختر‌های این جمع ازدواج کنی، کدام را انتخاب می‌کنی؟",
            "آهنگ مورد علاقت چیه؟",
            "به چه کسی توی این جمع حسادت می‌کنی؟",
            "از گفتن چه چیزی به من بیش از همه می‌ترسی؟",
            "اگر هرچیزی که می‌خواستی رو می‌تونستی بخری، چی می‌خریدی؟",
            "برای اینکه جذاب به نظر برسی چه کار می‌کنی؟",
            "در حال حاضر از کی خوشت میاد؟",
            "به کی حسودی می‌کنی؟",
            "پنج پسر اولی که به نظرت جذابن رو نام ببر؟",
            "جذاب‌ترین چیز در مورد مرد‌ها چیه؟",
            "آیا با کسی که از تو کوتاهتر باشه ازدواج می‌کنی؟",
            "از کی بیشتر از همه بدت میاد؟",
            "از کدوم بازیگر خوشت میاد؟",
            "اگر می‌شد پسر بشی، چکار می‌کردی؟",
            "کی توی این جمع از همه خنده‌دارتره؟",
            "آیا تاکنون از جیب کسی پول برداشته اید؟",
            "آیا از دوستی با یکی از افراد جمع پشیمان هستید؟",
            "فکر می کنید که حسود ترین شخص جمع کیست؟",
            "آیا تاکنون بدهی افراد را زیر پا گذاشته اید؟ (در صورتی که آن ها هم فراموش کرده باشند.)",
            "آیا تا به حال به کسی خیانت کرده اید؟",
            "بدترین شکست عشقی شما چه بود؟",
            "آخرین باری که به کسی دایرکت بد دادید را بخوانید.",
            "به نظر تو باهوش ترین شخص جمع کیست؟",
            "به نظر شما جلف ترین شخص جمع کیست؟",
            "لوس ترین حرفی که به پارتنرنت زدی؟",
            "بدترین جمله عاشقانه ای که گفته ای چه بود؟",
            "بد ترین سوتی عمرت",
            "دوست داری چند سالگی ازدواج کنی؟",
            "دوست داری بچه دختر باشه یا پسر؟",
            "آخرین بازی که توسط پدر و مادرت تنبیه شدی؟",
            "الان چه لباسی پوشیدی؟",
            "بدترین حرکتی یه پسر می‌تونه بزنه و از چشمات میوفته؟",
            "پسر پولدار زشت یا پسر فقیر خوشتیپ",
            "ادمین این گپ خیلی بی،شعوره قبول داری؟",
        ],
        "dare_boy": [
            "یک عکس از خودت با یک فیلتر خنده دار در گروه بفرست.",
            "یک پیام عاشقانه به فردی که بیشتر از همه دوستش داری بفرست.",
            "به مدت یک دقیقه وانمود کن که یک حیوان هستی.",
            "یک ژست خنده دار بگیر و عکسش را در گروه بفرست.",
            "یک جوک خنده دار برای گروه تعریف کن.",
            "یک کار احمقانه انجام بده و آن را در گروه به اشتراک بگذار.",
            "یک دقیقه تمام حرف بزن بدون اینکه مکث کنی.",
            "به یکی از دخترای گپ پیشنهاد ازدواج بده",
            "سرچ اخیر گوگل رو اسکرین بگیر و بفرست گروه",
            "وویس بگیر و صدای خر دربیار",
            "8 ثانیه از محیطی که الان هستی فیلم بگیر و بفرست گروه",
            "به یکی از اعضای گپ بگو روشون کراش داری",
            "دو عکس اخر گالریت رو به اشتراک بزار",
            "از صفحه گوشیت اسکرین بفرست",
            "تو بیوگرافیت بنویس این کاربر عقل ندارد » و بزار یک ساعت بمونه",
            "وویس بگیر و سعی کن انگلیسی صحبت کنی",
        ],
        "dare_girl": [
            "عکس از خودت با یک فیلتر خنده دار در گروه بفرست.",
            "یک پیام عاشقانه به فردی که بیشتر از همه دوستش داری بفرست.",
            "به مدت یک دقیقه وانمود کن که یک حیوان هستی.",
            "یک ژست خنده دار بگیر و عکسش را در گروه بفرست.",
            "یک جوک خنده دار برای گروه تعریف کن.",
            "یک کار احمقانه انجام بده و آن را در گروه به اشتراک بگذار.",
            "یک دقیقه تمام حرف بزن بدون اینکه مکث کنی.",
            "به یکی از پسرای گپ پیشنهاد ازدواج بده",
            "سرچ اخیر گوگل رو اسکرین بگیر و بفرست گروه",
            "وویس بگیر و صدای خر دربیار",
            "8 ثانیه از محیطی که الان هستی فیلم بگیر و بفرست گروه",
            "به یکی از اعضای گپ بگو روشون کراش داری",
            "دو عکس اخر گالریت رو به اشتراک بزار",
            "از صفحه گوشیت اسکرین بفرست",
            "تو بیوگرافیت بنویس این کاربر عقل ندارد » و بزار یک ساعت بمونه",
            "وویس بگیر وسعی کن انگلیسی صحبت کنی",
        ],
    }
    for key, path in FILES.items():
        if not os.path.exists(path):
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            arr = samples.get(key, ["سوال نمونه"])
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(arr))

def load_questions(fn: str):
    if fn in FILES:
        path = FILES[fn]
    else:
        path = fn
    if not path or not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]

def get_random_question(qtype: str, avoid: Optional[str] = None) -> Optional[str]:
    filename = {
        "truth_boy": FILES["truth_boy"],
        "truth_girl": FILES["truth_girl"],
        "dare_boy": FILES["dare_boy"],
        "dare_girl": FILES["dare_girl"],
    }.get(qtype)
    if not filename:
        return None
    qs = load_questions(filename)
    if not qs:
        return None
    # used_questions per chat stored in state["games"][chat]["used_questions"]
    return random.choice(qs) if not avoid else _choose_avoiding(qs, avoid)

def _choose_avoiding(qs, avoid):
    if not qs:
        return None
    if len(qs) == 1:
        return qs[0]
    q = random.choice(qs)
    attempts = 0
    while q == avoid and attempts < 8:
        q = random.choice(qs)
        attempts += 1
    return q

# ---------- مدیریت بازی ----------
def init_game(chat_id: int):
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
            "last_prompt_msg_id": None,   # پیام انتخاب نوع (حقیقت/جرأت)
            "last_group_msg_id": None,    # پیام سوال (تا حذف/ویرایش شود)
            "used_questions": {},        # per qtype list
        }
        state["games"] = games
        save_state()

def add_score(uid, amount=1):
    s = state.setdefault("scores", {})
    k = str(uid)
    if k not in s:
        s[k] = {"score": 0}
    s[k]["score"] += amount
    save_state()

def get_leaderboard(limit=10):
    items = []
    for uid, info in state.get("scores", {}).items():
        items.append((uid, info.get("score", 0)))
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:limit]

def next_player(chat_id: int) -> Optional[int]:
    g = state["games"].get(str(chat_id))
    if not g or not g.get("players"):
        return None
    # advance index and wrap
    g["idx"] = (g.get("idx", -1) + 1) % len(g["players"])
    save_state()
    return g["players"][g["idx"]]

def current_player(chat_id: int) -> Optional[int]:
    g = state["games"].get(str(chat_id))
    if not g or not g.get("players"):
        return None
    idx = g.get("idx", -1)
    if idx < 0 or idx >= len(g["players"]):
        return None
    return g["players"][idx]

# ---------- UI / commands ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "سلام! 🎲 ربات جرأت یا حقیقت\nدکمه‌ها یا دستورات را استفاده کنید."
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 پیوستن به بازی", callback_data="menu|join")],
        [InlineKeyboardButton("🚪 ترک بازی", callback_data="menu|leave"),
         InlineKeyboardButton("▶️ شروع بازی (ادمین)", callback_data="menu|startgame")],
        [InlineKeyboardButton("⏹ توقف بازی (ادمین)", callback_data="menu|stopgame"),
         InlineKeyboardButton("⏭️ رد نوبت (ادمین)", callback_data="menu|skip")],
        [InlineKeyboardButton("🏆 جدول امتیازات", callback_data="menu|leaderboard"),
         InlineKeyboardButton("🆔 آیدی من", callback_data="menu|myid")],
        [InlineKeyboardButton("📜 قوانین", callback_data="menu|rules"),
         InlineKeyboardButton("📋 وضعیت بازی", callback_data="menu|status")],
    ])
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=kb)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/join — وارد بازی شو\n"
        "/leave — از بازی خارج شو\n"
        "/startgame — (ادمین) شروع بازی\n"
        "/stopgame — (ادمین) توقف بازی\n"
        "/skip — (ادمین) رد کردن نوبت فعلی\n"
        "/remove <user_id> — (ادمین) حذف از بازی\n"
        "/addq <type> <text> — (ادمین) اضافه سوال\n"
        "/delq <type> <index> — (ادمین) حذف سوال از فایل (index از 1)\n"
        "/leaderboard — نمایش جدول امتیازات\n"
        "/status — وضعیت بازی\n"
        "/queue — لیست بازیکنان و نوبت\n"
        "/myid — گرفتن آیدی عددی شما\n"
        "/rules — قوانین بازی"
    )

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        await context.bot.send_message(chat_id=user.id, text=f"آیدی شما: {user.id}")
        await update.message.reply_text("✅ پیغام به دایرکت شما ارسال شد.")
    except Exception:
        await update.message.reply_text(f"آیدی شما: {user.id}")

async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    if user.id in g["players"]:
        try:
            await context.bot.send_message(chat_id=user.id, text="✅ شما قبلاً عضو بازی هستید.")
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text="✅ شما قبلاً عضو بازی هستید.")
        return
    g["players"].append(user.id)
    g["change_count"][str(user.id)] = 0
    save_state()
    msg = await context.bot.send_message(chat_id=chat_id, text=f"✅ {get_player_mention(user)} به بازی اضافه شد. (تعداد: {len(g['players'])})")
    delete_later(context.bot, chat_id, msg.message_id, AUTO_DELETE_SECONDS)
    write_log(chat_id, f"join {user.id}")

async def leave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    if user.id not in g["players"]:
        await context.bot.send_message(chat_id=chat_id, text="❌ شما در لیست نیستید.")
        return
    g["players"].remove(user.id)
    g["change_count"].pop(str(user.id), None)
    save_state()
    msg = await context.bot.send_message(chat_id=chat_id, text=f"✅ {get_player_mention(user)} از بازی خارج شد. (تعداد: {len(g['players'])})")
    delete_later(context.bot, chat_id, msg.message_id, AUTO_DELETE_SECONDS)
    write_log(chat_id, f"leave {user.id}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    started = "✅ فعال" if g.get("started") else "⛔ متوقف"
    cur = current_player(chat_id)
    cur_name = "ندارد"
    if cur:
        try:
            mem = await context.bot.get_chat_member(chat_id, cur)
            cur_name = mem.user.username and ("@" + mem.user.username) or mem.user.first_name
        except:
            cur_name = str(cur)
    text = f"وضعیت بازی: {started}\nشرکت‌کنندگان: {len(g.get('players', []))}\nنوبت فعلی: {cur_name}\nسوال فعلی: {g.get('current_question') or 'ندارد'}"
    await context.bot.send_message(chat_id=chat_id, text=text)

async def queue_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    if not g["players"]:
        return await context.bot.send_message(chat_id=chat_id, text="هیچ بازیکنی نیست.")
    lines = []
    for i, uid in enumerate(g["players"], start=1):
        try:
            m = await context.bot.get_chat_member(chat_id, uid)
            name = m.user.username and ("@" + m.user.username) or m.user.first_name
        except:
            name = str(uid)
        marker = "🔴" if i-1 == g.get("idx", -1) else "•"
        lines.append(f"{marker} {i}. {name}")
    await context.bot.send_message(chat_id=chat_id, text="\n".join(lines))

# ---------- مدیریت سوال‌ها (ادمین) ----------
async def addq_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        return await context.bot.send_message(chat_id=chat_id, text="فقط ادمین می‌تواند سوال اضافه کند.")
    if not context.args or len(context.args) < 2:
        return await context.bot.send_message(chat_id=chat_id, text="مثال: /addq truth_boy سوال جدید")
    qtype = context.args[0]
    text = " ".join(context.args[1:])
    path = FILES.get(qtype)
    if not path:
        return await context.bot.send_message(chat_id=chat_id, text="نوع سوال نامعتبر. (truth_boy, truth_girl, dare_boy, dare_girl)")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + text)
        await context.bot.send_message(chat_id=chat_id, text="✅ سوال اضافه شد.")
        write_log(chat_id, f"addq {user.id} {qtype} {text[:60]}")
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text="خطا در نوشتن فایل سوال.")

async def delq_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        return await context.bot.send_message(chat_id=chat_id, text="فقط ادمین می‌تواند سوال حذف کند.")
    if not context.args or len(context.args) < 2:
        return await context.bot.send_message(chat_id=chat_id, text="مثال: /delq truth_boy 3  (حذف سوال سوم)")
    qtype = context.args[0]
    try:
        idx = int(context.args[1]) - 1
    except:
        return await context.bot.send_message(chat_id=chat_id, text="ایندکس باید عدد باشد (از 1 شروع).")
    path = FILES.get(qtype)
    if not path or not os.path.exists(path):
        return await context.bot.send_message(chat_id=chat_id, text="نوع سوال نامعتبر یا فایل وجود ندارد.")
    qs = load_questions(path)
    if idx < 0 or idx >= len(qs):
        return await context.bot.send_message(chat_id=chat_id, text="ایندکس خارج از محدوده است.")
    removed = qs.pop(idx)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(qs))
        await context.bot.send_message(chat_id=chat_id, text=f"✅ سوال حذف شد: {removed}")
        write_log(chat_id, f"delq {user.id} {qtype} idx={idx+1}")
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text="خطا در نوشتن فایل سوال.")

# ---------- کمکی برای حذف پیام بعد از تاخیر ----------
def delete_later(bot, chat_id: int, message_id: int, delay: int = AUTO_DELETE_SECONDS):
    async def _del():
        try:
            await asyncio.sleep(delay)
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
    try:
        asyncio.create_task(_del())
    except Exception:
        pass

# ---------- رد کردن نوبت (ادمین) ----------
async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        return await context.bot.send_message(chat_id=chat_id, text="فقط ادمین می‌تواند نوبت را رد کند.")
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    cur = current_player(chat_id)
    if not cur:
        return await context.bot.send_message(chat_id=chat_id, text="نوبتی وجود ندارد یا بازی شروع نشده.")
    # cancel watcher
    t = current_tasks.get(chat_id)
    if t:
        try:
            t.cancel()
        except Exception:
            pass
        current_tasks.pop(chat_id, None)
    g["awaiting"] = False
    save_state()
    try:
        member = await context.bot.get_chat_member(chat_id, cur)
        name = member.user.username and ("@" + member.user.username) or member.user.first_name
    except Exception:
        name = str(cur)
    await context.bot.send_message(chat_id=chat_id, text=f"⏭️ ادمین {get_player_mention(user)} نوبت {mention_html(cur, name)} را رد کرد.", parse_mode=ParseMode.HTML)
    write_log(chat_id, f"skip_by_admin {user.id} skipped {cur}")
    await asyncio.sleep(0.2)
    await do_next_turn(chat_id, context)

# ---------- جریان اصلی بازی ----------
async def do_next_turn(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    if not g["players"]:
        await context.bot.send_message(chat_id=chat_id, text="هیچ بازیکنی نیست. بازی متوقف می‌شود.")
        g["started"] = False
        save_state()
        return
    if not g.get("started"):
        return

    # advance to next player
    next_pid = next_player(chat_id)
    if next_pid is None:
        return
    # reset per-turn counters
    g["change_count"][str(next_pid)] = 0
    g["awaiting"] = True
    g["current_question"] = ""
    g["current_type"] = ""
    # clear any last prompt/question ids for safety
    g["last_prompt_msg_id"] = None
    g["last_group_msg_id"] = None
    save_state()

    # mention
    mention_name = str(next_pid)
    try:
        member = await context.bot.get_chat_member(chat_id, next_pid)
        mention_name = member.user.username and ("@" + member.user.username) or member.user.first_name
    except Exception:
        mention_name = str(next_pid)

    # group prompt (who's turn + choose)
    group_text = f"👤 نوبت: {mention_html(next_pid, mention_name)}\nشرکت‌کنندگان: {len(g['players'])}\nنوع سوال: انتخاب کن"
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔵 حقیقت (پسر/دختر)", callback_data=f"choose|truth|{next_pid}"),
          InlineKeyboardButton("🔴 جرأت (پسر/دختر)", callback_data=f"choose|dare|{next_pid}")],
         [InlineKeyboardButton("⏭️ رد نوبت (ادمین)", callback_data=f"admin|skip|{next_pid}")]]
    )
    try:
        msg = await context.bot.send_message(chat_id=chat_id, text=group_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        g["last_prompt_msg_id"] = msg.message_id
        save_state()
    except Exception:
        pass

    # cancel previous watcher
    prev = current_tasks.get(chat_id)
    if prev:
        try:
            prev.cancel()
        except Exception:
            pass

    # start timeout watcher
    async def watcher(target_pid: int):
        try:
            await asyncio.sleep(TURN_TIMEOUT)
            load_state()
            g_local = state.get("games", {}).get(str(chat_id))
            if g_local and g_local.get("started") and g_local.get("awaiting") and g_local.get("players"):
                try:
                    if g_local.get("players")[g_local.get("idx")] == target_pid:
                        # penalize
                        state["games"][str(chat_id)]["awaiting"] = False
                        add_score(target_pid, PENALTY_NO_ANSWER)
                        save_state()
                        try:
                            mem = await context.bot.get_chat_member(chat_id, target_pid)
                            name = mem.user.username and ("@" + mem.user.username) or mem.user.first_name
                        except:
                            name = str(target_pid)
                        try:
                            await context.bot.send_message(chat_id=chat_id, text=f"⏱ {mention_html(target_pid, name)} فرصت پاسخ را از دست داد — {PENALTY_NO_ANSWER} امتیاز.", parse_mode=ParseMode.HTML)
                        except Exception:
                            pass
                        await asyncio.sleep(0.3)
                        st2 = load_state()
                        # go to next
                        await do_next_turn(chat_id, context)
                except Exception:
                    pass
        except asyncio.CancelledError:
            return
        except Exception:
            return

    task = asyncio.create_task(watcher(next_pid))
    current_tasks[chat_id] = task

# ---------- callback handler (همه دکمه‌ها) ----------
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
            await join_cmd(update, context); return
        if sub == "leave":
            await leave_cmd(update, context); return
        if sub == "startgame":
            await startgame_cmd(update, context); return
        if sub == "stopgame":
            await stopgame_cmd(update, context); return
        if sub == "skip":
            await skip_cmd(update, context); return
        if sub == "leaderboard":
            await leaderboard_cmd(update, context); return
        if sub == "myid":
            await myid_cmd(update, context); return
        if sub == "rules":
            await rules_cmd(update, context); return
        if sub == "status":
            await status_cmd(update, context); return

    # choose|truth|<pid> یا choose|dare|<pid>
    if cmd == "choose":
        _type = parts[1] if len(parts) > 1 else ""
        target = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        chat_id = query.message.chat.id
        user = query.from_user
        init_game(chat_id)
        g = state["games"][str(chat_id)]
        try:
            cur = current_player(chat_id)
        except Exception:
            cur = None
        # verify turn
        if user.id != cur or target != cur:
            # nicer message: send ephemeral alert
            try:
                await query.answer("نوبت شما نیست یا این دکمه برای شما نیست.", show_alert=True)
            except:
                pass
            return
        # delete prompt message to prevent re-press
        try:
            if g.get("last_prompt_msg_id"):
                await context.bot.delete_message(chat_id=chat_id, message_id=g["last_prompt_msg_id"])
                g["last_prompt_msg_id"] = None
                save_state()
        except Exception:
            pass
        # ask category (boy/girl) in group (keeps it simple)
        if _type == "truth":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("حقیقت (پسر)", callback_data=f"set|truth_boy|{cur}"),
                 InlineKeyboardButton("حقیقت (دختر)", callback_data=f"set|truth_girl|{cur}")]
            ])
            await context.bot.send_message(chat_id=chat_id, text="کدام دسته؟", reply_markup=kb)
            return
        else:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("جرأت (پسر)", callback_data=f"set|dare_boy|{cur}"),
                 InlineKeyboardButton("جرأت (دختر)", callback_data=f"set|dare_girl|{cur}")]
            ])
            await context.bot.send_message(chat_id=chat_id, text="کدام دسته؟", reply_markup=kb)
            return

    # set|<qtype>|<pid> -> ارسال سوال در گروه (و حذف prompt قبلی)
    if cmd == "set":
        qtype = parts[1] if len(parts) > 1 else ""
        target = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        chat_id = query.message.chat.id
        user = query.from_user
        init_game(chat_id)
        g = state["games"][str(chat_id)]
        cur = current_player(chat_id)
        if cur is None or user.id != cur or target != cur:
            try:
                await query.answer("نوبت شما نیست.", show_alert=True)
            except:
                pass
            return
        # pick question trying to avoid last one for variety; also avoid full repetition using used_questions
        used = g.setdefault("used_questions", {}).setdefault(qtype, [])
        qs = load_questions(FILES.get(qtype, ""))
        if not qs:
            await context.bot.send_message(chat_id=chat_id, text="سوال موجود نیست؛ ادمین لطفا فایل سوال را کامل کنه.")
            return
        # choose avoiding both current_question and used list if possible
        candidate = None
        available = [q for q in qs if q not in used]
        if not available:
            # reset used
            g["used_questions"][qtype] = []
            available = qs[:]
        candidate = random.choice(available)
        # mark used
        g["used_questions"].setdefault(qtype, []).append(candidate)
        # limit used list size to qs len to avoid memory bloat
        if len(g["used_questions"][qtype]) > len(qs):
            g["used_questions"][qtype] = g["used_questions"][qtype][-len(qs):]
        # store
        g["current_question"] = candidate
        g["current_type"] = qtype
        g["awaiting"] = True
        save_state()
        # build group keyboard for answer/change/no
        group_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ پاسخ دادم", callback_data=f"resp|done|{target}"),
             InlineKeyboardButton("🔄 تغییر سوال", callback_data=f"resp|change|{target}")],
            [InlineKeyboardButton("🚫 پاسخ نمیدهم", callback_data=f"resp|no|{target}")]
        ])
        mention_name = user.username and ("@" + user.username) or user.first_name
        # send question into group and save id
        try:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"📝 سوال برای {mention_html(target, mention_name)}:\n\n{candidate}\n\n⏳ {TURN_TIMEOUT} ثانیه فرصت دارید.",
                reply_markup=group_kb,
                parse_mode=ParseMode.HTML
            )
            g["last_group_msg_id"] = msg.message_id
            save_state()
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=f"📝 سوال:\n{candidate}", reply_markup=group_kb)
        return

    # admin actions via callback admin|<action>|<pid>
    if cmd == "admin":
        action = parts[1] if len(parts) > 1 else ""
        target = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        chat_id = query.message.chat.id
        user = query.from_user
        if not is_admin(user.id):
            try:
                await query.answer("فقط ادمین می‌تواند این کار را انجام دهد.", show_alert=True)
            except:
                pass
            return
        if action == "skip":
            # emulate skip_cmd but from callback
            init_game(chat_id)
            g = state["games"][str(chat_id)]
            cur = current_player(chat_id)
            if not cur:
                return await context.bot.send_message(chat_id=chat_id, text="نوبتی وجود ندارد.")
            # cancel watcher
            t = current_tasks.get(chat_id)
            if t:
                try:
                    t.cancel()
                except:
                    pass
                current_tasks.pop(chat_id, None)
            g["awaiting"] = False
            save_state()
            try:
                tr_mem = await context.bot.get_chat_member(chat_id, cur)
                tr_name = tr_mem.user.username and ("@" + tr_mem.user.username) or tr_mem.user.first_name
            except:
                tr_name = str(cur)
            await context.bot.send_message(chat_id=chat_id, text=f"⏭️ ادمین {get_player_mention(user)} نوبت {mention_html(cur, tr_name)} را رد کرد.", parse_mode=ParseMode.HTML)
            write_log(chat_id, f"admin_skip {user.id} skipped {cur}")
            await asyncio.sleep(0.2)
            await do_next_turn(chat_id, context)
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
            except:
                pass
            return

        # find the chat where this player is currently awaiting (usually current chat)
        game_chat_id = query.message.chat.id
        init_game(game_chat_id)
        g = state["games"][str(game_chat_id)]
        # ensure that this chat indeed has awaiting and current player matches
        cur = current_player(game_chat_id)
        if cur is None or cur != user.id or not g.get("awaiting"):
            try:
                await query.answer("وضعیت بازی برای این نوبت منقضی شده یا نوبت شما نیست.", show_alert=True)
            except:
                pass
            return

        # cancel watcher
        t = current_tasks.get(game_chat_id)
        if t:
            try:
                t.cancel()
            except:
                pass
            current_tasks.pop(game_chat_id, None)

        if action == "done":
            qtype = g.get("current_type", "")
            if qtype and qtype.startswith("dare"):
                add_score(user.id, SCORE_DARE)
                pts = SCORE_DARE
            else:
                add_score(user.id, SCORE_TRUTH)
                pts = SCORE_TRUTH
            g["awaiting"] = False
            save_state()
            # announce and cleanup question message
            try:
                await context.bot.send_message(chat_id=game_chat_id, text=f"✅ {mention_html(user.id, user.first_name)} پاسخ داد — +{pts} امتیاز.", parse_mode=ParseMode.HTML)
            except:
                pass
            try:
                if g.get("last_group_msg_id"):
                    await context.bot.delete_message(chat_id=game_chat_id, message_id=g["last_group_msg_id"])
                    g["last_group_msg_id"] = None
                    save_state()
            except:
                pass
            await asyncio.sleep(0.2)
            await do_next_turn(game_chat_id, context)
            return

        if action == "no":
            add_score(user.id, PENALTY_NO_ANSWER)
            g["awaiting"] = False
            save_state()
            try:
                await context.bot.send_message(chat_id=game_chat_id, text=f"⛔ {mention_html(user.id, user.first_name)} پاسخ نداد/نخواست — {PENALTY_NO_ANSWER} امتیاز.", parse_mode=ParseMode.HTML)
            except:
                pass
            try:
                if g.get("last_group_msg_id"):
                    await context.bot.delete_message(chat_id=game_chat_id, message_id=g["last_group_msg_id"])
                    g["last_group_msg_id"] = None
                    save_state()
            except:
                pass
            await asyncio.sleep(0.2)
            await do_next_turn(game_chat_id, context)
            return

        if action == "change":
            cnt = g["change_count"].get(str(user.id), 0)
            if cnt >= MAX_CHANGES_PER_TURN:
                await context.bot.send_message(chat_id=game_chat_id, text="⚠️ دیگر نمی‌توانید سوال را تغییر دهید.")
                return
            qtype = g.get("current_type", "")
            if not qtype:
                await context.bot.send_message(chat_id=game_chat_id, text="نوع سوال نامشخص است.")
                return
            qs = load_questions(FILES.get(qtype, ""))
            if not qs:
                await context.bot.send_message(chat_id=game_chat_id, text="سوال موجود نیست؛ ادمین کاملش کنه.")
                return
            # choose new avoiding current_question
            q_new = _choose_avoiding(qs, g.get("current_question", ""))
            g["current_question"] = q_new
            g["change_count"][str(user.id)] = cnt + 1
            save_state()
            # edit last question message if exists
            try:
                if g.get("last_group_msg_id"):
                    await context.bot.edit_message_text(
                        chat_id=game_chat_id,
                        message_id=g["last_group_msg_id"],
                        text=f"📝 سوال جدید برای {mention_html(user.id, user.first_name)}:\n\n{q_new}\n(تغییر: {g['change_count'][str(user.id)]}/{MAX_CHANGES_PER_TURN})\n⏳ {TURN_TIMEOUT} ثانیه فرصت دارید.",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    msg = await context.bot.send_message(chat_id=game_chat_id, text=f"📝 سوال جدید:\n{q_new}")
                    g["last_group_msg_id"] = msg.message_id
                    save_state()
            except Exception:
                await context.bot.send_message(chat_id=game_chat_id, text=f"📝 سوال جدید:\n{q_new}")
            # restart watcher for this chat
            async def restart_watch():
                try:
                    await asyncio.sleep(TURN_TIMEOUT)
                    load_state()
                    gl = state.get("games", {}).get(str(game_chat_id))
                    if gl and gl.get("started") and gl.get("awaiting"):
                        gl["awaiting"] = False
                        add_score(user.id, PENALTY_NO_ANSWER)
                        save_state()
                        try:
                            mem = await context.bot.get_chat_member(game_chat_id, user.id)
                            name = mem.user.username and ("@" + mem.user.username) or mem.user.first_name
                        except:
                            name = str(user.id)
                        try:
                            await context.bot.send_message(chat_id=game_chat_id, text=f"⏱ {mention_html(user.id, name)} فرصت پاسخ را از دست داد — {PENALTY_NO_ANSWER} امتیاز.", parse_mode=ParseMode.HTML)
                        except:
                            pass
                        await asyncio.sleep(0.2)
                        await do_next_turn(game_chat_id, context)
                except asyncio.CancelledError:
                    return
            t = asyncio.create_task(restart_watch())
            current_tasks[game_chat_id] = t
            return

    # default fallback
    try:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="عملیات ناشناخته یا منقضی شده.")
    except Exception:
        pass

# ---------- rules ----------
async def rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = (
        "🎯 راهنمای بازی جرأت یا حقیقت 🎯\n\n"
        "1️⃣ برای ورود به بازی، دکمه 🎯 پیوستن به بازی رو بزنید.\n"
        "2️⃣ فقط ادمین می‌تونه بازی رو شروع یا متوقف کنه.\n"
        "3️⃣ وقتی نوبت شما شد، بین حقیقت یا جرأت انتخاب کنید.\n"
        "4️⃣ هر سوال رو می‌تونید تا ۲ بار تغییر بدید.\n"
        f"5️⃣ +{SCORE_DARE} امتیاز برای جرأت، +{SCORE_TRUTH} امتیاز برای حقیقت، و {PENALTY_NO_ANSWER} امتیاز اگر جواب ندید.\n"
        "6️⃣ بازی به‌صورت نوبت تصادفی بین بازیکنان انجام می‌شه.\n"
        "7️⃣ جدول امتیازات رو می‌تونید از منو یا دستور /leaderboard ببینید.\n\n"
        "🔔 نکات مهم:\n"
        "- اگر نوبت شما نیست روی منو یا دکمه‌ها نزنید.\n"
        "- هنگام بازی از چت کردن و پیام بی‌ربط خودداری کنید تا گپ شلوغ نشه.\n"
        "- پاسخ‌هاتون رو **روی پیام ربات** که سوال رو ارسال کرده ریپلای کنید یا از دکمه‌ها استفاده کنید.\n"
        "- اگر به سوال پاسخ ندادید یا دکمه «پاسخ دادم» رو به درستی نزنید، امتیاز منفی خواهید گرفت."
    )
    await context.bot.send_message(chat_id=chat_id, text=text)

# ---------- leaderboard handler ----------
async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    items = get_leaderboard(10)
    if not items:
        return await context.bot.send_message(chat_id=chat_id, text="هیچ امتیازی ثبت نشده.")
    lines = ["🏆 جدول امتیازات:"]
    i = 1
    for uid, sc in items:
        mention = str(uid)
        try:
            member = await context.bot.get_chat_member(chat_id, int(uid))
            mention = member.user.username and ("@" + member.user.username) or member.user.first_name
        except Exception:
            mention = str(uid)
        lines.append(f"{i}. {mention} — {sc}")
        i += 1
    await context.bot.send_message(chat_id=chat_id, text="\n".join(lines))

# ---------- admin start/stop ----------
async def startgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        return await context.bot.send_message(chat_id=chat_id, text="فقط ادمین می‌تواند بازی را شروع کند.")
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    if not g["players"]:
        return await context.bot.send_message(chat_id=chat_id, text="هیچ بازیکنی نیست. لطفاً /join کنید.")
    # shuffle players for random order
    random.shuffle(g["players"])
    g["started"] = True
    g["idx"] = -1
    g["change_count"] = {str(uid): 0 for uid in g["players"]}
    save_state()
    await context.bot.send_message(chat_id=chat_id, text=f"🎮 بازی شروع شد — شرکت‌کنندگان: {len(g['players'])}")
    write_log(chat_id, f"start_by {user.id}")
    await asyncio.sleep(0.2)
    await do_next_turn(chat_id, context)

async def stopgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        return await context.bot.send_message(chat_id=chat_id, text="فقط ادمین می‌تواند بازی را متوقف کند.")
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    g["started"] = False
    g["awaiting"] = False
    save_state()
    t = current_tasks.get(chat_id)
    if t:
        try:
            t.cancel()
        except Exception:
            pass
        current_tasks.pop(chat_id, None)
    try:
        if g.get("last_group_msg_id"):
            await context.bot.delete_message(chat_id=chat_id, message_id=g["last_group_msg_id"])
            g["last_group_msg_id"] = None
            save_state()
    except Exception:
        pass
    await context.bot.send_message(chat_id=chat_id, text="⏹ بازی متوقف شد.")
    write_log(chat_id, f"stop_by {user.id}")

# ---------- main bootstrap ----------
def main():
    load_state()
    ensure_data_folder()
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
    app.add_handler(CommandHandler("skip", skip_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("addq", addq_cmd))
    app.add_handler(CommandHandler("delq", delq_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("queue", queue_cmd))
    app.add_handler(CommandHandler("rules", rules_cmd))

    # callback queries (all)
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
