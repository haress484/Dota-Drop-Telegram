import asyncio
import json
import os
import hmac
import hashlib
import logging
import random
import time
import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qsl

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (Message, CallbackQuery, LabeledPrice, WebAppInfo,
                           InlineKeyboardButton, InlineKeyboardMarkup, PreCheckoutQuery,
                           InlineQuery, InlineQueryResultArticle, InlineQueryResultPhoto,
                           InputTextMessageContent)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise SystemExit("❌ Не задан BOT_TOKEN в Environment на Render!")

ADMIN_PC_PASSWORD = os.environ.get("ADMIN_PC_PASSWORD", "")
if not ADMIN_PC_PASSWORD:
    print("⚠️ ADMIN_PC_PASSWORD не задан. Вход в PC-админку будет невозможен.")

CHANNEL_USERNAME = "@the_kubicki"
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://haress484.github.io/Dota-Drop-Telegram/").rstrip("/") + "/"
ADMIN_URL = WEB_APP_URL + "admin.html"
OWNER_ID = 1837442717

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

BANNER_URL = "https://raw.githubusercontent.com/haress484/Dota-Drop-Telegram/main/inline_banner.jpg"
INLINE_MAX_STARS = 10000

SNIPER_ENABLED = True
SNIPER_INTERVAL = 15
SNIPER_MANUAL_COOLDOWN = 5

GIFT_PATTERNS = [
    {"seq": [15, 15, 25, 15, 15, 50], "weight": 40},
    {"seq": [25, 15, 15, 15, 15, 50], "weight": 30},
    {"seq": [15, 15, 25, 15, 15, 25], "weight": 20},
    {"seq": [15, 15, 15, 15, 15, 25], "weight": 10},
]
PRICE_TO_GIFTS = {
    15: ["gift_heart", "gift_teddy"],
    25: ["gift_box", "gift_rose"],
    50: ["gift_cake", "gift_bouquet"],
}

ALLOWED_PUSH_FIELDS = {"casesOpened", "coinsSpent", "balance", "inventory"}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

# ================= ПОДАРКИ =================
GIFT_CATALOG = {
    "gift_heart": {"id": "5170145012310081615", "price": 15, "name": "💝 Сердечко"},
    "gift_teddy": {"id": "5170233102089322756", "price": 15, "name": "🧸 Мишка"},
    "gift_box":   {"id": "5170250947678437525", "price": 25, "name": "🎁 Подарок"},
    "gift_rose":  {"id": "5168103777563050263", "price": 25, "name": "🌹 Роза"},
    "gift_cake":  {"id": "5170144170496491616", "price": 50, "name": "🎂 Торт"},
    "gift_bouquet":{"id": "5170314324215857265", "price": 50, "name": "💐 Букет"}
}

class GiftSendStates(StatesGroup):
    waiting_user_id = State()
    confirming = State()

class BroadcastStates(StatesGroup):
    choosing_audience = State()
    waiting_uid = State()
    waiting_content = State()

# ================= SUPABASE =================
class DB:
    def __init__(self):
        self.base = SUPABASE_URL + "/rest/v1"
        self.h = {
            "apikey": SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

    async def _req(self, method, path, data=None):
        async with aiohttp.ClientSession() as s:
            async with s.request(method, self.base + path, headers=self.h, json=data) as r:
                try:
                    body = await r.json()
                except Exception:
                    body = None
                if r.status >= 300:
                    print(f"DB ERROR {method} {path} -> {r.status}: {body}")
                return body

    async def select(self, table, q=""):
        res = await self._req("GET", f"/{table}{q}")
        return res if isinstance(res, list) else []

    async def insert(self, table, rows):
        return await self._req("POST", f"/{table}", rows)

    async def upsert(self, table, rows):
        h = dict(self.h)
        h["Prefer"] = "return=representation,resolution=merge-duplicates"
        async with aiohttp.ClientSession() as s:
            async with s.post(self.base + f"/{table}", headers=h, json=rows) as r:
                try:
                    body = await r.json()
                except Exception:
                    body = None
                if r.status >= 300:
                    print(f"DB ERROR POST /{table} -> {r.status}: {body}")
                return body

    async def update(self, table, q, data):
        return await self._req("PATCH", f"/{table}{q}", data)

    async def delete(self, table, q):
        return await self._req("DELETE", f"/{table}{q}")

    async def count(self, table, q=""):
        h = dict(self.h)
        h["Prefer"] = "count=exact"
        async with aiohttp.ClientSession() as s:
            async with s.get(self.base + f"/{table}{q}", headers=h) as r:
                try:
                    return int(r.headers.get("Content-Range", "0-0/*").split("/")[-1])
                except Exception:
                    return 0

db = DB()

async def touch_player(user_id, username=None, first_name=None):
    row = {"user_id": user_id, "last_seen": now_iso()}
    if username and username.strip():
        row["username"] = username
    if first_name and first_name.strip() and first_name.upper() != "EMPTY":
        row["first_name"] = first_name
    await db.upsert("players", [row])

async def merge_player_stats(uid, patch):
    rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
    cur = (rows[0].get("stats") if rows else None) or {}
    cur.update(patch)
    await db.update("players", f"?user_id=eq.{uid}", {"stats": cur})

async def get_gift_inv(uid):
    rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
    if not rows:
        await db.upsert("players", [{"user_id": uid, "stats": {"gift_inv": {}}}])
        return {"gift_inv": {}}, {}
    stats = rows[0].get("stats") or {}
    return stats, (stats.get("gift_inv") or {})

async def set_gift_inv(uid, stats, gift_inv):
    stats["gift_inv"] = gift_inv
    await db.update("players", f"?user_id=eq.{uid}", {"stats": stats})

async def get_real_stars():
    try:
        res = await bot.get_star_balance()
        return getattr(res, "current_amount", None)
    except Exception as e:
        print("get_star_balance недоступен:", e)
        return None

async def refresh_stars_cache():
    real = await get_real_stars()
    if real is not None:
        await db.upsert("meta", [{"key": "stars_cache", "value": real}])
    return real

async def stars_delta_ok(stars):
    real = await get_real_stars()
    if real is None:
        return True
    rows = await db.select("meta", "?key=eq.stars_cache")
    cache = int(rows[0].get("value")) if rows else None
    if cache is None:
        await db.upsert("meta", [{"key": "stars_cache", "value": real}])
        return True
    ok = real >= cache + stars
    await db.upsert("meta", [{"key": "stars_cache", "value": real}])
    if not ok:
        print(f"🚨 FRAUD: баланс {real}, ожидалось >= {cache + stars} (платёж {stars})")
    return ok

# ================= PC ADMIN AUTH =================
async def validate_pc_token(token):
    if not token:
        return None
    rows = await db.select("admin_sessions", f"?token=eq.{token}")
    if not rows:
        return None
    sess = rows[0]
    expires = datetime.fromisoformat(sess["expires_at"])
    if expires < datetime.now(timezone.utc):
        await db.delete("admin_sessions", f"?id=eq.{sess['id']}")
        return None
    await db.update("admin_sessions", f"?id=eq.{sess['id']}", {"last_used_at": now_iso()})
    return sess

async def log_player_action(user_id, action, details=None):
    try:
        await db.insert("player_action_log", [{
            "user_id": user_id,
            "action": action,
            "details": details or {}
        }])
    except Exception as e:
        print(f"Log error: {e}")

# ================= КЛАВИАТУРЫ =================
def play_kb(user_id):
    rows = [[InlineKeyboardButton(text="🎮 ИГРАТЬ", web_app=WebAppInfo(url=WEB_APP_URL))]]
    if user_id == OWNER_ID:
        rows.append([
            InlineKeyboardButton(text="🛠 АДМИНКА", web_app=WebAppInfo(url=ADMIN_URL)),
            InlineKeyboardButton(text="🎁 ПОДАРОК", callback_data="admin_gift"),
        ])
        rows.append([InlineKeyboardButton(text="📢 РАССЫЛКА", callback_data="admin_broadcast")])
        rows.append([InlineKeyboardButton(text="🎯 СКАН ЛИМИТОК", callback_data="admin_sniper_scan")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

SUB_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/the_kubicki")],
    [InlineKeyboardButton(text="✅ Я подписался, проверить", callback_data="check_sub")]
])

async def check_sub(user_id):
    try:
        m = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception:
        return False

# ================= КОМАНДЫ =================
LAST_MSG = {}

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    old_mid = LAST_MSG.get(uid)
    if old_mid is None:
        try:
            rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
            old_mid = ((rows[0].get("stats") or {}) if rows else {}).get("last_msg_id")
        except Exception as e:
            print("start: ошибка чтения stats:", e)
    if old_mid:
        try:
            await bot.delete_message(message.chat.id, old_mid)
        except Exception as e:
            print("start: не удалось удалить старое:", e)
    try:
        await message.delete()
    except Exception:
        pass
    try:
        await touch_player(uid, message.from_user.username, message.from_user.first_name)
    except Exception as e:
        print("start: touch_player ошибка:", e)

    if not await check_sub(uid):
        sent = await message.answer(
            "👋 Привет! Чтобы получить доступ к боту, подпишись на канал:\n\n"
            "📢 @the_kubicki\n\nПосле подписки нажми кнопку ниже.",
            reply_markup=SUB_KB)
    else:
        sent = await message.answer(
            "🎉 Добро пожаловать в Dota Drop!\nЖми кнопку ниже, чтобы играть.",
            reply_markup=play_kb(uid))
    LAST_MSG[uid] = sent.message_id
    try:
        await merge_player_stats(uid, {"last_msg_id": sent.message_id})
    except Exception as e:
        print("start: ошибка сохранения stats:", e)

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(cb: CallbackQuery):
    uid = cb.from_user.id
    if await check_sub(uid):
        await cb.message.edit_text(
            "🎉 Добро пожаловать в Dota Drop!\nЖми кнопку ниже, чтобы играть.",
            reply_markup=play_kb(uid))
        await cb.answer("Подписка подтверждена!")
    else:
        await cb.answer("⚠️ Ты всё ещё не подписан!", show_alert=True)

# ================= INLINE-РЕЖИМ =================
@dp.inline_query()
async def handle_inline(iq: InlineQuery):
    if iq.from_user.id != OWNER_ID:
        await iq.answer([], cache_time=0, is_personal=True)
        return
    q = (iq.query or "").strip()
    if not q.isdigit():
        hint = InlineQueryResultArticle(
            id="hint",
            title="Введи число звёзд",
            description="Например: 25 — карточка спонсорства бота",
            input_message_content=InputTextMessageContent(
                message_text="💎 Спонсорство Dota Drop: напиши @бот и число звёзд"),
        )
        await iq.answer([hint], cache_time=0, is_personal=True)
        return
    n = int(q)
    if n < 1 or n > INLINE_MAX_STARS:
        hint = InlineQueryResultArticle(
            id="hint_range",
            title=f"Число от 1 до {INLINE_MAX_STARS}",
            description="Столько звёзд сможет внести спонсор",
            input_message_content=InputTextMessageContent(
                message_text="💎 Введи число звёзд от 1 до 10000"),
        )
        await iq.answer([hint], cache_time=0, is_personal=True)
        return
    try:
        link = await bot.create_invoice_link(
            title="Спонсорство Dota Drop",
            description=f"Поддержка бота на {n} Stars",
            payload=f"bot_topup_{n}",
            currency="XTR",
            prices=[LabeledPrice(label="Спонсорство", amount=n)])
    except Exception as e:
        print(f"Inline invoice error: {e}")
        await iq.answer([], cache_time=0, is_personal=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Спонсировать {n} ⭐", url=link)]
    ])
    result = InlineQueryResultPhoto(
        id=f"sponsor_{n}",
        photo_url=BANNER_URL,
        thumbnail_url=BANNER_URL,
        caption=f"💎 Поддержи бота Dota Drop на {n} ⭐",
        reply_markup=kb,
    )
    await iq.answer([result], cache_time=0, is_personal=True)

# ================= ОТПРАВКА ПОДАРКА ЧЕРЕЗ БОТА (FSM) =================
@dp.callback_query(F.data == "admin_gift")
async def cb_admin_gift(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("⛔ Доступ запрещён", show_alert=True)
        return
    await cb.message.edit_text(
        "🎁 <b>Отправка подарка</b>\n\nВведите <b>ID пользователя</b> (число):",
        parse_mode="HTML")
    await state.set_state(GiftSendStates.waiting_user_id)
    await cb.answer()

@dp.message(GiftSendStates.waiting_user_id)
async def process_user_id(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    try:
        user_id = int(message.text.strip())
        if user_id <= 0:
            raise ValueError()
    except Exception:
        await message.answer("❌ Неверный ID. Введите числовой ID:")
        return
    await state.update_data(user_id=user_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    for key, val in GIFT_CATALOG.items():
        row.append(InlineKeyboardButton(text=f"{val['name']} ({val['price']}⭐)", callback_data=f"select_gift_{key}"))
        if len(row) == 2:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)
    kb.inline_keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_gift")])
    await message.answer(f"✅ Получатель: <code>{user_id}</code>\n\nВыберите подарок:", parse_mode="HTML", reply_markup=kb)
    await state.set_state(GiftSendStates.confirming)

@dp.callback_query(F.data.startswith("select_gift_"), GiftSendStates.confirming)
async def select_gift(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        return
    gift_key = cb.data.replace("select_gift_", "")
    gift = GIFT_CATALOG.get(gift_key)
    if not gift:
        await cb.answer("❌ Подарок не найден", show_alert=True)
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    rows = await db.select("meta", "?key=eq.bot_stars")
    cur = int(rows[0].get("value")) if rows else 0
    if cur < gift["price"]:
        await cb.answer(f"❌ Недостаточно звёзд! Нужно {gift['price']}, есть {cur}", show_alert=True)
        return
    await cb.message.edit_text("⏳ Отправка подарка...")
    try:
        await bot.send_gift(user_id=user_id, gift_id=gift["id"])
        new_balance = cur - gift["price"]
        await db.upsert("meta", [{"key": "bot_stars", "value": new_balance}])
        await refresh_stars_cache()
        await cb.message.edit_text(
            f"✅ <b>Подарок отправлен!</b>\n\n👤 <code>{user_id}</code>\n🎁 {gift['name']}\n💰 Списано: {gift['price']} ⭐\n💳 Баланс бота: {new_balance} ⭐",
            parse_mode="HTML")
    except Exception as e:
        await cb.message.edit_text(f"❌ Ошибка: <code>{str(e)}</code>", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data == "cancel_gift", GiftSendStates.confirming)
async def cancel_gift(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        return
    await cb.message.edit_text("❌ Отменено.")
    await state.clear()

# ================= РАССЫЛКА (FSM) =================
@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("⛔ Доступ запрещён", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Всем", callback_data="bc_all"),
         InlineKeyboardButton(text="👤 Конкретному", callback_data="bc_one")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="bc_cancel")],
    ])
    await cb.message.answer("📢 <b>Рассылка</b>\n\nКому отправить сообщение?", parse_mode="HTML", reply_markup=kb)
    await state.set_state(BroadcastStates.choosing_audience)
    await cb.answer()

@dp.callback_query(F.data == "bc_cancel")
async def bc_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer("❌ Отменено")

@dp.message(BroadcastStates(), F.text.in_(["/cancel", "Отмена", "❌ Отмена"]))
async def bc_cancel_text(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Рассылка отменена.")

@dp.callback_query(F.data == "bc_all", BroadcastStates.choosing_audience)
async def bc_all(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        return
    await state.update_data(target="all")
    await cb.message.answer(
        "👥 Отправлю ВСЕМ игрокам.\n\nТеперь пришли сообщение для рассылки "
        "(текст, фото, файл, видео, стикер) — скопирую как есть.")
    await state.set_state(BroadcastStates.waiting_content)
    await cb.answer()

@dp.callback_query(F.data == "bc_one", BroadcastStates.choosing_audience)
async def bc_one(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        return
    await state.update_data(target="one")
    await cb.message.answer("👤 Введи ID получателя (число, можно взять из админки):")
    await state.set_state(BroadcastStates.waiting_uid)
    await cb.answer()

@dp.message(BroadcastStates.waiting_uid)
async def bc_uid(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    try:
        uid = int(message.text.strip())
        if uid <= 0:
            raise ValueError()
    except Exception:
        await message.answer("❌ Неверный ID. Введите число:")
        return
    await state.update_data(target_uid=uid)
    await message.answer(
        f"👤 Получатель: <code>{uid}</code>\n\nТеперь пришли сообщение для отправки "
        f"(текст, фото, файл, видео, стикер) — скопирую как есть.", parse_mode="HTML")
    await state.set_state(BroadcastStates.waiting_content)

@dp.message(BroadcastStates.waiting_content)
async def bc_content(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    data = await state.get_data()
    await state.clear()
    if data.get("target") == "all":
        players = await db.select("players", "?select=user_id")
        targets = [p["user_id"] for p in players]
    else:
        targets = [int(data.get("target_uid", 0))]
    status = await message.answer(f"⏳ Отправляю на {len(targets)} чат(ов)...")
    sent = 0
    failed = 0
    for uid in targets:
        try:
            await message.copy_to(uid)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await status.edit_text(f"✅ Рассылка завершена\n📤 Отправлено: {sent}\n⚠️ Ошибок: {failed}")

# ================= СНАЙПЕР ЛИМИТОК =================
SNIPER_STATE = {"notified": set(), "msg_ids": {}, "last_manual": 0.0, "baseline_done": False}

async def sniper_load_cache():
    rows = await db.select("meta", "?key=eq.sniper_notified")
    if rows:
        try:
            SNIPER_STATE["notified"] = set(json.loads(rows[0].get("value") or "[]"))
        except Exception:
            SNIPER_STATE["notified"] = set()

async def sniper_save_cache():
    await db.upsert("meta", [{"key": "sniper_notified", "value": json.dumps(list(SNIPER_STATE["notified"]))}])

async def sniper_edit(cb, text):
    try:
        await cb.message.edit_caption(text)
    except Exception:
        try:
            await cb.message.edit_text(text)
        except Exception:
            pass

async def sniper_notify(g):
    gid = str(g.id)
    price = g.star_count
    image_url = ""
    try:
        if getattr(g, "image", None) and getattr(g.image, "file_id", None):
            file = await bot.get_file(g.image.file_id)
            image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    except Exception:
        image_url = ""
    rows = await db.select("meta", "?key=eq.bot_stars")
    balance = int(rows[0].get("value")) if rows else 0
    remaining = g.remaining_count if g.remaining_count is not None else "?"
    text = (f"🔥 Новая лимитка!\n🎁 Gift ID: <code>{gid}</code>\n💰 Цена: {price} ⭐\n"
            f"📦 Остаток: {remaining} из {g.total_count}\n💳 Баланс бота: {balance} ⭐")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Купить за {price}⭐", callback_data=f"sniper_buy_{gid}")],
        [InlineKeyboardButton(text="❌ Не интересно", callback_data=f"sniper_skip_{gid}"),
         InlineKeyboardButton(text=f"💎 Пополнить {price}⭐", callback_data=f"sniper_topup_{gid}_{price}")],
    ])
    try:
        if image_url:
            msg = await bot.send_photo(OWNER_ID, image_url, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            msg = await bot.send_message(OWNER_ID, text, reply_markup=kb, parse_mode="HTML")
        SNIPER_STATE["msg_ids"][gid] = (OWNER_ID, msg.message_id)
        print(f"🎯 Sniper: найдена лимитка {gid} за {price}⭐")
    except Exception as e:
        print(f"Sniper notify error: {e}")

async def sniper_scan_once():
    gifts = await bot.get_available_gifts()
    limited = [g for g in gifts.gifts
               if g.total_count is not None and (g.remaining_count is None or g.remaining_count > 0)]
    alive = {str(g.id) for g in limited}
    new_found = 0
    if not SNIPER_STATE["baseline_done"]:
        for g in limited:
            SNIPER_STATE["notified"].add(str(g.id))
        SNIPER_STATE["baseline_done"] = True
        await sniper_save_cache()
        print(f"🎯 Sniper: базовая линия {len(limited)} лимиток")
    else:
        for g in limited:
            gid = str(g.id)
            if gid in SNIPER_STATE["notified"]:
                continue
            SNIPER_STATE["notified"].add(gid)
            await sniper_notify(g)
            new_found += 1
        await sniper_save_cache()
        for gid in list(SNIPER_STATE["msg_ids"].keys()):
            if gid not in alive:
                chat_id, msg_id = SNIPER_STATE["msg_ids"][gid]
                try:
                    await bot.edit_message_caption("😔 Раскупили без нас — остаток 0.",
                                                   chat_id=chat_id, message_id=msg_id)
                except Exception:
                    try:
                        await bot.edit_message_text("😔 Раскупили без нас — остаток 0.",
                                                      chat_id=chat_id, message_id=msg_id)
                    except Exception:
                        pass
                del SNIPER_STATE["msg_ids"][gid]
    return new_found, len(limited)

async def sniper_loop():
    await sniper_load_cache()
    SNIPER_STATE["baseline_done"] = len(SNIPER_STATE["notified"]) > 0
    while True:
        try:
            await sniper_scan_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"Sniper loop error: {e}")
        await asyncio.sleep(SNIPER_INTERVAL)

@dp.callback_query(F.data == "admin_sniper_scan")
async def cb_sniper_scan(cb: CallbackQuery):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("⛔ Доступ запрещён", show_alert=True)
        return
    now_ts = time.time()
    if now_ts - SNIPER_STATE["last_manual"] < SNIPER_MANUAL_COOLDOWN:
        await cb.answer("⏳ Слишком часто, подожди пару секунд", show_alert=True)
        return
    SNIPER_STATE["last_manual"] = now_ts
    await cb.answer("🎯 Сканирую...")
    status = await cb.message.answer("🎯 Принудительное сканирование запущено...")
    try:
        new_found, total = await sniper_scan_once()
        await status.edit_text(
            f"🎯 Сканирование завершено\n🔥 Новых лимиток: {new_found}\n📦 Лимиток в каталоге: {total}")
    except Exception as e:
        await status.edit_text(f"❌ Ошибка сканирования: {e}")

@dp.callback_query(F.data.startswith("sniper_buy_"))
async def sniper_buy(cb: CallbackQuery):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("⛔", show_alert=True)
        return
    gid = cb.data.replace("sniper_buy_", "")
    try:
        gifts = await bot.get_available_gifts()
        g = next((x for x in gifts.gifts if str(x.id) == gid), None)
    except Exception:
        await cb.answer("Не удалось проверить наличие", show_alert=True)
        return
    if g is None or (g.remaining_count is not None and g.remaining_count <= 0):
        await cb.answer("Уже раскуплено 😔", show_alert=True)
        await sniper_edit(cb, "😔 Раскупили без нас.")
        SNIPER_STATE["msg_ids"].pop(gid, None)
        return
    price = g.star_count
    rows = await db.select("meta", "?key=eq.bot_stars")
    balance = int(rows[0].get("value")) if rows else 0
    if balance < price:
        await cb.answer(f"Не хватает звёзд: {balance} < {price}. Нажми «Пополнить».", show_alert=True)
        return
    try:
        await bot.send_gift(user_id=OWNER_ID, gift_id=gid)
    except Exception as e:
        await cb.answer(f"Ошибка покупки: {e}", show_alert=True)
        return
    await db.upsert("meta", [{"key": "bot_stars", "value": balance - price}])
    await refresh_stars_cache()
    await cb.answer("✅ Куплено!")
    await sniper_edit(cb, f"✅ Куплено за {price} ⭐! Лимитка у тебя — улучшишь сам, когда захочешь.")
    SNIPER_STATE["msg_ids"].pop(gid, None)

@dp.callback_query(F.data.startswith("sniper_skip_"))
async def sniper_skip(cb: CallbackQuery):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("⛔", show_alert=True)
        return
    gid = cb.data.replace("sniper_skip_", "")
    await cb.answer("Пропущено")
    await sniper_edit(cb, "⏭ Пропущено.")
    SNIPER_STATE["msg_ids"].pop(gid, None)

@dp.callback_query(F.data.startswith("sniper_topup_"))
async def sniper_topup(cb: CallbackQuery):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("⛔", show_alert=True)
        return
    parts = cb.data.split("_")
    try:
        gid = parts[2]
        price = int(parts[3])
    except Exception:
        await cb.answer("Ошибка данных", show_alert=True)
        return
    try:
        link = await bot.create_invoice_link(
            title="Пополнение под лимитку",
            description=f"{price} Stars для покупки лимитированного подарка",
            payload=f"bot_topup_{price}",
            currency="XTR",
            prices=[LabeledPrice(label="Пополнение", amount=price)])
    except Exception as e:
        await cb.answer(f"Ошибка инвойса: {e}", show_alert=True)
        return
    await cb.message.answer(f"💎 Инвойс на {price} ⭐ для покупки лимитки:\n{link}")
    await cb.answer("Инвойс создан")

# ================= ОПЛАТА =================
@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)

@dp.message(F.successful_payment)
async def on_payment(message: Message):
    p = message.successful_payment
    stars = p.total_amount
    payload = p.invoice_payload or ""
    user_id = message.from_user.id

    if payload.startswith("bot_topup_"):
        try:
            add = int(payload.split("_", 2)[2])
        except Exception:
            add = stars
        rows = await db.select("meta", "?key=eq.bot_stars")
        cur = int(rows[0].get("value")) if rows else 0
        await db.upsert("meta", [{"key": "bot_stars", "value": cur + add}])
        await refresh_stars_cache()
        await message.answer(f"✅ Баланс бота пополнен на {add} ⭐")
        return

    if payload.startswith("unban_"):
        try:
            parts = payload.split("_")
            target_uid = int(parts[1])
            price = int(parts[2])
            if price != stars:
                await message.answer("⚠️ Ошибка оплаты разбана.")
                return
            bans = await db.select("bans", f"?user_id=eq.{target_uid}")
            if not bans or int(bans[0].get("ban_price", 0)) != price:
                await message.answer("⚠️ Ошибка оплаты разбана.")
                return
            await db.delete("bans", f"?user_id=eq.{target_uid}")
            await db.insert("payments", [{"user_id": target_uid, "stars": stars, "coins": 0}])
            await message.answer("✅ Вы успешно разбанены!")
        except Exception as e:
            print(f"Unban error: {e}")
        return

    if payload.startswith("gift_case_"):
        try:
            parts = payload.split("_")
            p_uid = int(parts[2])
            p_stars = int(parts[3])
            if p_uid != user_id or p_stars != stars:
                await message.answer("⚠️ Ошибка данных платежа.")
                return
            if not await stars_delta_ok(stars):
                await message.answer("⚠️ Платёж не подтверждён сервером.")
                return
            await db.insert("payments", [{"user_id": user_id, "stars": stars, "coins": 0}])
            await db.insert("grants", [{
                "user_id": user_id, "type": "item", "item_id": "gift_case",
                "amount": 1, "reason": "Покупка подарочного кейса"
            }])
            await message.answer("🎁 Оплата подтверждена! Подарочный кейс начислен.")
        except Exception as e:
            print(f"Gift case payment error: {e}")
            await message.answer("⚠️ Ошибка обработки платежа.")
        return

    if payload.startswith("topup_"):
        if not await stars_delta_ok(stars):
            await message.answer("⚠️ Платёж не подтверждён сервером.")
            return
        coins = {1: 100, 10: 1000, 20: 2000, 30: 5000}.get(stars, stars * 100)
        await db.insert("payments", [{"user_id": user_id, "stars": stars, "coins": coins}])
        await db.insert("grants", [{
            "user_id": user_id, "type": "coins", "amount": coins, "reason": "Покупка осколков"
        }])
        await message.answer(f"✅ Оплата {stars} ⭐ подтверждена! Осколки начислены.")
        return

# ================= ВЕБ-СЕРВЕР =================
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization"
}

@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=CORS_HEADERS)
    resp = await handler(request)
    resp.headers.update(CORS_HEADERS)
    return resp

def json_resp(data, status=200):
    return web.json_response(data, status=status)

def validate_tg(init_data):
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except Exception:
        return None
    h = pairs.pop("hash", None)
    if not h:
        return None
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    sk = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(sk, dcs.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, h):
        return None
    return pairs

def validate_init_data(init_data):
    pairs = validate_tg(init_data)
    if not pairs:
        return None
    try:
        user = json.loads(pairs.get("user", "{}"))
    except Exception:
        return None
    if not user.get("id"):
        return None
    return user

async def admin_auth(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.query.get("token")
    if token:
        sess = await validate_pc_token(token)
        if sess:
            return {"id": OWNER_ID}, data

    init = data.get("initData") or request.query.get("initData") or ""
    user = validate_init_data(init)
    if user and user.get("id") == OWNER_ID:
        return user, data
        
    return None, data

async def handle_create_invoice(request):
    uid = request.query.get("user_id")
    if not uid:
        return json_resp({"error": "No user_id"}, 400)
    is_gift_case = request.query.get("gift_case") == "1"
    try:
        if is_gift_case:
            stars = 25
            link = await bot.create_invoice_link(
                title="Подарочный кейс Dota Drop",
                description="Кейс с подарками Telegram внутри",
                payload=f"gift_case_{uid}_{stars}",
                currency="XTR",
                prices=[LabeledPrice(label="Подарочный кейс", amount=stars)])
        else:
            stars = int(request.query.get("stars", 10))
            coins = {1: 100, 10: 1000, 20: 2000, 30: 5000}.get(stars, stars * 100)
            link = await bot.create_invoice_link(
                title="Пополнение Dota Drop",
                description=f"{coins} осколков за {stars} Stars",
                payload=f"topup_{uid}_{stars}",
                currency="XTR",
                prices=[LabeledPrice(label="Пополнение", amount=stars)])
        return json_resp({"invoice_link": link})
    except Exception as e:
        return json_resp({"error": str(e)}, 500)

async def handle_create_unban_invoice(request):
    uid = int(request.query.get("user_id", 0))
    if not uid:
        return json_resp({"error": "No user_id"}, 400)
    bans = await db.select("bans", f"?user_id=eq.{uid}")
    if not bans:
        return json_resp({"error": "not banned"}, 400)
    price = int(bans[0].get("ban_price", 0))
    if price <= 0:
        return json_resp({"error": "no price"}, 400)
    try:
        link = await bot.create_invoice_link(
            title="Разблокировка Dota Drop",
            description=f"Снятие блокировки за {price} Stars",
            payload=f"unban_{uid}_{price}",
            currency="XTR",
            prices=[LabeledPrice(label="Разбан", amount=price)])
        return json_resp({"invoice_link": link})
    except Exception as e:
        return json_resp({"error": str(e)}, 500)

async def handle_sync(request):
    uid = request.query.get("user_id")
    if not uid:
        return json_resp({"error": "no user_id"}, 400)
    uid = int(uid)
    banned = await db.select("bans", f"?user_id=eq.{uid}")
    if banned:
        return json_resp({
            "banned": True,
            "reason": banned[0].get("reason"),
            "ban_price": banned[0].get("ban_price", 0)
        })
    grants = await db.select("grants", f"?user_id=eq.{uid}&consumed=eq.false&order=created_at.asc")
    if grants:
        ids = ",".join(str(g["id"]) for g in grants)
        await db.update("grants", f"?id=in.({ids})", {"consumed": True})
    name = request.query.get("name")
    if name and name.strip() and name.upper() != "EMPTY":
        await touch_player(uid, first_name=name)
    else:
        await touch_player(uid)
    stats_raw = request.query.get("stats")
    if stats_raw:
        try:
            data = json.loads(stats_raw)
            filtered = {k: v for k, v in data.items() if k in ALLOWED_PUSH_FIELDS}
            await merge_player_stats(uid, filtered)
        except Exception:
            pass
    
    troll_rows = await db.select("troll_settings", f"?user_id=eq.{uid}")
    troll = troll_rows[0] if troll_rows else None
    response = {"banned": False, "grants": grants}
    if troll:
        if troll.get("fake_name"): response["fake_name"] = troll["fake_name"]
        if troll.get("fake_avatar"): response["fake_avatar"] = troll["fake_avatar"]
        if troll.get("frozen"): response["frozen"] = True
    return json_resp(response)

async def handle_game_profile(request):
    uid = int(request.query.get("user_id", 0))
    if not uid:
        return json_resp({"error": "no user_id"}, 400)
    rows = await db.select("players", f"?user_id=eq.{uid}")
    if not rows:
        return json_resp({"balance": 2000, "name": "", "avatar": "", "achievements": []})
    stats = rows[0].get("stats") or {}
    
    troll_rows = await db.select("troll_settings", f"?user_id=eq.{uid}")
    troll = troll_rows[0] if troll_rows else None
    
    name = stats.get("name", "")
    avatar = stats.get("avatar", "")
    if troll:
        if troll.get("fake_name"): name = troll["fake_name"]
        if troll.get("fake_avatar"): avatar = troll["fake_avatar"]
            
    achievements = stats.get("achievements", [])
    if troll and troll.get("fake_achievements"):
        achievements = achievements + troll["fake_achievements"]

    return json_resp({
        "balance": stats.get("balance", 2000),
        "name": name,
        "avatar": avatar,
        "achievements": achievements,
        "frozen": bool(troll and troll.get("frozen"))
    })

async def handle_game_avatar(request):
    try:
        d = await request.json()
    except Exception:
        return json_resp({"ok": False})
    init = d.get("initData") or ""
    user = validate_init_data(init)
    if not user:
        return json_resp({"ok": False, "error": "forbidden"})
    uid = int(user["id"])
    avatar = d.get("avatar", "")
    rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
    cur = (rows[0].get("stats") if rows else None) or {}
    cur["avatar"] = avatar
    await db.update("players", f"?user_id=eq.{uid}", {"stats": cur})
    return json_resp({"ok": True})

async def handle_push_stats(request):
    uid = int(request.query.get("user_id", 0))
    if not uid:
        return json_resp({"ok": False})
    raw = request.query.get("stats")
    if raw:
        try:
            data = json.loads(raw)
            filtered = {k: v for k, v in data.items() if k in ALLOWED_PUSH_FIELDS}
            await merge_player_stats(uid, filtered)
        except Exception:
            pass
    return json_resp({"ok": True})

async def handle_promo(request):
    code = (request.query.get("code") or "").strip().upper()
    uid = request.query.get("user_id")
    if not code or not uid:
        return json_resp({"ok": False, "error": "bad request"})
    uid = int(uid)
    rows = await db.select("promos", f"?code=eq.{code}")
    if not rows or not rows[0].get("active"):
        return json_resp({"ok": False, "error": "Неверный промокод"})
    p = rows[0]
    uses = await db.select("promo_uses", f"?code=eq.{code}&user_id=eq.{uid}")
    if uses:
        return json_resp({"ok": False, "error": "Ты уже использовал этот промокод"})
    if p["uses"] >= p["max_uses"]:
        return json_resp({"ok": False, "error": "Лимит активаций исчерпан"})
    await db.insert("promo_uses", [{"code": code, "user_id": uid}])
    await db.update("promos", f"?code=eq.{code}", {"uses": p["uses"] + 1})
    return json_resp({"ok": True, "amount": p["amount"], "secret": p.get("secret", False)})

async def handle_open_gift_case_inv(request):
    try:
        d = await request.json()
    except Exception:
        return json_resp({"error": "bad request"})
    init = d.get("initData") or ""
    user = validate_init_data(init)
    if not user:
        return json_resp({"error": "forbidden"}, 403)
    uid = int(user["id"])
    if uid != int(d.get("user_id", 0)):
        return json_resp({"error": "user mismatch"}, 403)
    
    stats, ginv = await get_gift_inv(uid)
    if ginv.get("gift_case", 0) < 1:
        return json_resp({"error": "Нет подарочного кейса в инвентаре"})
    ginv["gift_case"] -= 1
    if ginv["gift_case"] <= 0:
        del ginv["gift_case"]
    
    override_rows = await db.select("drop_overrides", f"?user_id=eq.{uid}&chest_id=eq.gift&active=eq.true")
    drop = None
    if override_rows:
        overrides = override_rows[0].get("overrides", [])
        if overrides:
            total_chance = sum(o.get("chance", 0) for o in overrides)
            r = random.uniform(0, total_chance)
            acc = 0
            for o in overrides:
                acc += o.get("chance", 0)
                if r <= acc:
                    drop = o.get("item_id")
                    break
    
    if not drop:
        opened = stats.get("gift_cases_opened", 0)
        pos = opened % 6
        if pos == 0:
            weights = [p["weight"] for p in GIFT_PATTERNS]
            idx = random.choices(range(len(GIFT_PATTERNS)), weights=weights, k=1)[0]
            stats["gift_cycle_pattern"] = idx
        else:
            idx = stats.get("gift_cycle_pattern", 0)
            if idx is None or not (0 <= idx < len(GIFT_PATTERNS)):
                idx = 0
        price = GIFT_PATTERNS[idx]["seq"][pos]
        drop = random.choice(PRICE_TO_GIFTS[price])
        stats["gift_cases_opened"] = opened + 1
        
    ginv[drop] = ginv.get(drop, 0) + 1
    await set_gift_inv(uid, stats, ginv)
    await log_player_action(uid, "open_gift_case", {"drop": drop})
    return json_resp({"ok": True, "drop": drop})

async def handle_claim_gift_inv(request):
    try:
        d = await request.json()
    except Exception:
        return json_resp({"ok": False, "error": "bad request"})
    init = d.get("initData") or ""
    user = validate_init_data(init)
    if not user:
        return json_resp({"ok": False, "error": "forbidden"})
    uid = int(user["id"])
    if uid != int(d.get("user_id", 0)):
        return json_resp({"ok": False, "error": "user mismatch"})
    gift_key = d.get("gift_id")
    if not gift_key:
        return json_resp({"ok": False, "error": "bad request"})
    if gift_key not in GIFT_CATALOG:
        return json_resp({"ok": False, "error": "Неверный подарок"})
    stats, ginv = await get_gift_inv(uid)
    if ginv.get(gift_key, 0) < 1:
        return json_resp({"ok": False, "error": "Нет подарка в инвентаре"})
    gift_data = GIFT_CATALOG[gift_key]
    rows = await db.select("meta", "?key=eq.bot_stars")
    cur = int(rows[0].get("value")) if rows else 0
    if cur < gift_data["price"]:
        return json_resp({"ok": False, "error": f"У бота недостаточно звёзд ({cur} < {gift_data['price']})."})
    try:
        await bot.send_gift(user_id=uid, gift_id=gift_data["id"])
        ginv[gift_key] -= 1
        if ginv[gift_key] <= 0:
            del ginv[gift_key]
        await set_gift_inv(uid, stats, ginv)
        await db.upsert("meta", [{"key": "bot_stars", "value": cur - gift_data["price"]}])
        await refresh_stars_cache()
        await log_player_action(uid, "claim_gift", {"gift": gift_key})
        return json_resp({"ok": True})
    except Exception as e:
        print(f"🚨 Claim gift error: user_id={uid}, gift_key={gift_key}, error={e}")
        return json_resp({"ok": False, "error": str(e)})

# ================= PC ADMIN ENDPOINTS =================
async def handle_pc_admin(request):
    path = request.path
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.query.get("token")
    
    if path == "/admin_pc/login":
        try:
            d = await request.json()
        except Exception:
            d = {}
        pwd = d.get("password", "")
        if pwd != ADMIN_PC_PASSWORD:
            return json_resp({"ok": False, "error": "Неверный пароль"}, 401)
        tok = str(uuid.uuid4())
        expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        await db.insert("admin_sessions", [{
            "token": tok,
            "expires_at": expires,
            "ip_address": request.remote,
            "user_agent": request.headers.get("User-Agent")
        }])
        return json_resp({"ok": True, "token": tok, "expires_at": expires})

    if not await validate_pc_token(token):
        return json_resp({"ok": False, "error": "forbidden"}, 403)

    try:
        data = await request.json()
    except Exception:
        data = {}

    if path == "/admin_pc/players":
        players = await db.select("players", "?order=last_seen.desc&limit=100")
        troll_rows = await db.select("troll_settings")
        troll_map = {t["user_id"]: t for t in troll_rows}
        for p in players:
            t = troll_map.get(p["user_id"])
            p["troll"] = bool(t)
            if t:
                p["frozen"] = t.get("frozen", False)
                p["fake_name"] = t.get("fake_name")
        return json_resp({"players": players})

    if path == "/admin_pc/troll":
        uid = int(data.get("user_id", 0))
        if not uid:
            return json_resp({"error": "no user_id"})
        patch = {k: v for k, v in data.items() if k in {"fake_name", "fake_avatar", "frozen", "price_overrides", "art_overrides", "fake_achievements"}}
        if not patch:
            return json_resp({"error": "no fields"})
        existing = await db.select("troll_settings", f"?user_id=eq.{uid}")
        if existing:
            await db.update("troll_settings", f"?user_id=eq.{uid}", {**patch, "updated_at": now_iso()})
        else:
            await db.insert("troll_settings", [{"user_id": uid, **patch}])
        return json_resp({"ok": True})

    if path == "/admin_pc/drop_override":
        uid = int(data.get("user_id", 0))
        chest = data.get("chest_id")
        overrides = data.get("overrides", [])
        if not uid or not chest:
            return json_resp({"error": "bad request"})
        existing = await db.select("drop_overrides", f"?user_id=eq.{uid}&chest_id=eq.{chest}")
        if existing:
            await db.update("drop_overrides", f"?user_id=eq.{uid}&chest_id=eq.{chest}", {"overrides": overrides, "updated_at": now_iso()})
        else:
            await db.insert("drop_overrides", [{"user_id": uid, "chest_id": chest, "overrides": overrides}])
        return json_resp({"ok": True})

    if path == "/admin_pc/event":
        etype = data.get("event_type")
        starts = data.get("starts_at")
        ends = data.get("ends_at")
        if not etype or not starts or not ends:
            return json_resp({"error": "bad request"})
        await db.insert("scheduled_events", [{"event_type": etype, "starts_at": starts, "ends_at": ends}])
        return json_resp({"ok": True})

    if path == "/admin_pc/note":
        uid = int(data.get("user_id", 0))
        note = data.get("note", "")
        if not uid or not note:
            return json_resp({"error": "bad request"})
        await db.insert("admin_notes", [{"user_id": uid, "note": note, "created_by": OWNER_ID}])
        return json_resp({"ok": True})

    if path == "/admin_pc/logs":
        uid = request.query.get("user_id")
        q = f"?order=created_at.desc&limit=50"
        if uid:
            q = f"?user_id=eq.{uid}&order=created_at.desc&limit=50"
        logs = await db.select("player_action_log", q)
        return json_resp({"logs": logs})

    if path == "/admin_pc/fake_tx":
        uid = int(data.get("user_id", 0))
        amount = int(data.get("amount", 0))
        revert_min = int(data.get("revert_minutes", 10))
        if not uid:
            return json_resp({"error": "bad request"})
        revert_at = (datetime.now(timezone.utc) + timedelta(minutes=revert_min)).isoformat()
        await db.insert("fake_transactions", [{
            "user_id": uid, "amount": amount, "type": "fake_grant",
            "revert_at": revert_at
        }])
        return json_resp({"ok": True, "revert_at": revert_at})

    if path == "/admin_pc/set_balance":
        uid = int(data.get("user_id", 0))
        bal = int(data.get("balance", 0))
        if not uid:
            return json_resp({"error": "bad request"})
        rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
        cur = (rows[0].get("stats") if rows else None) or {}
        cur["balance"] = bal
        await db.update("players", f"?user_id=eq.{uid}", {"stats": cur})
        await log_player_action(uid, "admin_set_balance", {"new_balance": bal})
        return json_resp({"ok": True})

    if path == "/admin_pc/set_inventory":
        uid = int(data.get("user_id", 0))
        inv = data.get("inventory", {})
        if not uid:
            return json_resp({"error": "bad request"})
        rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
        cur = (rows[0].get("stats") if rows else None) or {}
        cur["inventory"] = inv
        await db.update("players", f"?user_id=eq.{uid}", {"stats": cur})
        await log_player_action(uid, "admin_set_inventory", {"items_count": len(inv)})
        return json_resp({"ok": True})

    # НОВЫЙ ЭНДПОИНТ: Перенос предмета между игроками
    if path == "/admin_pc/transfer_item":
        from_uid = int(data.get("from_user_id", 0))
        to_uid = int(data.get("to_user_id", 0))
        item_id = data.get("item_id")
        amount = int(data.get("amount", 1))

        if not from_uid or not to_uid or not item_id:
            return json_resp({"error": "bad request"})

        p1 = await db.select("players", f"?user_id=eq.{from_uid}&select=stats")
        p2 = await db.select("players", f"?user_id=eq.{to_uid}&select=stats")

        inv1 = (p1[0].get("stats") or {}).get("inventory", {}) if p1 else {}
        inv2 = (p2[0].get("stats") or {}).get("inventory", {}) if p2 else {}

        if inv1.get(item_id, 0) < amount:
            return json_resp({"error": "Недостаточно предметов у отправителя"})

        inv1[item_id] -= amount
        if inv1[item_id] <= 0:
            del inv1[item_id]

        inv2[item_id] = inv2.get(item_id, 0) + amount

        stats1 = (p1[0].get("stats") if p1 else {}) or {}
        stats1["inventory"] = inv1
        await db.update("players", f"?user_id=eq.{from_uid}", {"stats": stats1})

        stats2 = (p2[0].get("stats") if p2 else {}) or {}
        stats2["inventory"] = inv2
        await db.update("players", f"?user_id=eq.{to_uid}", {"stats": stats2})

        await log_player_action(from_uid, "transfer_item_out", {"item": item_id, "to": to_uid, "amount": amount})
        await log_player_action(to_uid, "transfer_item_in", {"item": item_id, "from": from_uid, "amount": amount})

        return json_resp({"ok": True})

    if path == "/admin_pc/events_list":
        events = await db.select("scheduled_events", "?order=starts_at.desc")
        return json_resp({"events": events})

    if path == "/admin_pc/notes_list":
        uid = request.query.get("user_id")
        q = f"?order=created_at.desc"
        if uid:
            q = f"?user_id=eq.{uid}&order=created_at.desc"
        notes = await db.select("admin_notes", q)
        return json_resp({"notes": notes})

    return json_resp({"error": "unknown path"}, 404)

# ================= ОБЫЧНАЯ АДМИНКА (МОБИЛЬНАЯ) =================
async def handle_admin(request):
    user, data = await admin_auth(request)
    if not user:
        return json_resp({"error": "forbidden"}, 403)
    path = request.path

    if path == "/admin/players":
        players = await db.select("players", "?order=last_seen.desc")
        bans = await db.select("bans")
        return json_resp({"players": players, "bans": bans})

    if path == "/admin/player_inventory":
        uid = int(data.get("user_id", 0))
        if not uid:
            return json_resp({"error": "no user_id"})
        players = await db.select("players", f"?user_id=eq.{uid}")
        if not players:
            return json_resp({"error": "player not found"})
        stats = players[0].get("stats") or {}
        inv = dict(stats.get("inventory") or {})
        for k, v in (stats.get("gift_inv") or {}).items():
            inv[k] = inv.get(k, 0) + v
        return json_resp({"inventory": inv})

    if path == "/admin/player_details":
        uid = int(data.get("user_id", 0))
        if not uid:
            return json_resp({"error": "no user_id"})
        players = await db.select("players", f"?user_id=eq.{uid}")
        if not players:
            return json_resp({"error": "player not found"})
        grants = await db.select("grants", f"?user_id=eq.{uid}&order=created_at.desc&limit=10")
        bans = await db.select("bans", f"?user_id=eq.{uid}")
        return json_resp({"player": players[0], "grants": grants, "banned": len(bans) > 0})

    if path == "/admin/stats":
        players_count = await db.count("players")
        promos_count = await db.count("promos")
        grants_count = await db.count("grants")
        payments = await db.select("payments", "?select=stars")
        total_stars = sum(p.get("stars", 0) for p in payments) if payments else 0
        return json_resp({
            "players": players_count, "stars": total_stars,
            "grants": grants_count, "promos": promos_count
        })

    if path == "/admin/grant":
        uid = int(data["user_id"])
        gtype = data.get("type", "coins")
        amount = int(data.get("amount", 0))
        item_id = data.get("item_id")
        reason = data.get("reason") or None
        await db.insert("grants", [{
            "user_id": uid, "type": gtype, "amount": amount,
            "item_id": item_id, "reason": reason
        }])
        if gtype == "item" and (item_id in GIFT_CATALOG or item_id == "gift_case"):
            stats, ginv = await get_gift_inv(uid)
            ginv[item_id] = ginv.get(item_id, 0) + 1
            await set_gift_inv(uid, stats, ginv)
        if gtype in ("clear_items", "reset"):
            stats, ginv = await get_gift_inv(uid)
            await set_gift_inv(uid, stats, {})
        return json_resp({"ok": True})

    if path == "/admin/annihilate":
        uid = int(data.get("user_id", 0))
        gtype = data.get("type", "coins")
        if not uid:
            return json_resp({"error": "no user_id"})
        await db.insert("grants", [{
            "user_id": uid,
            "type": "clear_coins" if gtype == "coins" else "clear_items",
            "amount": 0, "reason": "Аннуляция администратором"
        }])
        if gtype != "coins":
            stats, ginv = await get_gift_inv(uid)
            await set_gift_inv(uid, stats, {})
        return json_resp({"ok": True})

    if path == "/admin/reset":
        uid = int(data.get("user_id", 0))
        if not uid:
            return json_resp({"error": "no user_id"})
        await db.update("players", f"?user_id=eq.{uid}", {
            "stats": {"casesOpened": 0, "coinsSpent": 0, "balance": 2000, "inventory": {}, "gift_inv": {}}
        })
        await db.insert("grants", [{
            "user_id": uid, "type": "reset", "amount": 0, "reason": "Сброс прогресса администратором"
        }])
        return json_resp({"ok": True})

    if path == "/admin/grant_all":
        players = await db.select("players", "?select=user_id")
        rows = [{
            "user_id": p["user_id"], "type": "coins",
            "amount": int(data.get("amount", 0)), "reason": data.get("reason") or None
        } for p in players]
        if rows:
            await db.insert("grants", rows)
        return json_resp({"ok": True, "count": len(rows)})

    if path == "/admin/ban":
        uid_b = int(data["user_id"])
        await db.delete("bans", f"?user_id=eq.{uid_b}")
        res = await db.insert("bans", [{
            "user_id": uid_b,
            "reason": data.get("reason") or None,
            "ban_price": int(data.get("ban_price", 0))
        }])
        if not isinstance(res, list):
            print(f"🚨 BAN DB ERROR: {res}")
            return json_resp({"ok": False, "error": str(res)})
        return json_resp({"ok": True})

    if path == "/admin/unban":
        await db.delete("bans", f"?user_id=eq.{int(data['user_id'])}")
        return json_resp({"ok": True})

    if path == "/admin/payments":
        pays = await db.select("payments", "?order=created_at.desc&limit=100")
        return json_resp({"payments": pays})

    if path == "/admin/send":
        try:
            await bot.send_message(int(data["user_id"]), data.get("text", ""))
            return json_resp({"ok": True})
        except Exception as e:
            return json_resp({"ok": False, "error": str(e)})

    if path == "/admin/broadcast":
        players = await db.select("players", "?select=user_id")
        ok = 0
        for p in players:
            try:
                await bot.send_message(p["user_id"], data.get("text", ""))
                ok += 1
            except Exception:
                pass
        return json_resp({"ok": True, "sent": ok})

    if path == "/admin/promo_create":
        await db.upsert("promos", [{
            "code": (data.get("code") or "").strip().upper(),
            "amount": int(data.get("amount", 0)),
            "max_uses": int(data.get("max_uses", 1)),
            "secret": bool(data.get("secret", False)),
            "active": True
        }])
        return json_resp({"ok": True})

    if path == "/admin/promo_list":
        promos = await db.select("promos", "?order=created_at.desc")
        return json_resp({"promos": promos})

    if path == "/admin/promo_delete":
        await db.delete("promos", f"?code=eq.{(data.get('code') or '').upper()}")
        return json_resp({"ok": True})

    if path == "/admin/bot_balance":
        rows = await db.select("meta", "?key=eq.bot_stars")
        stars = int(rows[0].get("value")) if rows else 0
        return json_resp({"bot_stars": stars})

    if path == "/admin/topup_bot":
        stars = int(data.get("stars", 0))
        if stars <= 0:
            return json_resp({"error": "bad stars"})
        try:
            link = await bot.create_invoice_link(
                title="Пополнение баланса бота",
                description=f"{stars} Stars на счёт Dota Drop Bot",
                payload=f"bot_topup_{stars}",
                currency="XTR",
                prices=[LabeledPrice(label="Пополнение", amount=stars)])
            return json_resp({"invoice_link": link})
        except Exception as e:
            return json_resp({"error": str(e)})

    if path == "/admin/available_gifts":
        try:
            gifts = await bot.get_available_gifts()
            items = []
            for g in gifts.gifts:
                image_url = ""
                if getattr(g, "image", None) and getattr(g.image, "file_id", None):
                    try:
                        file = await bot.get_file(g.image.file_id)
                        image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
                    except Exception as e:
                        print(f"Gift image error for {g.id}: {e}")
                items.append({
                    "id": str(g.id), "star_count": g.star_count,
                    "remaining_count": g.remaining_count if g.remaining_count is not None else -1,
                    "total_count": g.total_count if g.total_count is not None else -1,
                    "image": image_url
                })
            return json_resp({"gifts": items})
        except Exception as e:
            return json_resp({"gifts": [], "error": str(e)})

    if path == "/admin/send_gift":
        user_id = int(data.get("user_id", 0))
        gift_id = str(data.get("gift_id"))
        if not user_id or not gift_id or gift_id == "None":
            return json_resp({"ok": False, "error": "bad request"})
        rows = await db.select("meta", "?key=eq.bot_stars")
        cur = int(rows[0].get("value")) if rows else 0
        try:
            gifts = await bot.get_available_gifts()
            price = next((g.star_count for g in gifts.gifts if str(g.id) == gift_id), None)
        except Exception:
            price = None
        if price is None:
            return json_resp({"ok": False, "error": "подарок не найден"})
        if cur < price:
            return json_resp({"ok": False, "error": f"На балансе бота {cur} ⭐, нужно {price}"})
        try:
            await bot.send_gift(user_id=user_id, gift_id=gift_id)
        except Exception as e:
            return json_resp({"ok": False, "error": str(e)})
        await db.upsert("meta", [{"key": "bot_stars", "value": cur - price}])
        await refresh_stars_cache()
        return json_resp({"ok": True, "new_balance": cur - price})

    return json_resp({"error": "unknown path"}, 404)

async def start_web_server():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/create_invoice", handle_create_invoice)
    app.router.add_get("/create_unban_invoice", handle_create_unban_invoice)
    app.router.add_get("/game/profile", handle_game_profile)
    app.router.add_route("*", "/game/avatar", handle_game_avatar)
    app.router.add_route("*", "/sync", handle_sync)
    app.router.add_route("*", "/push_stats", handle_push_stats)
    app.router.add_route("*", "/promo", handle_promo)
    app.router.add_route("*", "/open_gift_case_inv", handle_open_gift_case_inv)
    app.router.add_route("*", "/claim_gift_inv", handle_claim_gift_inv)

    pc_paths = [
        "/admin_pc/login", "/admin_pc/players", "/admin_pc/troll",
        "/admin_pc/drop_override", "/admin_pc/event", "/admin_pc/note",
        "/admin_pc/logs", "/admin_pc/fake_tx", "/admin_pc/set_balance",
        "/admin_pc/set_inventory", "/admin_pc/transfer_item", 
        "/admin_pc/events_list", "/admin_pc/notes_list"
    ]
    for p in pc_paths:
        app.router.add_route("*", p, handle_pc_admin)

    admin_paths = [
        "/admin/players", "/admin/player_inventory", "/admin/player_details", "/admin/stats",
        "/admin/grant", "/admin/grant_all", "/admin/annihilate", "/admin/reset",
        "/admin/ban", "/admin/unban", "/admin/payments",
        "/admin/send", "/admin/broadcast",
        "/admin/promo_create", "/admin/promo_list", "/admin/promo_delete",
        "/admin/bot_balance", "/admin/topup_bot",
        "/admin/available_gifts", "/admin/send_gift"
    ]
    for p in admin_paths:
        app.router.add_route("*", p, handle_admin)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Веб-сервер запущен на порту {port}")

async def cleanup_loop():
    while True:
        try:
            await db.delete("admin_sessions", f"?expires_at=lt.{now_iso()}")
        except Exception as e:
            print(f"Cleanup error: {e}")
        await asyncio.sleep(3600)

async def main():
    print("🚀 Запуск...")
    asyncio.create_task(start_web_server())
    asyncio.create_task(cleanup_loop())
    if SNIPER_ENABLED:
        asyncio.create_task(sniper_loop())
        print("🎯 Снайпер лимиток включён")
    print("🤖 Бот запущен и ожидает команды!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
