import os
import hmac
import json
import time
import hashlib
import asyncio
import random
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qsl, quote
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ChatMemberUpdated,
    WebAppInfo, MenuButtonWebApp,
)

TOKEN = "".join(os.environ["BOT_TOKEN"].split())

SITE_URL = "https://demirbek411-ops.github.io/TalabaMed-site/"
SITE_ORIGIN = "https://demirbek411-ops.github.io"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = "".join(os.environ.get("SUPABASE_KEY", "").split())
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)
TZ = timezone(timedelta(hours=5))  # Toshkent vaqti

SCHEDULE_URL = "https://demirbek411-ops.github.io/Dars-jadvali-/"

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
    "👉 Boshlash uchun pastdagi «Ilovani Ochish» tugmasini yoki ▦ menyuni bosing."
)

ABOUT_TEXT = (
    "ℹ️ Bot haqida\n\n"
    "TALABA MED tibbiyot talabalari uchun yaratilgan. Bot orqali ilovani ochib, "
    "o'zbek va rus potoklari uchun yakuniy fanlar testlari, imtihon rejimi, xatolarni takrorlash va yozma ish biletlaridan foydalanasiz.\n\n"
    "Ilova uchun uchala kanal/guruhga obuna bo'lish shart. Fikr va takliflaringizni "
    "«💬 Fikr bildirish» tugmasi orqali yuboring."
)

BTN_APP = "🌐 Ilovani ochish"
BTN_SCHEDULE = "🗓 Dars jadvali"
BTN_ABOUT = "ℹ️ Bot haqida"
BTN_CHANNELS = "📢 Kanallar"
BTN_CONTACT = "📞 Aloqa"
BTN_FEEDBACK = "💬 Fikr bildirish"
BTN_ORALIQ = "📝 Oraliqlar"
BTN_BACK = "⬅️ Orqaga"
BTN_STREAK = "🔥 Seriyam"
BTN_RATING = "🏆 Reyting"

ORALIQ_PREFIX = "oraliq_"      # PDF fayl nomi shu so'z bilan boshlanishi kerak
FILE_PREFIX = "📄 "

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_APP), KeyboardButton(text=BTN_SCHEDULE)],
        [KeyboardButton(text=BTN_ABOUT), KeyboardButton(text=BTN_CHANNELS)],
        [KeyboardButton(text=BTN_CONTACT), KeyboardButton(text=BTN_FEEDBACK)],
        [KeyboardButton(text=BTN_ORALIQ), KeyboardButton(text=BTN_STREAK)],
        [KeyboardButton(text=BTN_RATING)],
    ],
    resize_keyboard=True,
)

feedback_mode = {}   # user_id -> "anon" | "named" | "choose"
last_feedback = {}   # user_id -> oxirgi yuborilgan vaqt

CHANNELS = [
    ("📢 Talaba Med", "@TalabaMed_2025"),
    ("📚 MedEdu", "@MedEdu_uz"),
    ("💬 Talaba Med dars (guruh)", "@talabamed_dars"),
]

# Majburiy emas, faqat tavsiya: kanallar ro'yxati ustidagi matnga qo'shiladi
OPTIONAL_CHANNEL_NOTE = (
    "ℹ️ Adminlarimizdan birining kanali: https://t.me/Edits_foto (qo'shilish ixtiyoriy)"
)

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


async def send_main(chat_id):
    if os.path.exists("welcome.jpg"):
        await bot.send_photo(chat_id, FSInputFile("welcome.jpg"), caption=WELCOME_TEXT, reply_markup=MENU)
    else:
        await bot.send_message(chat_id, WELCOME_TEXT, reply_markup=MENU)

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


async def save_user(user_id, first_name, username, is_member=None):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    row = {
        "user_id": user_id,
        "first_name": first_name,
        "username": username,
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }
    if is_member is not None:
        row["is_member"] = is_member
        row["left_at"] = None if is_member else datetime.now(timezone.utc).isoformat()
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


async def db_count(column=None, since=None, extra=""):
    url = f"{SUPABASE_URL}/rest/v1/bot_users?select=user_id{extra}"
    if column and since:
        url += f"&{column}=gte." + quote(since.isoformat(), safe="")
    async with aiohttp.ClientSession() as s:
        async with s.get(
            url,
            headers=db_headers({"Prefer": "count=exact", "Range": "0-0"}),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            return int(r.headers.get("Content-Range", "*/0").split("/")[-1])


# ---------- Obunadan chiqqanlarni aniqlash ----------

async def get_flag(user_id):
    """Bazadagi is_member qiymati: True / False / None (noma'lum)."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{SUPABASE_URL}/rest/v1/bot_users?select=is_member&user_id=eq.{user_id}",
                headers=db_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                data = await r.json()
                if data:
                    return data[0].get("is_member")
    except Exception as e:
        print("get_flag xatosi:", e)
    return None


async def patch_user(user_id, fields):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.patch(
                f"{SUPABASE_URL}/rest/v1/bot_users?user_id=eq.{user_id}",
                headers=db_headers({"Prefer": "return=minimal"}),
                json=fields,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status >= 300:
                    print("DB patch xato:", r.status, await r.text())
    except Exception as e:
        print("patch_user xatosi:", e)


async def warn_left(user_id, left):
    names = ", ".join(n for n, _ in left)
    try:
        await bot.send_message(
            user_id,
            "⚠️ Siz quyidagilardan chiqib ketdingiz:\n" + names + "\n\n"
            "Shu sababli ilova va yangi fayllardan foydalanish yopildi. "
            "Davom etish uchun qayta obuna bo'ling va «Tekshirish» tugmasini bosing:",
            reply_markup=sub_keyboard(left),
        )
    except Exception as e:
        print("Ogohlantirish yuborilmadi:", user_id, e)


async def recheck_user(user_id, flag):
    """Obunani qayta tekshiradi, bazani yangilaydi, chiqib ketgan bo'lsa ogohlantiradi."""
    left = await not_subscribed(user_id)
    now = not left
    if flag is not now:
        await patch_user(user_id, {
            "is_member": now,
            "left_at": None if now else datetime.now(timezone.utc).isoformat(),
        })
    if flag is True and not now:
        await warn_left(user_id, left)


@dp.chat_member()
async def on_member_change(ev: ChatMemberUpdated):
    uname = ("@" + (ev.chat.username or "")).lower()
    if uname not in [u.lower() for _, u in CHANNELS]:
        return
    old, new = ev.old_chat_member.status, ev.new_chat_member.status
    if new in ("left", "kicked") and old not in ("left", "kicked"):
        uid = ev.new_chat_member.user.id
        flag = await get_flag(uid)
        await recheck_user(uid, flag)


async def sweep_once():
    """Bazadagi hammani aylanib chiqadi (har birini ~0.2 soniyada)."""
    offset = 0
    while True:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{SUPABASE_URL}/rest/v1/bot_users?select=user_id,is_member&order=user_id.asc&limit=500&offset={offset}",
                headers=db_headers(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                rows = await r.json()
        if not rows:
            break
        for row in rows:
            try:
                await recheck_user(row["user_id"], row.get("is_member"))
            except Exception as e:
                print("sweep xatosi:", e)
            await asyncio.sleep(0.2)
        offset += 500


async def sweep_loop():
    await asyncio.sleep(300)
    while True:
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                await sweep_once()
            except Exception as e:
                print("sweep_once xatosi:", e)
        await asyncio.sleep(6 * 3600)


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
        members = await db_count(extra="&is_member=eq.true")
        left_n = await db_count(extra="&is_member=eq.false")
        await msg.answer(
            "📊 Statistika\n\n"
            f"👥 Jami foydalanuvchi: {total}\n"
            f"🆕 Bugun yangi: {new_today}\n"
            f"🔥 Bugun faol: {active_today}\n"
            f"📅 Oxirgi 7 kunda yangi: {new_week}\n\n"
            f"✅ Hozir obunada: {members}\n"
            f"🚪 Obunasiz (chiqib ketgan yoki hali obuna bo'lmagan): {left_n}"
        )
    except Exception as e:
        print("stats xatosi:", e)
        await msg.answer("Statistikani olishda xatolik. Loglarni tekshiring.")


@dp.message(Command("dbtest"))
async def dbtest(msg: Message):
    """Admin uchun: bazaga ulanishni tekshiradi (kalitni ko'rsatmaydi)."""
    if msg.from_user.id != ADMIN_ID:
        return
    if not SUPABASE_URL or not SUPABASE_KEY:
        await msg.answer("SUPABASE_URL yoki SUPABASE_KEY bo'sh.")
        return
    host = SUPABASE_URL.replace("https://", "").replace("http://", "")
    if SUPABASE_KEY.startswith("sb_secret_"):
        ktype = "sb_secret (to'g'ri)"
    elif SUPABASE_KEY.startswith("sb_publishable_"):
        ktype = "sb_publishable (NOTO'G'RI, secret kerak)"
    elif SUPABASE_KEY.startswith("eyJ"):
        ktype = "eyJ (JWT: anon yoki service_role bo'lishi mumkin)"
    else:
        ktype = "noma'lum ko'rinish"
    lines = [f"URL: {host}", f"Kalit turi: {ktype}", ""]
    for table in ("bot_users", "streaks"):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{SUPABASE_URL}/rest/v1/{table}?select=*&limit=1",
                    headers=db_headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    body = (await r.text())[:200]
                    lines.append(f"{table}: HTTP {r.status}")
                    if r.status >= 300:
                        lines.append(body)
        except Exception as e:
            lines.append(f"{table}: xato {e}")
    await msg.answer("\n".join(lines))


@dp.message(CommandStart())
async def start(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    left = await not_subscribed(msg.from_user.id)
    await save_user(msg.from_user.id, msg.from_user.first_name, msg.from_user.username, not left)
    if left:
        await msg.answer(
            "Botdan foydalanish uchun quyidagilarga obuna bo'ling, "
            "so'ng «Tekshirish» tugmasini bosing:\n\n" + OPTIONAL_CHANNEL_NOTE,
            reply_markup=sub_keyboard(left),
        )
    else:
        await send_main(msg.chat.id)


@dp.message(Command("menu"))
async def menu_cmd(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    await msg.answer("📋 Menyu pastda. Yopish uchun telefondagi orqaga tugmasini yoki ▦ ni bosing.", reply_markup=MENU)


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
        await save_user(cb.from_user.id, cb.from_user.first_name, cb.from_user.username, True)
        try:
            await cb.message.delete()
        except Exception:
            pass
        await send_main(cb.message.chat.id)


# ---------- Pastdagi tugmalar paneli ----------

async def need_subscribe(msg: Message):
    """Obuna bo'lmagan bo'lsa, so'rov yuboradi va True qaytaradi."""
    left = await not_subscribed(msg.from_user.id)
    if left:
        await msg.answer(
            "Avval quyidagilarga obuna bo'ling, so'ng «Tekshirish» tugmasini bosing:\n\n"
            + OPTIONAL_CHANNEL_NOTE,
            reply_markup=sub_keyboard(left),
        )
        return True
    return False


@dp.message(F.text == BTN_APP)
async def btn_app(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    if await need_subscribe(msg):
        return
    await msg.answer("Ilovani ochish uchun tugmani bosing.", reply_markup=app_keyboard(SITE_URL))


@dp.message(F.text == BTN_SCHEDULE)
async def btn_schedule(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    if await need_subscribe(msg):
        return
    await msg.answer("🗓 Dars jadvalini ochish uchun tugmani bosing.",
                     reply_markup=app_keyboard(SCHEDULE_URL, "🗓 Dars jadvalini ochish"))


@dp.message(F.text == BTN_ABOUT)
async def btn_about(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    await msg.answer(ABOUT_TEXT)


@dp.message(F.text == BTN_CHANNELS)
async def btn_channels(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    rows = [[InlineKeyboardButton(text=n, url=f"https://t.me/{u[1:]}")] for n, u in CHANNELS]
    await msg.answer(
        "📢 Bizning kanal va guruhlar:\n\n" + OPTIONAL_CHANNEL_NOTE,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.message(F.text == BTN_CONTACT)
async def btn_contact(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✉️ Yozish", url=f"https://t.me/{CONTACT[1:]}")
    ]])
    await msg.answer(f"📞 Aloqa uchun: {CONTACT}", reply_markup=kb)


@dp.message(F.text == BTN_FEEDBACK)
async def btn_feedback(msg: Message):
    feedback_mode[msg.from_user.id] = "choose"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕶 Anonim yuborish", callback_data="fb_anon")],
        [InlineKeyboardButton(text="👤 Ismim bilan yuborish", callback_data="fb_named")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="fb_cancel")],
    ])
    await msg.answer(
        "💬 Bot haqida fikringizni bildiring.\n\n"
        "Anonim yuborsangiz, sizning ismingiz va akkauntingiz egasiga ko'rsatilmaydi. "
        "Qanday yuborasiz?",
        reply_markup=kb,
    )


# ---------- Kunlik seriya (Supabase: streaks jadvali) ----------

DAILY_GOAL = 10   # kuniga nechta test kerak

# Har kuni maqsad bajarilganda tasodifiy bittasi chiqadi ({n} = seriya kunlari)
DAILY_MESSAGES = [
    "🔥 {n} kunlik seriya!\nHar kungi 10 ta test kelajakdagi yaxshi shifokorni shakllantiradi.",
    "✅ Bugungi maqsad bajarildi.\nKichik qadamlar katta natija beradi, {n}-kun ortda qoldi.",
    "💪 {n} kun ketma-ket!\nImtihonda aynan shu odat sizni qutqaradi.",
    "🩺 Bilim kunma-kun yig'iladi.\n{n}-kun tayyor, davom eting!",
    "📚 Bugun ham o'zingizni yengdingiz.\nSeriya: {n} kun.",
]

# Nishonlar: kun -> (belgi, matn)
MILESTONES = {
    3: ("🌱", "Odat shakllana boshladi. Eng qiyini boshlash edi, siz boshladingiz."),
    7: ("🏅", "Bir hafta uzluksiz! Hamma ham bunga erisha olmaydi."),
    14: ("🥈", "Ikki hafta. Endi bu odat, majburiyat emas."),
    30: ("🥇", "Bir oy! Siz intizomli shifokor yo'lidasiz."),
    60: ("💎", "Ikki oy. Bilimingiz har kuni ko'rinadigan darajada o'sdi."),
    100: ("👑", "100 kun! Bu endi seriya emas, siz haqingizdagi hikoya."),
}

NEW_START_TEXT = "🌟 Yangi boshlanish!\nSeriya qaytadan boshlandi. Eng uzun natijangiz {best} kun edi, demak buni qila olasiz."


def praise_text(streak, best):
    """Bugungi maqsad bajarilganda chiqadigan ilhomlantiruvchi matn."""
    if streak in MILESTONES:
        icon, text = MILESTONES[streak]
        return f"{icon} {streak} kunlik seriya!\n{text}"
    if streak == 1 and best > 1:
        return NEW_START_TEXT.format(best=best)
    return random.choice(DAILY_MESSAGES).format(n=streak)


def today_str(offset=0):
    return (datetime.now(TZ).date() + timedelta(days=offset)).isoformat()


async def streak_get(user_id):
    """Qator (dict), qator yo'q bo'lsa {}, xato bo'lsa None."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{SUPABASE_URL}/rest/v1/streaks?select=*&user_id=eq.{user_id}",
                headers=db_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status >= 300:
                    print("streak_get xato:", r.status, await r.text())
                    return None
                data = await r.json()
                return data[0] if data else {}
    except Exception as e:
        print("streak_get xatosi:", e)
        return None


async def streak_save(row):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{SUPABASE_URL}/rest/v1/streaks?on_conflict=user_id",
                headers=db_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                json=row,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status >= 300:
                    print("streak_save xato:", r.status, await r.text())
                    return False
                return True
    except Exception as e:
        print("streak_save xatosi:", e)
        return False


def streak_view(row):
    today, yest = today_str(), today_str(-1)
    last = row.get("last_active_date")
    streak = row.get("streak") or 0
    if last not in (today, yest):
        streak = 0   # kecha ham, bugun ham faol bo'lmagan: seriya uzilgan
    cnt = (row.get("today_count") or 0) if row.get("today_date") == today else 0
    return {
        "streak": streak,
        "best": row.get("best_streak") or 0,
        "today_count": cnt,
        "goal": DAILY_GOAL,
        "done_today": last == today,
    }


async def streak_add(user_id, n=1):
    """n ta test yechilganini hisoblaydi. Yangilangan holatni qaytaradi (xato bo'lsa None)."""
    row = await streak_get(user_id)
    if row is None:
        return None
    today, yest = today_str(), today_str(-1)
    streak = row.get("streak") or 0
    best = row.get("best_streak") or 0
    last = row.get("last_active_date")
    cnt = (row.get("today_count") or 0) if row.get("today_date") == today else 0
    cnt += n
    just = False
    if cnt >= DAILY_GOAL and last != today:
        streak = streak + 1 if last == yest else 1
        best = max(best, streak)
        last = today
        just = True
    new = {
        "user_id": user_id,
        "streak": streak,
        "best_streak": best,
        "last_active_date": last,
        "today_date": today,
        "today_count": cnt,
    }
    if not await streak_save(new):
        return None
    view = streak_view(new)
    view["just_completed"] = just
    if just:
        view["message"] = praise_text(streak, best)
    return view


def streak_text(v):
    done = min(v["today_count"], v["goal"])
    bar = "█" * done + "░" * (v["goal"] - done)
    lines = [
        f"🔥 {v['streak']} kunlik seriya",
        f"🏆 Eng uzun seriya: {v['best']} kun",
        "",
        f"Bugungi maqsad: {done}/{v['goal']} test",
        bar,
        "",
    ]
    if v["done_today"]:
        lines.append("✅ Bugungi maqsad bajarildi. Barakalla!")
    elif v["streak"] == 0 and v["best"] > 0:
        lines.append(
            f"Seriya uzildi, lekin eng uzun natijangiz {v['best']} kun edi, demak buni qila olasiz. "
            f"Bugun yangisini boshlang: atigi {v['goal']} ta test."
        )
    else:
        lines.append(f"Bugun {v['goal'] - done} ta test qoldi, siz uddalaysiz.")
    nxt = [m for m in MILESTONES if m > v["streak"]]
    if nxt:
        m = min(nxt)
        icon = MILESTONES[m][0]
        lines.append(f"\n{icon} Keyingi nishon: {m} kun (yana {m - v['streak']} kun)")
    return "\n".join(lines)


@dp.message(F.text == BTN_STREAK)
async def btn_streak(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    row = await streak_get(msg.from_user.id)
    if row is None:
        await msg.answer("Seriyani hozir ko'rsatib bo'lmadi. Keyinroq urinib ko'ring.")
        return
    await msg.answer(
        streak_text(streak_view(row)),
        reply_markup=app_keyboard(SITE_URL, "🌐 Test yechish"),
    )


# ---------- Kunning savoli (A/B/C/D tugmalar, javoblar hisobi, izoh) ----------

QOTD_HOUR = 8   # har kuni soat nechada yuboriladi (Toshkent vaqti)
LETTERS = "ABCDEFGH"


def _load_qotd():
    base = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(base, "questions.json"), encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print("questions.json yuklanmadi:", e)
        return {}, {}, [], [], {"start": None, "order": [], "items": {}}
    by_hash = {x["h"]: x for x in data["q"]}
    try:
        with open(os.path.join(base, "explanations.json"), encoding="utf-8") as f:
            expl = json.load(f)
    except Exception as e:
        print("explanations.json yuklanmadi:", e)
        expl = {"start": None, "order": [], "items": {}}
    curated = [h for h in expl.get("order", []) if h in by_hash]
    used = set(curated)
    rest = [x["h"] for x in data["q"] if x["h"] not in used and len(set(x["o"])) == len(x["o"])]
    random.Random(20261013).shuffle(rest)
    return data["titles"], by_hash, curated, rest, expl


QOTD_TITLES, QOTD_QUESTIONS, QOTD_CURATED, QOTD_REST, QOTD_EXPL = _load_qotd()


def qotd_day():
    """Savol kuni soat 08:00 da almashadi (Toshkent)."""
    return (datetime.now(TZ) - timedelta(hours=QOTD_HOUR)).date().toordinal()


def qotd_for(day):
    """Berilgan kun uchun savol: hamma uchun bir xil, variantlar kunga qarab aralashtiriladi."""
    start = None
    if QOTD_EXPL.get("start"):
        try:
            start = datetime.fromisoformat(QOTD_EXPL["start"]).date().toordinal()
        except Exception:
            start = None
    if start is not None and 0 <= day - start < len(QOTD_CURATED):
        h = QOTD_CURATED[day - start]
    else:
        h = QOTD_REST[day % len(QOTD_REST)]
    item = QOTD_QUESTIONS[h]
    order = list(range(len(item["o"])))
    random.Random(day).shuffle(order)          # order[pos] = asl variant raqami
    return {
        "day": day,
        "h": h,
        "q": item["q"],
        "opts": [item["o"][i] for i in order],
        "orig": order,
        "correct": order.index(item["c"]),
        "src": QOTD_TITLES.get(item["k"], ""),
    }


def qotd_head(p):
    return ["🧠 Kunning savoli", f"📚 {p['src']}", "", p["q"], ""]


def qotd_question_text(p):
    lines = qotd_head(p)
    for i, o in enumerate(p["opts"]):
        lines.append(f"{LETTERS[i]}) {o}")
    lines += ["", "Javobni tanlang 👇"]
    return "\n".join(lines)


def qotd_keyboard(p):
    row = [
        InlineKeyboardButton(text=LETTERS[i], callback_data=f"qa:{p['day']}:{i}")
        for i in range(len(p["opts"]))
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def qotd_result_text(p, my_pos, counts):
    total = sum(counts)
    lines = qotd_head(p)
    for i, o in enumerate(p["opts"]):
        pct = round(counts[i] * 100 / total) if total else 0
        mark = "✅ " if i == p["correct"] else ""
        you = "  ← siz" if i == my_pos else ""
        lines.append(f"{LETTERS[i]}) {mark}{o}")
        lines.append(f"      {pct}% ({counts[i]}){you}")
    lines += ["", f"Jami {total} kishi javob berdi", ""]
    right = LETTERS[p["correct"]]
    if my_pos == p["correct"]:
        lines.append("✅ To'g'ri!")
    else:
        lines.append(f"❌ Xato. To'g'ri javob: {right}) {p['opts'][p['correct']]}")
    ex = QOTD_EXPL.get("items", {}).get(p["h"])
    if ex:
        if my_pos != p["correct"]:
            w = ex.get("wrong", {}).get(str(p["orig"][my_pos]))
            if w:
                lines += ["", f"❌ Nega xato: {w}"]
        lines += ["", f"💡 Nega to'g'ri: {ex['why']}", "", "ℹ️ Izoh qo'shimcha tushuntirish uchun, asosiy manba — darslik."]
    else:
        lines += ["", "Bu savol uchun izoh hali qo'shilmagan."]
    return "\n".join(lines)


async def vote_insert(day, uid, option):
    """True = yangi javob yozildi, False = oldin javob bergan, None = xato."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{SUPABASE_URL}/rest/v1/qotd_votes?on_conflict=day,user_id",
                headers=db_headers({"Prefer": "resolution=ignore-duplicates,return=representation"}),
                json={"day": day, "user_id": uid, "option": option},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status >= 300:
                    print("vote_insert xato:", r.status, await r.text())
                    return None
                return bool(await r.json())
    except Exception as e:
        print("vote_insert xatosi:", e)
        return None


async def vote_get(day, uid):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{SUPABASE_URL}/rest/v1/qotd_votes?select=option&day=eq.{day}&user_id=eq.{uid}",
                headers=db_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status >= 300:
                    return None
                rows = await r.json()
                return rows[0]["option"] if rows else None
    except Exception as e:
        print("vote_get xatosi:", e)
        return None


async def _vote_count(day, option):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{SUPABASE_URL}/rest/v1/qotd_votes?select=user_id&day=eq.{day}&option=eq.{option}&limit=1",
                headers=db_headers({"Prefer": "count=exact"}),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status >= 300:
                    return 0
                return int(r.headers.get("Content-Range", "*/0").split("/")[-1])
    except Exception as e:
        print("vote_count xatosi:", e)
        return 0


async def vote_counts(day, n):
    return list(await asyncio.gather(*[_vote_count(day, i) for i in range(n)]))


async def qotd_send(user_id):
    if not QOTD_QUESTIONS or not QOTD_REST:
        return False
    p = qotd_for(qotd_day())
    await bot.send_message(user_id, qotd_question_text(p), reply_markup=qotd_keyboard(p))
    return True


@dp.callback_query(F.data.startswith("qa:"))
async def on_qotd_answer(cb: CallbackQuery):
    try:
        _, d, pos = cb.data.split(":")
        d, pos = int(d), int(pos)
    except Exception:
        await cb.answer()
        return
    if d != qotd_day():
        await cb.answer("Bu savol eskirgan. Yangi savol har kuni soat 08:00 da keladi.", show_alert=True)
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    p = qotd_for(d)
    if pos < 0 or pos >= len(p["opts"]):
        await cb.answer()
        return
    uid = cb.from_user.id
    inserted = await vote_insert(d, uid, pos)
    if inserted is None:
        await cb.answer("Javobni hozir saqlab bo'lmadi. Qayta urinib ko'ring.", show_alert=True)
        return
    my_pos = pos
    if not inserted:
        prev = await vote_get(d, uid)
        if prev is not None:
            my_pos = prev
    counts = await vote_counts(d, len(p["opts"]))
    try:
        await cb.message.edit_text(qotd_result_text(p, my_pos, counts), reply_markup=None)
    except Exception as e:
        print("qotd edit xatosi:", e)
    await cb.answer("✅ To'g'ri!" if my_pos == p["correct"] else "❌ Xato")
    if inserted:
        await stats_add(uid, cb.from_user.first_name, 1, 1 if my_pos == p["correct"] else 0)
        v = await streak_add(uid, 1)
        if v and v.get("just_completed") and v.get("message"):
            try:
                await bot.send_message(uid, v["message"])
            except Exception as e:
                print("Seriya xabari yuborilmadi:", uid, e)


@dp.message(Command("qotd"))
async def cmd_qotd(msg: Message):
    """Admin uchun: bugungi savolni faqat o'zingizga yuboradi (sinash)."""
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        ok = await qotd_send(msg.from_user.id)
    except Exception as e:
        await msg.answer(f"Xato: {e}")
        return
    if not ok:
        await msg.answer("questions.json yuklanmagan (faylni repozitoriyga qo'shing).")


# ---------- Reyting (eng faol / eng ko'p to'g'ri javob) ----------

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def week_key():
    y, w, _ = datetime.now(TZ).isocalendar()
    return f"{y}-W{w:02d}"


def clean_name(name, uid):
    n = (name or "").strip()
    return n[:18] if n else f"Foydalanuvchi {str(uid)[-4:]}"


async def stats_add(user_id, name, answered, correct):
    """Yechilgan va to'g'ri javoblar sonini jami hamda haftalik hisoblagichlarga qo'shadi."""
    if answered <= 0 or not SUPABASE_URL or not SUPABASE_KEY:
        return
    correct = max(0, min(correct, answered))
    wk = week_key()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{SUPABASE_URL}/rest/v1/stats?select=*&user_id=eq.{user_id}",
                headers=db_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status >= 300:
                    print("stats_add o'qish xato:", r.status, await r.text())
                    return
                rows = await r.json()
            row = rows[0] if rows else {}
            if row.get("week_key") == wk:
                wt = (row.get("week_total") or 0) + answered
                wc = (row.get("week_correct") or 0) + correct
            else:
                wt, wc = answered, correct
            new = {
                "user_id": user_id,
                "name": clean_name(name or row.get("name"), user_id),
                "total": (row.get("total") or 0) + answered,
                "correct": (row.get("correct") or 0) + correct,
                "week_key": wk,
                "week_total": wt,
                "week_correct": wc,
            }
            async with s.post(
                f"{SUPABASE_URL}/rest/v1/stats?on_conflict=user_id",
                headers=db_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                json=new,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r2:
                if r2.status >= 300:
                    print("stats_add yozish xato:", r2.status, await r2.text())
    except Exception as e:
        print("stats_add xatosi:", e)


def lb_col(metric, period):
    base = "total" if metric == "a" else "correct"
    return ("week_" + base) if period == "w" else base


async def lb_fetch(metric, period, user_id):
    """(top10, mening_natijam, mening_o'rnim) yoki xato bo'lsa None.
    top10 = [(o'rin, ism, qiymat, user_id)]; teng natijalar bir xil o'rinni oladi."""
    col = lb_col(metric, period)
    flt = f"&week_key=eq.{week_key()}" if period == "w" else ""
    t = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{SUPABASE_URL}/rest/v1/stats?select=user_id,name,{col}&{col}=gt.0{flt}"
                f"&order={col}.desc,user_id.asc&limit=10",
                headers=db_headers(), timeout=t,
            ) as r:
                if r.status >= 300:
                    print("lb_fetch xato:", r.status, await r.text())
                    return None
                rows = await r.json()
            top, prev_v, prev_rank = [], None, 0
            for i, x in enumerate(rows):
                v = x[col]
                rank = prev_rank if v == prev_v else i + 1
                prev_v, prev_rank = v, rank
                top.append((rank, x.get("name") or "—", v, x["user_id"]))
            async with s.get(
                f"{SUPABASE_URL}/rest/v1/stats?select={col}&user_id=eq.{user_id}{flt}",
                headers=db_headers(), timeout=t,
            ) as r:
                mine = await r.json() if r.status < 300 else []
            my_val = mine[0][col] if mine else 0
            my_rank = None
            if my_val > 0:
                async with s.get(
                    f"{SUPABASE_URL}/rest/v1/stats?select=user_id&{col}=gt.{my_val}{flt}&limit=1",
                    headers=db_headers({"Prefer": "count=exact"}), timeout=t,
                ) as r:
                    if r.status < 300:
                        my_rank = int(r.headers.get("Content-Range", "*/0").split("/")[-1]) + 1
            return top, my_val, my_rank
    except Exception as e:
        print("lb_fetch xatosi:", e)
        return None


def lb_text(metric, period, data, uid):
    top, my_val, my_rank = data
    title_m = "🔥 Eng faol (yechilgan testlar)" if metric == "a" else "🎯 Eng ko'p to'g'ri javob"
    title_p = "📅 Shu hafta" if period == "w" else "🏆 Barcha vaqt"
    unit = "test" if metric == "a" else "ta to'g'ri"
    lines = ["🏆 Reyting", f"{title_m} · {title_p}", ""]
    if not top:
        lines.append("Hozircha natijalar yo'q. Birinchi bo'ling: saytda test yeching!")
    for rank, name, v, u in top:
        mark = MEDALS.get(rank, f"{rank}.")
        me = "  👈 siz" if u == uid else ""
        lines.append(f"{mark} {name} — {v} {unit}{me}")
    lines.append("")
    if my_rank:
        lines.append(f"{MEDALS.get(my_rank, '👤')} Sizning o'rningiz: {my_rank}-o'rin — {my_val} {unit}")
    else:
        lines.append("👤 Siz hali reytingda yo'qsiz. Saytda test yeching!")
    lines += ["", "Reyting saytdagi testlar va kunning savoli asosida hisoblanadi."]
    return "\n".join(lines)


def lb_kb(metric, period):
    def b(text, m, p, on):
        return InlineKeyboardButton(text=("✅ " if on else "") + text, callback_data=f"lb:{m}:{p}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [b("🔥 Eng faol", "a", period, metric == "a"), b("🎯 To'g'ri javob", "c", period, metric == "c")],
        [b("📅 Hafta", metric, "w", period == "w"), b("🏆 Jami", metric, "t", period == "t")],
    ])


@dp.message(F.text == BTN_RATING)
async def btn_rating(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    data = await lb_fetch("a", "w", msg.from_user.id)
    if data is None:
        await msg.answer("Reytingni hozir ko'rsatib bo'lmadi. Keyinroq urinib ko'ring.")
        return
    await msg.answer(lb_text("a", "w", data, msg.from_user.id), reply_markup=lb_kb("a", "w"))


@dp.callback_query(F.data.startswith("lb:"))
async def on_rating(cb: CallbackQuery):
    try:
        _, m, p = cb.data.split(":")
        assert m in ("a", "c") and p in ("w", "t")
    except Exception:
        await cb.answer()
        return
    data = await lb_fetch(m, p, cb.from_user.id)
    if data is None:
        await cb.answer("Hozir ko'rsatib bo'lmadi. Keyinroq urinib ko'ring.", show_alert=True)
        return
    try:
        await cb.message.edit_text(lb_text(m, p, data, cb.from_user.id), reply_markup=lb_kb(m, p))
    except Exception:
        pass   # matn o'zgarmagan bo'lsa Telegram xato beradi, bu normal
    await cb.answer()


# ---------- Oraliqlar (PDF fayllar) ----------

file_cache = {}   # fayl nomi -> Telegram file_id (qayta yuklamaslik uchun)


def oraliq_files():
    """Repodagi oraliq_*.pdf fayllarini topadi: {tugma nomi: fayl yo'li}"""
    base = os.path.dirname(os.path.abspath(__file__))
    result = {}
    try:
        names = sorted(os.listdir(base))
    except Exception:
        return result
    for fn in names:
        if fn.lower().startswith(ORALIQ_PREFIX) and fn.lower().endswith(".pdf"):
            title = fn[len(ORALIQ_PREFIX):-4].replace("_", " ").strip()
            if title:
                result[FILE_PREFIX + title] = os.path.join(base, fn)
    return result


@dp.message(F.text == BTN_ORALIQ)
async def btn_oraliq(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    files = oraliq_files()
    if not files:
        await msg.answer("📝 Oraliq fayllari hozircha yuklanmagan. Tez orada qo'shiladi!")
        return
    rows = [[KeyboardButton(text=t)] for t in files]
    rows.append([KeyboardButton(text=BTN_BACK)])
    kb = ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
    await msg.answer("📝 Oraliqlar. Fanni tanlang:", reply_markup=kb)


@dp.message(F.text == BTN_BACK)
async def btn_back(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    await msg.answer("📋 Asosiy menyu", reply_markup=MENU)


@dp.message(F.text.startswith(FILE_PREFIX))
async def btn_oraliq_file(msg: Message):
    feedback_mode.pop(msg.from_user.id, None)
    if await need_subscribe(msg):
        return
    path = oraliq_files().get(msg.text)
    if not path:
        await msg.answer("Bu fayl topilmadi. /menu ni bosib qayta urinib ko'ring.")
        return
    caption = "📝 " + msg.text[len(FILE_PREFIX):] + " (oraliq)\n\nTALABA MED"
    try:
        fid = file_cache.get(path)
        sent = await msg.answer_document(fid or FSInputFile(path), caption=caption, reply_markup=MENU, protect_content=True)
        if not fid and sent.document:
            file_cache[path] = sent.document.file_id
    except Exception as e:
        print("PDF yuborishda xato:", e)
        await msg.answer("Faylni yuborib bo'lmadi. Keyinroq urinib ko'ring.")


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
        await cb.message.edit_text(f"✍️ Fikringizni bitta xabar qilib yozing ({how} yuboriladi).\nBekor qilish uchun pastdagi tugmalardan birini bosing.")
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
    left = await not_subscribed(user["id"])
    await save_user(user["id"], user.get("first_name"), user.get("username"), not left)
    missing = [{"name": n, "url": f"https://t.me/{u[1:]}"} for n, u in left]
    return web.json_response({"ok": not left, "missing": missing})


async def _streak_user(request):
    """(user, xato_javobi) qaytaradi."""
    try:
        body = await request.json()
    except Exception:
        return None, None, web.json_response({"ok": False, "error": "bad_request"}, status=400)
    user = user_from_init_data(body.get("initData", ""))
    if not user:
        return None, None, web.json_response({"ok": False, "error": "invalid"}, status=403)
    return user, body, None


DAILY_CAP = 600          # kuniga reyting/seriyaga hisoblanadigan maksimal javoblar soni (yechish cheklanmaydi)
VERIFY_MAX_ITEMS = 60    # bitta so'rovdagi javoblar chegarasi


def _norm(t):
    return " ".join(str(t).split())


def _h(t, n):
    return hashlib.sha1(_norm(t).encode("utf-8")).hexdigest()[:n]


def _load_bank():
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bank.json")
        with open(path, encoding="utf-8") as f:
            return {k: set(v) for k, v in json.load(f)["q"].items()}
    except Exception as e:
        print("bank.json yuklanmadi:", e)
        return {}


BANK = _load_bank()   # savol matni xeshi -> to'g'ri javob matni xeshlari


async def seen_insert(day, uid, pairs):
    """Shu kun birinchi marta berilgan javoblarni yozadi va ro'yxatini qaytaradi. Xato bo'lsa None."""
    rows = [{"day": day, "user_id": uid, "qh": qh, "ok": ok} for qh, ok in pairs]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{SUPABASE_URL}/rest/v1/seen_daily?on_conflict=day,user_id,qh",
                headers=db_headers({"Prefer": "resolution=ignore-duplicates,return=representation"}),
                json=rows,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status >= 300:
                    print("seen_insert xato:", r.status, await r.text())
                    return None
                return [(x["qh"], x["ok"]) for x in await r.json()]
    except Exception as e:
        print("seen_insert xatosi:", e)
        return None


async def api_answer(request):
    """Sayt javoblarni (savol matni + tanlangan variant matni) yuboradi.
    To'g'rilikni SERVER o'zining bazasidan tekshiradi; mijoz yuborgan 'to'g'ri' degan da'vo qabul qilinmaydi.
    Har savol kuniga bir marta hisoblanadi, kuniga DAILY_CAP tagacha."""
    if request.method == "OPTIONS":
        return web.Response()
    user, body, err = await _streak_user(request)
    if err:
        return err
    items = body.get("items")
    if not isinstance(items, list):
        return web.json_response({"ok": True, "counted": 0, "legacy": True})
    uid = user["id"]

    seen_req, pairs, unknown = set(), [], 0
    for it in items[:VERIFY_MAX_ITEMS]:
        try:
            qt, at = it["q"], it["a"]
            if not isinstance(qt, str) or not isinstance(at, str):
                continue
        except Exception:
            continue
        qh = _h(qt, 12)
        good = BANK.get(qh)
        if good is None:
            unknown += 1
            continue
        if qh in seen_req:
            continue
        seen_req.add(qh)
        pairs.append((qh, _h(at, 10) in good))

    row = await streak_get(uid)
    if row is None:
        return web.json_response({"ok": False, "error": "db"}, status=500)
    view = streak_view(row)
    allowed = max(0, DAILY_CAP - view["today_count"])
    pairs = pairs[:allowed]

    new = []
    if pairs:
        new = await seen_insert(datetime.now(TZ).date().toordinal(), uid, pairs)
        if new is None:
            return web.json_response({"ok": False, "error": "db"}, status=500)
    counted = len(new)
    correct = sum(1 for _, ok in new if ok)
    if not counted:
        view["just_completed"] = False
        return web.json_response({"ok": True, "counted": 0, "unknown": unknown, "capped": allowed == 0, **view})

    v = await streak_add(uid, counted)
    await stats_add(uid, user.get("first_name"), counted, correct)
    if v is None:
        return web.json_response({"ok": False, "error": "db"}, status=500)
    if v.get("just_completed") and v.get("message"):
        try:
            await bot.send_message(uid, v["message"])
        except Exception as e:
            print("Seriya xabari yuborilmadi:", uid, e)
    return web.json_response({"ok": True, "counted": counted, "correct": correct, "unknown": unknown, **v})


async def api_streak(request):
    """Sayt seriyani ko'rsatish uchun (hisobni o'zgartirmaydi)."""
    if request.method == "OPTIONS":
        return web.Response()
    user, body, err = await _streak_user(request)
    if err:
        return err
    row = await streak_get(user["id"])
    if row is None:
        return web.json_response({"ok": False, "error": "db"}, status=500)
    return web.json_response({"ok": True, **streak_view(row)})


async def streak_reminder_loop():
    """Har kuni 20:00 (Toshkent) da bugungi maqsadini bajarmagan seriya egalariga eslatma."""
    while True:
        now = datetime.now(TZ)
        nxt = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        if not SUPABASE_URL or not SUPABASE_KEY:
            continue
        try:   # 2 kundan eski "shu kun javob berilgan savollar" yozuvlarini o'chirish
            async with aiohttp.ClientSession() as s:
                await s.delete(
                    f"{SUPABASE_URL}/rest/v1/seen_daily?day=lt.{datetime.now(TZ).date().toordinal() - 2}",
                    headers=db_headers(), timeout=aiohttp.ClientTimeout(total=20),
                )
        except Exception as e:
            print("seen_daily tozalash xatosi:", e)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{SUPABASE_URL}/rest/v1/streaks?select=user_id,streak"
                    f"&last_active_date=eq.{today_str(-1)}&streak=gt.0&limit=1000",
                    headers=db_headers(),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as r:
                    rows = await r.json() if r.status < 300 else []
            for row in rows:
                try:
                    await bot.send_message(
                        row["user_id"],
                        f"Bugun {DAILY_GOAL} ta test qoldi, siz uddalaysiz. "
                        f"🔥 {row['streak']} kunlik seriyangizni davom ettiring.",
                        reply_markup=app_keyboard(SITE_URL, "🌐 Test yechish"),
                    )
                except Exception as e:
                    print("Eslatma yuborilmadi:", row.get("user_id"), e)
                await asyncio.sleep(0.1)
        except Exception as e:
            print("streak eslatma xatosi:", e)


async def qotd_users():
    ids, offset = [], 0
    while True:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{SUPABASE_URL}/rest/v1/bot_users?select=user_id&is_member=eq.true"
                f"&order=user_id.asc&limit=1000&offset={offset}",
                headers=db_headers(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                rows = await r.json() if r.status < 300 else []
        ids += [x["user_id"] for x in rows]
        if len(rows) < 1000:
            break
        offset += 1000
    return ids


async def qotd_loop():
    """Har kuni 08:00 (Toshkent) da obunadagi hammaga kunning savolini yuboradi."""
    while True:
        now = datetime.now(TZ)
        nxt = now.replace(hour=QOTD_HOUR, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        if not SUPABASE_URL or not SUPABASE_KEY or not QOTD_QUESTIONS:
            continue
        try:
            for uid in await qotd_users():
                try:
                    await qotd_send(uid)
                except Exception as e:
                    print("Kunning savoli yuborilmadi:", uid, e)
                await asyncio.sleep(0.06)
            # izohli savollar tugab borayotgan bo'lsa, adminga eslatma
            st = QOTD_EXPL.get("start")
            if st:
                left = len(QOTD_CURATED) - (qotd_day() - datetime.fromisoformat(st).date().toordinal()) - 1
                if left <= 2:
                    await bot.send_message(
                        ADMIN_ID,
                        f"⚠️ Izohli savollar {max(left, 0)} kunga qoldi. Yangi izohlar tayyorlash vaqti.",
                    )
        except Exception as e:
            print("qotd_loop xatosi:", e)


async def health(request):
    return web.Response(text="OK")


async def main():
    app = web.Application(middlewares=[cors_mw])
    app.router.add_get("/", health)
    app.router.add_route("*", "/api/check", api_check)
    app.router.add_route("*", "/api/answer", api_answer)
    app.router.add_route("*", "/api/streak", api_streak)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()
    asyncio.create_task(sweep_loop())
    asyncio.create_task(streak_reminder_loop())
    asyncio.create_task(qotd_loop())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


asyncio.run(main())
