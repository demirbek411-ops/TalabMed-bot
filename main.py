import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

TOKEN = os.environ["BOT_TOKEN"]

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
        await msg.answer("Xush kelibsiz! 🎉")


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
        await cb.message.edit_text("Rahmat! Endi botdan foydalanishingiz mumkin ✅")
        await cb.answer()


async def health(request):
    return web.Response(text="OK")


async def main():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()
    await dp.start_polling(bot)


asyncio.run(main())
