import asyncio
import json
import os
import hmac
import hashlib
import logging
import random
from datetime import datetime, timezone
from urllib.parse import parse_qsl

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (Message, CallbackQuery, LabeledPrice, WebAppInfo,
                           InlineKeyboardButton, InlineKeyboardMarkup, PreCheckoutQuery)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise SystemExit("❌ Не задан BOT_TOKEN в Environment на Render!")

CHANNEL_USERNAME = "@the_kubicki"
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://haress484.github.io/Dota-Drop-Telegram/").rstrip("/") + "/"
ADMIN_URL = WEB_APP_URL + "admin.html"
OWNER_ID = 1837442717

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

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

# ================= СЕРВЕРНЫЙ ПОДАРОЧНЫЙ ИНВЕНТАРЬ =================
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

# ================= ЗАЩИТА: ПРОВЕРКА РЕАЛЬНОГО БАЛАНСА ЗВЁЗД =================
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
    """Оплата засчитывается ТОЛЬКО если реальный баланс бота вырос на сумму платежа."""
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

# ================= КЛАВИАТУРЫ =================
def play_kb(user_id):
    rows = [[InlineKeyboardButton(text="🎮 ИГРАТЬ", web_app=WebAppInfo(url=WEB_APP_URL))]]
    if user_id == OWNER_ID:
        rows.append([InlineKeyboardButton(text="🛠 АДМИНКА", web_app=WebAppInfo(url=ADMIN_URL))])
        rows.append([InlineKeyboardButton(text="🎁 ПОДАРОК", callback_data="admin_gift")])
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
async def cmd_start(message: Message):
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

    # 1. Пополнение баланса бота
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

    # 2. Платный разбан
    if payload.startswith("unban_"):
        try:
            target_uid = int(payload.split("_")[1])
            await db.delete("bans", f"?user_id=eq.{target_uid}")
            await message.answer("✅ Вы успешно разбанены! Добро пожаловать обратно.")
        except Exception as e:
            print(f"Unban error: {e}")
        return

    # 3. Покупка подарочного кейса: проверка баланса -> выдача через grant
    if payload.startswith("gift_case_"):
        try:
            parts = payload.split("_")
            p_uid = int(parts[2])
            p_stars = int(parts[3])
            if p_uid != user_id or p_stars != stars:
                await message.answer("⚠️ Ошибка данных платежа. Обратитесь в поддержку.")
                return
            if not await stars_delta_ok(stars):
                await message.answer("⚠️ Платёж не подтверждён сервером Telegram. Обратитесь в поддержку.")
                return
            await db.insert("payments", [{"user_id": user_id, "stars": stars, "coins": 0}])
            await db.insert("grants", [{
                "user_id": user_id, "type": "item", "item_id": "gift_case",
                "amount": 1, "reason": "Покупка подарочного кейса"
            }])
            await message.answer("🎁 Оплата подтверждена! Подарочный кейс начислен в игру.")
        except Exception as e:
            print(f"Gift case payment error: {e}")
            await message.answer("⚠️ Ошибка обработки платежа. Обратитесь в поддержку.")
        return

    # 4. Обычное пополнение осколков: проверка баланса -> выдача через grant
    if payload.startswith("topup_"):
        if not await stars_delta_ok(stars):
            await message.answer("⚠️ Платёж не подтверждён сервером Telegram. Обратитесь в поддержку.")
            return
        coins = {1: 100, 10: 1000, 20: 2000, 30: 5000}.get(stars, stars * 100)
        await db.insert("payments", [{"user_id": user_id, "stars": stars, "coins": coins}])
        await db.insert("grants", [{
            "user_id": user_id, "type": "coins", "amount": coins, "reason": "Покупка осколков"
        }])
        await message.answer(f"✅ Оплата {stars} ⭐ подтверждена! Осколки начислены в игру.")
        return

# ================= ВЕБ-СЕРВЕР =================
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type"
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
            await merge_player_stats(uid, json.loads(stats_raw))
        except Exception:
            pass
    return json_resp({"banned": False, "grants": grants})

async def handle_push_stats(request):
    uid = int(request.query.get("user_id", 0))
    if not uid:
        return json_resp({"ok": False})
    raw = request.query.get("stats")
    if raw:
        try:
            await merge_player_stats(uid, json.loads(raw))
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

# ---- открытие подарочного кейса (цикл 6 открытий) ----
async def handle_open_gift_case_inv(request):
    uid = int(request.query.get("user_id", 0))
    if not uid:
        return json_resp({"error": "no user_id"})
    stats, ginv = await get_gift_inv(uid)
    if ginv.get("gift_case", 0) < 1:
        return json_resp({"error": "Нет подарочного кейса в инвентаре"})
    ginv["gift_case"] -= 1
    if ginv["gift_case"] <= 0:
        del ginv["gift_case"]
    opened = stats.get("gift_cases_opened", 0)
    cycle = opened % 6
    if cycle in (0, 1, 3, 4):
        drop = random.choice(["gift_heart", "gift_teddy"])
    elif cycle == 2:
        drop = random.choice(["gift_box", "gift_rose"])
    else:
        drop = random.choice(["gift_cake", "gift_bouquet"])
    ginv[drop] = ginv.get(drop, 0) + 1
    stats["gift_cases_opened"] = opened + 1
    await set_gift_inv(uid, stats, ginv)
    return json_resp({"ok": True, "drop": drop})

# ---- получение подарка из инвентаря ----
async def handle_claim_gift_inv(request):
    try:
        d = await request.json()
    except Exception:
        return json_resp({"ok": False, "error": "bad request"})
    uid = int(d.get("user_id", 0))
    gift_key = d.get("gift_id")
    if not uid or not gift_key:
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
        return json_resp({"ok": False, "error": f"У бота недостаточно звёзд ({cur} < {gift_data['price']}). Напишите админу."})
    try:
        await bot.send_gift(user_id=uid, gift_id=gift_data["id"])
        ginv[gift_key] -= 1
        if ginv[gift_key] <= 0:
            del ginv[gift_key]
        await set_gift_inv(uid, stats, ginv)
        await db.upsert("meta", [{"key": "bot_stars", "value": cur - gift_data["price"]}])
        await refresh_stars_cache()
        return json_resp({"ok": True})
    except Exception as e:
        print(f"🚨 Claim gift error: user_id={uid}, gift_key={gift_key}, error={e}")
        return json_resp({"ok": False, "error": str(e)})

# ---- проверка админа ----
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

async def admin_auth(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    init = data.get("initData") or request.query.get("initData") or ""
    pairs = validate_tg(init)
    if not pairs:
        return None, data
    try:
        user = json.loads(pairs.get("user", "{}"))
    except Exception:
        return None, data
    if user.get("id") != OWNER_ID:
        return None, data
    return user, data

# ---- админ-эндпоинты ----
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
    app.router.add_route("*", "/sync", handle_sync)
    app.router.add_route("*", "/push_stats", handle_push_stats)
    app.router.add_route("*", "/promo", handle_promo)
    app.router.add_route("*", "/open_gift_case_inv", handle_open_gift_case_inv)
    app.router.add_route("*", "/claim_gift_inv", handle_claim_gift_inv)

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

async def main():
    print("🚀 Запуск...")
    asyncio.create_task(start_web_server())
    print("🤖 Бот запущен и ожидает команды!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
