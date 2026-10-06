import os
import hmac
import json
import time
import hashlib
import asyncio
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qsl, quote
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove, BotCommand,
    WebAppInfo, MenuButtonWebApp,
)

TOKEN = "".join(os.environ["BOT_TOKEN"].split())

SITE_URL = "https://demirbek411-ops.github.io/TalabaMed-site/"
SITE_ORIGIN = "https://demirbek411-ops.github.io"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = "".join(os.environ.get("SUPABASE_KEY", "").split())
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)
TZ = timezone(timedelta(hours=5))  # Toshkent vaqti

# Kitoblar saytining havolasi (https://...). Bo'sh bo'lsa "tez orada" deb yoziladi.
BOOKS_URL = ""

CONTACT = "@Demirbek_17_09"

WELCOME_TEXT = (
    "🩺 TALABA MED: tibbiyot talabasi uchun test ilovasi\n\n"
    "Imtihon oldidan faqat darslik emas, o'zingizni sinab ko'rish ham kerak. 📲\n\n"
    "🔹 O'zbek va rus potoklari uchun yakuniy testlar ham bor: Gistologiya, Anatomiya, Psixologiya (3000 dan ortiq test)\n"
    "🔹 Imtihon rejimi: 20 ta test, 10 daqiqa, natija foiz va ballda\n"
    "🔹 Xatolarni takrorlash va tasodifiy testlar\n"
    "🔹 Gistologiya seminar mashg'ulotlari: mavzular bo'yicha vaziyatli testlar\n"
    "🔹 Anatomiya va Psixologiya yozma ish biletlari\n"
    "🔹 Ilova ikki tilda ishlaydi: UZ | RU\n\n"
    "Vaqtingizni material qidirishga emas, tayyorgarlikka sarflang. 💪\n\n"
    "👉 Boshlash uchun pastdagi «Ilovani Ochish» tugmasini bosing."
)

ABOUT_TEXT = (
    "ℹ️ Bot haqida\n\n"
    "TALABA MED tibbiyot talabalari uchun yaratilgan. Bot orqali ilovani ochib, "
    "o'zbek va rus potoklari uchun yakuniy fanlar testlari, imtihon rejimi, xatolarni takrorlash va yozma ish biletlaridan foydalanasiz.\n\n"
    "Ilova uchun uchala kanal/guruhga obuna bo'lish shart. Fikr va takliflaringizni "
    "menyudagi «💬 Fikr bildirish» tugmasi orqali yuboring."
)

feedback_mode = {}   # user_id -> "anon" | "named" | "choose"
last_feedback = {}   # user_id -> oxirgi yuborilgan vaqt

CHANNELS = [
    ("📢 Talaba Med", "@TalabaMed_2025"),
    ("📚 MedEdu", "@MedEdu_uz"),
    ("💬 Talaba Med dars (guruh)", "@talabamed_dars"),
]

bot = Bot(TOKEN)
dp = Dispatcher()


async def not_subscribed(user_id):
    result = []
    for name, username in CHANNELS:
        try:
            m = await bot.get_chat_member(username, user_id)
            if m.status in ("left", "kicked"):
                result.append((name, username))
            elif m.status == "restricted" and not m.is_member:
                result.append((name, username))
        except Exception as e:
            print("Xato:", username, e)
            result.append((name, username))
    return result


def sub_keyboard(channels):
    rows = [
        [InlineKeyboardButton(text=n, url=f"https://t.me/{u[1:]}")]
        for n, u in channels
    ]
    rows.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def app_keyboard(url, text="🌐 Saytni ochish"):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))
    ]])


def inline_menu():
    books = (
        InlineKeyboardButton(text="📚 Kitoblar", web_app=WebAppInfo(url=BOOKS_URL))
        if BOOKS_URL else
        InlineKeyboardButton(text="📚 Kitoblar", callback_data="m_books")
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Ilovani ochish", web_app=WebAppInfo(url=SITE_URL))],
        [books, InlineKeyboardButton(text="ℹ️ Bot haqida", callback_data="m_about")],
        [InlineKeyboardButton(text="📢 Kanallar", callback_data="m_channels"),
         InlineKeyboardButton(text="📞 Aloqa", url=f"https://t.me/{CONTACT[1:]}")],
        [InlineKeyboardButton(text="💬 Fikr bildirish", callback_data="m_feedback")],
    ])


async def clear_old_keyboard(chat_id):
    """Oldingi versiyadan qolgan pastdagi tugmalar panelini olib tashlaydi."""
    try:
        m = await bot.send_message(chat_id, "⏳", reply_markup=ReplyKeyboardRemove())
        await m.delete()
    except Exception:
        pass


async def send_main(chat_id):
    await clear_old_keyboard(chat_id)
    if os.path.exists("welcome.jpg"):
        await bot.send_photo(chat_id, FSInputFile("welcome.jpg"), caption=WELCOME_TEXT, reply_markup=inline_menu())
    else:
        await bot.send_message(chat_id, WELCOME_TEXT, reply_markup=inline_menu())

    try:
        await bot.set_chat_menu_button(
            chat_id=chat_id,
            menu_button=MenuButtonWebApp(
                text="Ilovani Ochish",
                web_app=WebAppInfo(url=SITE_URL),
            ),
        )
    except Exception as e:
        print("Menu tugma xatosi:", e)


# ---------- Foydalanuvchilarni hisoblash (Supabase) ----------

def db_headers(extra=None):
    h = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    if SUPABASE_KEY.startswith("eyJ"):
        h["Authorization"] = f"Bearer {SUPABASE_KEY}"
    if extra:
        h.update(extra)
    return h


async def save_user(user_id, first_name, username):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    row = {
        "user_id": user_id,
        "first_name": first_name,
        "username": username,
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{SUPABASE_URL}/rest/v1/bot_users?on_conflict=user_id",
                headers=db_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                json=row,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status >= 300:
                    print("DB xato:", r.status, await r.text())
    except Exception as e:
        print("DB xatosi:", e)


async def db_count(column=None, since=None):
    url = f"{SUPABASE_URL}/rest/v1/bot_users?select=user_id"
    if column and since:
        url += f"&{column}=gte." + quote(since.isoformat(), safe="")
    async with aiohttp.ClientSession() as s:
        async with s.get(
            url,
            headers=db_headers({"Prefer": "count=exact", "Range": "0-0"}),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            return int(r.headers.get("Content-Range", "*/0").split("/")[-1])


@dp.message(Command("stats"))
async def stats(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    if not SUPABASE_URL or not SUPABASE_KEY:
        await msg.answer("Baza ulanmagan (SUPABASE_URL / SUPABASE_KEY yo'q).")
        return
    try:
        now = datetime.now(TZ)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week = today - timedelta(days=6)
        total = await db_count()
        new_today = await db_count("first_seen", today)
        active_today = await db_count("last_seen", today)
        new_week = await db_count("first_seen", week)
        await msg.answer(
            "📊 Statistika\n\n"
            f"👥 Jami foydalanuvchi: {total}\n"
            f"🆕 Bugun yangi: {new_today}\n"
            f"🔥 Bugun faol: {active_today}\n"
            f"📅 Oxirgi 7 kunda yangi: {new_week}"
        )
    except Exception as e:
        print("stats xatosi:", e)
        await msg.answer("Statistikani olishda xatolik. Loglarni tekshiring.")


@dp.message(CommandStart())
async def start(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    await save_user(msg.from_user.id, msg.from_user.first_name, msg.from_user.username)
    left = await not_subscribed(msg.from_user.id)
    if left:
        await msg.answer(
            "Botdan foydalanish uchun quyidagilarga obuna bo'ling, "
            "so'ng «Tekshirish» tugmasini bosing:",
            reply_markup=sub_keyboard(left),
        )
    else:
        await send_main(msg.chat.id)


@dp.message(Command("menu"))
async def menu_cmd(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    await msg.answer("📋 Menyu:", reply_markup=inline_menu())


@dp.callback_query(F.data == "check")
async def check(cb: CallbackQuery):
    left = await not_subscribed(cb.from_user.id)
    if left:
        await cb.answer("Hali hammasiga obuna bo'lmadingiz!", show_alert=True)
        try:
            await cb.message.edit_reply_markup(reply_markup=sub_keyboard(left))
        except Exception:
            pass
    else:
        await cb.answer()
        try:
            await cb.message.delete()
        except Exception:
            pass
        await send_main(cb.message.chat.id)


# ---------- Menyu tugmalari ----------

@dp.callback_query(F.data == "m_books")
async def m_books(cb: CallbackQuery):
    await cb.answer("📚 Kitoblar bo'limi tez orada ochiladi!", show_alert=True)


@dp.callback_query(F.data == "m_about")
async def m_about(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer(ABOUT_TEXT)


@dp.callback_query(F.data == "m_channels")
async def m_channels(cb: CallbackQuery):
    await cb.answer()
    rows = [[InlineKeyboardButton(text=n, url=f"https://t.me/{u[1:]}")] for n, u in CHANNELS]
    await cb.message.answer("📢 Bizning kanal va guruhlar:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data == "m_feedback")
async def m_feedback(cb: CallbackQuery):
    await cb.answer()
    feedback_mode[cb.from_user.id] = "choose"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕶 Anonim yuborish", callback_data="fb_anon")],
        [InlineKeyboardButton(text="👤 Ismim bilan yuborish", callback_data="fb_named")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="fb_cancel")],
    ])
    await cb.message.answer(
        "💬 Bot haqida fikringizni bildiring.\n\n"
        "Anonim yuborsangiz, sizning ismingiz va akkauntingiz egasiga ko'rsatilmaydi. "
        "Qanday yuborasiz?",
        reply_markup=kb,
    )


@dp.callback_query(F.data.in_({"fb_anon", "fb_named", "fb_cancel"}))
async def fb_choice(cb: CallbackQuery):
    uid = cb.from_user.id
    if cb.data == "fb_cancel":
        feedback_mode.pop(uid, None)
        await cb.answer("Bekor qilindi")
        try:
            await cb.message.delete()
        except Exception:
            pass
        return
    feedback_mode[uid] = "anon" if cb.data == "fb_anon" else "named"
    await cb.answer()
    how = "anonim" if cb.data == "fb_anon" else "ismingiz bilan"
    try:
        await cb.message.edit_text(f"✍️ Fikringizni bitta xabar qilib yozing ({how} yuboriladi).\nBekor qilish uchun /menu ni bosing.")
    except Exception:
        pass


@dp.message(F.text & ~F.text.startswith("/"))
async def feedback_text(msg: Message):
    uid = msg.from_user.id
    mode = feedback_mode.get(uid)
    if mode not in ("anon", "named"):
        return
    if not ADMIN_ID:
        feedback_mode.pop(uid, None)
        await msg.answer("Fikr qabul qilish hozircha ishlamayapti.")
        return
    now = time.time()
    if now - last_feedback.get(uid, 0) < 30:
        await msg.answer("Iltimos, biroz kutib, keyin yuboring.")
        return
    text = msg.text.strip()[:1500]
    if mode == "anon":
        head = "💬 Yangi fikr (anonim)"
    else:
        u = msg.from_user
        name = " ".join(x for x in [u.first_name, u.last_name] if x) or "Ism yo'q"
        uname = f" @{u.username}" if u.username else ""
        head = f"💬 Yangi fikr\n👤 {name}{uname} (ID: {u.id})"
    try:
        await bot.send_message(ADMIN_ID, f"{head}\n\n{text}")
    except Exception as e:
        print("Fikrni yuborishda xato:", e)
        await msg.answer("Yuborib bo'lmadi, keyinroq urinib ko'ring.")
        return
    last_feedback[uid] = now
    feedback_mode.pop(uid, None)
    await msg.answer("✅ Rahmat! Fikringiz yuborildi.")


# ---------- Sayt uchun obuna tekshiruvi ----------

def user_from_init_data(init_data):
    """Telegram initData imzosini tekshiradi va foydalanuvchini qaytaradi."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received = pairs.pop("hash", None)
        if not received:
            return None
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > 86400:
            return None
        return json.loads(pairs["user"])
    except Exception as e:
        print("initData xatosi:", e)
        return None


@web.middleware
async def cors_mw(request, handler):
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = SITE_ORIGIN
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


async def api_check(request):
    if request.method == "OPTIONS":
        return web.Response()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)
    user = user_from_init_data(body.get("initData", ""))
    if not user:
        return web.json_response({"ok": False, "error": "invalid"}, status=403)
    await save_user(user["id"], user.get("first_name"), user.get("username"))
    left = await not_subscribed(user["id"])
    missing = [{"name": n, "url": f"https://t.me/{u[1:]}"} for n, u in left]
    return web.json_response({"ok": not left, "missing": missing})


async def health(request):
    return web.Response(text="OK")


async def main():
    app = web.Application(middlewares=[cors_mw])
    app.router.add_get("/", health)
    app.router.add_route("*", "/api/check", api_check)
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Boshlash"),
            BotCommand(command="menu", description="Menyu"),
        ])
    except Exception as e:
        print("Buyruqlar xatosi:", e)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()
    await dp.start_polling(bot)


asyncio.run(main())
