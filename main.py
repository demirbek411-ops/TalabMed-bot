import os
import hmac
import json
import time
import hashlib
import asyncio
from urllib.parse import parse_qsl
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, MenuButtonWebApp,
)

TOKEN = "".join(os.environ["BOT_TOKEN"].split())

SITE_URL = "https://demirbek411-ops.github.io/TalabaMed-site/"
SITE_ORIGIN = "https://demirbek411-ops.github.io"

WELCOME_TEXT = (
    "Xush kelibsiz! 🎉\n\n"
    "Saytni ochish uchun pastdagi «Ilovani Ochish» tugmasini bosing."
)

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


async def send_main(chat_id):
    if os.path.exists("welcome.jpg"):
        await bot.send_photo(chat_id, FSInputFile("welcome.jpg"), caption=WELCOME_TEXT)
    else:
        await bot.send_message(chat_id, WELCOME_TEXT)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🌐 Saytni ochish", web_app=WebAppInfo(url=SITE_URL))
    ]])
    await bot.send_message(chat_id, "Saytni ochish uchun tugmani bosing.", reply_markup=kb)

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


@dp.message(CommandStart())
async def start(msg: Message):
    left = await not_subscribed(msg.from_user.id)
    if left:
        await msg.answer(
            "Botdan foydalanish uchun quyidagilarga obuna bo'ling, "
            "so'ng «Tekshirish» tugmasini bosing:",
            reply_markup=sub_keyboard(left),
        )
    else:
        await send_main(msg.chat.id)


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


# ---------- Sayt uchun obuna tekshiruvi ----------

def user_from_init_data(init_data):
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
    left = await not_subscribed(user["id"])
    missing = [{"name": n, "url": f"https://t.me/{u[1:]}"} for n, u in left]
    return web.json_response({"ok": not left, "missing": missing})


async def health(request):
    return web.Response(text="OK")


async def main():
    app = web.Application(middlewares=[cors_mw])
    app.router.add_get("/", health)
    app.router.add_route("*", "/api/check", api_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()
    await dp.start_polling(bot)


asyncio.run(main())
