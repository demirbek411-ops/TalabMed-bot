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

ORALIQ_PREFIX = "oraliq_"      # PDF fayl nomi shu so'z bilan boshlanishi kerak
FILE_PREFIX = "📄 "

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_APP), KeyboardButton(text=BTN_SCHEDULE)],
        [KeyboardButton(text=BTN_ABOUT), KeyboardButton(text=BTN_CHANNELS)],
        [KeyboardButton(text=BTN_CONTACT), KeyboardButton(text=BTN_FEEDBACK)],
        [KeyboardButton(text=BTN_ORALIQ), KeyboardButton(text=BTN_STREAK)],
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
            "so'ng «Tekshirish» tugmasini bosing:",
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
            "Avval quyidagilarga obuna bo'ling, so'ng «Tekshirish» tugmasini bosing:",
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
    await msg.answer("📢 Bizning kanal va guruhlar:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


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


async def api_answer(request):
    """Sayt har test javobidan keyin chaqiradi: seriya hisobini yangilaydi."""
    if request.method == "OPTIONS":
        return web.Response()
    user, body, err = await _streak_user(request)
    if err:
        return err
    try:
        n = int(body.get("n", 1))
    except Exception:
        n = 1
    n = max(1, min(n, 50))
    v = await streak_add(user["id"], n)
    if v is None:
        return web.json_response({"ok": False, "error": "db"}, status=500)
    if v.get("just_completed") and v.get("message"):
        try:
            await bot.send_message(user["id"], v["message"])
        except Exception as e:
            print("Seriya xabari yuborilmadi:", user["id"], e)
    return web.json_response({"ok": True, **v})


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
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


asyncio.run(main())
