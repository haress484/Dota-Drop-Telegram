import asyncio
import json
import os
import hmac
import hashlib
import logging
from datetime import datetime, timezone
from urllib.parse import parse_qsl

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (Message, CallbackQuery, LabeledPrice, WebAppInfo,
                           InlineKeyboardButton, InlineKeyboardMarkup, PreCheckoutQuery)
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

# ================= SUPABASE =================
class DB:
    def __init__(self):
        self.base = SUPABASE_URL + "/rest/v1"
        self.h = {"apikey": SUPABASE_KEY,
                  "Authorization": "Bearer " + SUPABASE_KEY,
                  "Content-Type": "application/json",
                  "Prefer": "return=representation"}

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

db = DB()

async def touch_player(user_id, username=None, first_name=None):
    row = {"user_id": user_id, "last_seen": now_iso()}
    if username is not None:
        row["username"] = username
    if first_name is not None:
        row["first_name"] = first_name
    await db.upsert("players", [row])

async def merge_player_stats(uid, patch):
    rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
    cur = (rows[0].get("stats") if rows else None) or {}
    cur.update(patch)
    await db.update("players", f"?user_id=eq.{uid}", {"stats": cur})

# ================= КЛАВИАТУРЫ / ПОДПИСКА =================
def play_kb(user_id):
    rows = [[InlineKeyboardButton(text="🎮 ИГРАТЬ", web_app=WebAppInfo(url=WEB_APP_URL))]]
    if user_id == OWNER_ID:
        rows.append([InlineKeyboardButton(text="🛠 АДМИНКА", web_app=WebAppInfo(url=ADMIN_URL))])
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

# ================= ОПЛАТА =================
@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)

@dp.message(F.successful_payment)
async def on_payment(message: Message):
    p = message.successful_payment
    stars = p.total_amount
    coins = {1: 100, 10: 1000, 20: 2000, 30: 5000}.get(stars, stars * 100)
    await db.insert("payments", [{"user_id": message.from_user.id, "stars": stars, "coins": coins}])
    await message.answer(f"✅ Оплата {stars} ⭐ прошла! Осколки уже в игре.")

# ================= ВЕБ-СЕРВЕР =================
CORS_HEADERS = {"Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type"}

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
    stars = int(request.query.get("stars", 10))
    if not uid:
        return json_resp({"error": "No user_id"}, 400)
    coins = {1: 100, 10: 1000, 20: 2000, 30: 5000}.get(stars, stars * 100)
    try:
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
        return json_resp({"banned": True, "reason": banned[0].get("reason")})
    grants = await db.select("grants", f"?user_id=eq.{uid}&consumed=eq.false")
    if grants:
        ids = ",".join(str(g["id"]) for g in grants)
        await db.update("grants", f"?id=in.({ids})", {"consumed": True})
    name = request.query.get("name")
    await touch_player(uid, first_name=name)
    stats_raw = request.query.get("stats")
    if stats_raw:
        try:
            await merge_player_stats(uid, json.loads(stats_raw))
        except Exception:
            pass
    return json_resp({"banned": False, "grants": grants})

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

async def handle_admin(request):
    user, data = await admin_auth(request)
    if not user:
        return json_resp({"error": "forbidden"}, 403)
    path = request.path

    if path == "/admin/players":
        players = await db.select("players", "?order=last_seen.desc")
        bans = await db.select("bans")
        return json_resp({"players": players, "bans": bans})

    if path == "/admin/grant":
        await db.insert("grants", [{
            "user_id": int(data["user_id"]),
            "type": data.get("type", "coins"),
            "amount": int(data.get("amount", 0)),
            "item_id": data.get("item_id"),
            "reason": data.get("reason") or None}])
        return json_resp({"ok": True})

    if path == "/admin/grant_all":
        players = await db.select("players", "?select=user_id")
        rows = [{"user_id": p["user_id"], "type": "coins",
                 "amount": int(data.get("amount", 0)),
                 "reason": data.get("reason") or None} for p in players]
        if rows:
            await db.insert("grants", rows)
        return json_resp({"ok": True, "count": len(rows)})

    if path == "/admin/ban":
        await db.upsert("bans", [{"user_id": int(data["user_id"]),
                                  "reason": data.get("reason") or None}])
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
            "active": True}])
        return json_resp({"ok": True})

    if path == "/admin/promo_list":
        promos = await db.select("promos", "?order=created_at.desc")
        return json_resp({"promos": promos})

    if path == "/admin/promo_delete":
        await db.delete("promos", f"?code=eq.{(data.get('code') or '').upper()}")
        return json_resp({"ok": True})

    return json_resp({"error": "unknown path"}, 404)

async def handle_dbtest(request):
    sel = await db.select("players", "?limit=1")
    up = await db.upsert("meta", [{"key": "dbtest", "value": {"t": now_iso()}}])
    back = await db.select("meta", "?key=eq.dbtest")
    return json_resp({
        "url_set": bool(SUPABASE_URL),
        "key_set": bool(SUPABASE_KEY),
        "select_players": sel,
        "upsert_meta": up,
        "read_back": back})

async def start_web_server():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/create_invoice", handle_create_invoice)
    app.router.add_get("/dbtest", handle_dbtest)
    app.router.add_route("*", "/sync", handle_sync)
    app.router.add_route("*", "/promo", handle_promo)
    for p in ["/admin/players", "/admin/grant", "/admin/grant_all", "/admin/ban",
              "/admin/unban", "/admin/payments", "/admin/send", "/admin/broadcast",
              "/admin/promo_create", "/admin/promo_list", "/admin/promo_delete"]:
        app.router.add_route("*", p, handle_admin)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Веб-сервер запущен на порту {port}")

# ================= ЗАПУСК =================
async def main():
    print("🚀 Запуск...")
    asyncio.create_task(start_web_server())
    print("🤖 Бот запущен и ожидает команды!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
