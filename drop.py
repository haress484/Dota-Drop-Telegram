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
    # Обновляем username только если он передан и не пустой
    if username and username.strip():
        row["username"] = username
    # Обновляем first_name только если он передан и не "EMPTY"/пустой
    if first_name and first_name.strip() and first_name.upper() != "EMPTY":
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
    [InlineKeyboardButton(text=" Подписаться на канал", url="https://t.me/the_kubicki")],
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
            " Добро пожаловать в Dota Drop!\nЖми кнопку ниже, чтобы играть.",
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
    payload = p.invoice_payload or ""

    if payload.startswith("bot_topup_"):
        try:
            add = int(payload.split("_", 2)[2])
        except Exception:
            add = stars
        rows = await db.select("meta", "?key=eq.bot_stars")
        cur = 0
        if rows:
            try:
                cur = int(rows[0].get("value"))
            except Exception:
                pass
        await db.upsert("meta", [{"key": "bot_stars", "value": cur + add}])
        await message.answer(f"✅ Пополнено {add} ⭐ на баланс бота!")
        return

    coins = {1: 100, 10: 1000, 20: 2000, 30: 5000}.get(stars, stars * 100)
    await db.insert("payments", [{"user_id": message.from_user.id, "stars": stars, "coins": coins}])
    await message.answer(f"✅ Оплата {stars} ⭐ прошла! Осколки уже в игре.")

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

# ---- создание счёта на звёзды ----
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

# ---- синхронизация страницы ----
async def handle_sync(request):
    uid = request.query.get("user_id")
    if not uid:
        return json_resp({"error": "no user_id"}, 400)
    uid = int(uid)
    
    banned = await db.select("bans", f"?user_id=eq.{uid}")
    if banned:
        return json_resp({"banned": True, "reason": banned[0].get("reason")})
    
    grants = await db.select("grants", f"?user_id=eq.{uid}&consumed=eq.false&order=created_at.asc")
    
    if grants:
        ids = ",".join(str(g["id"]) for g in grants)
        await db.update("grants", f"?id=in.({ids})", {"consumed": True})
    
    name = request.query.get("name")
    # Не перезаписываем имя если оно пустое
if name and name.strip() and name.upper() != "EMPTY":
    await touch_player(uid, first_name=name)
else:
    await touch_player(uid)  # просто обновляем last_seen
    
    stats_raw = request.query.get("stats")
    if stats_raw:
        try:
            await merge_player_stats(uid, json.loads(stats_raw))
        except Exception:
            pass
    
    return json_resp({"banned": False, "grants": grants})

# ---- проверка промокода ----
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
        inventory = stats.get("inventory", {})
        return json_resp({"inventory": inventory})

    if path == "/admin/player_details":
        uid = int(data.get("user_id", 0))
        if not uid:
            return json_resp({"error": "no user_id"})
        players = await db.select("players", f"?user_id=eq.{uid}")
        if not players:
            return json_resp({"error": "player not found"})
        grants = await db.select("grants", f"?user_id=eq.{uid}&order=created_at.desc&limit=10")
        bans = await db.select("bans", f"?user_id=eq.{uid}")
        return json_resp({
            "player": players[0],
            "grants": grants,
            "banned": len(bans) > 0
        })

    if path == "/admin/stats":
        players_count = await db.count("players")
        promos_count = await db.count("promos")
        grants_count = await db.count("grants")
        payments = await db.select("payments", "?select=stars")
        total_stars = sum(p.get("stars", 0) for p in payments) if payments else 0
        return json_resp({
            "players": players_count,
            "stars": total_stars,
            "grants": grants_count,
            "promos": promos_count
        })

    if path == "/admin/grant":
        uid = int(data["user_id"])
        gtype = data.get("type", "coins")
        amount = int(data.get("amount", 0))
        item_id = data.get("item_id")
        reason = data.get("reason") or None
        
        await db.insert("grants", [{
            "user_id": uid,
            "type": gtype,
            "amount": amount,
            "item_id": item_id,
            "reason": reason
        }])
        return json_resp({"ok": True})

    if path == "/admin/annihilate":
        uid = int(data.get("user_id", 0))
        gtype = data.get("type", "coins")
        if not uid:
            return json_resp({"error": "no user_id"})
        
        if gtype == "coins":
            await db.insert("grants", [{
                "user_id": uid,
                "type": "clear_coins",
                "amount": 0,
                "reason": "Аннуляция администратором"
            }])
        else:
            await db.insert("grants", [{
                "user_id": uid,
                "type": "clear_items",
                "amount": 0,
                "reason": "Аннуляция администратором"
            }])
        return json_resp({"ok": True})

    if path == "/admin/reset":
        uid = int(data.get("user_id", 0))
        if not uid:
            return json_resp({"error": "no user_id"})
        
        await db.update("players", f"?user_id=eq.{uid}", {
            "stats": {"casesOpened": 0, "coinsSpent": 0, "balance": 2000, "inventory": {}}
        })
        
        await db.insert("grants", [{
            "user_id": uid,
            "type": "reset",
            "amount": 0,
            "reason": "Сброс прогресса администратором"
        }])
        return json_resp({"ok": True})

    if path == "/admin/grant_all":
        players = await db.select("players", "?select=user_id")
        rows = [{
            "user_id": p["user_id"],
            "type": "coins",
            "amount": int(data.get("amount", 0)),
            "reason": data.get("reason") or None
        } for p in players]
        if rows:
            await db.insert("grants", rows)
        return json_resp({"ok": True, "count": len(rows)})

    if path == "/admin/ban":
        await db.upsert("bans", [{
            "user_id": int(data["user_id"]),
            "reason": data.get("reason") or None
        }])
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
        stars = 0
        if rows:
            try:
                stars = int(rows[0].get("value"))
            except Exception:
                stars = 0
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
                    "id": g.id,
                    "star_count": g.star_count,
                    "remaining_count": g.remaining_count if g.remaining_count is not None else -1,
                    "total_count": g.total_count if g.total_count is not None else -1,
                    "image": image_url
                })
            return json_resp({"gifts": items})
        except Exception as e:
            return json_resp({"gifts": [], "error": str(e)})

    if path == "/admin/send_gift":
        user_id = int(data.get("user_id", 0))
        gift_id = data.get("gift_id")
        if not user_id or not gift_id:
            return json_resp({"ok": False, "error": "bad request"})
        
        rows = await db.select("meta", "?key=eq.bot_stars")
        cur = 0
        if rows:
            try:
                cur = int(rows[0].get("value"))
            except Exception:
                pass
        
        try:
            gifts = await bot.get_available_gifts()
            price = next((g.star_count for g in gifts.gifts if g.id == gift_id), None)
        except Exception:
            price = None
        
        if price is None:
            return json_resp({"ok": False, "error": "подарок не найден"})
        if cur < price:
            return json_resp({"ok": False, "error": f"На балансе бота {cur} ⭐, нужно {price}"})
        
        try:
            await bot.send_gift(user_id, gift_id)
        except Exception as e:
            return json_resp({"ok": False, "error": str(e)})
        
        await db.upsert("meta", [{"key": "bot_stars", "value": cur - price}])
        return json_resp({"ok": True, "new_balance": cur - price})

    return json_resp({"error": "unknown path"}, 404)

# ---- тестовый эндпоинт ----
async def handle_dbtest(request):
    sel = await db.select("players", "?limit=1")
    up = await db.upsert("meta", [{"key": "dbtest", "value": {"t": now_iso()}}])
    back = await db.select("meta", "?key=eq.dbtest")
    return json_resp({
        "url_set": bool(SUPABASE_URL),
        "key_set": bool(SUPABASE_KEY),
        "select_players": sel,
        "upsert_meta": up,
        "read_back": back
    })

async def start_web_server():
    app = web.Application(middlewares=[cors_middleware])
    
    app.router.add_get("/create_invoice", handle_create_invoice)
    app.router.add_get("/dbtest", handle_dbtest)
    app.router.add_route("*", "/sync", handle_sync)
    app.router.add_route("*", "/promo", handle_promo)
    
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

# ================= ЗАПУСК =================
async def main():
    print("🚀 Запуск...")
    asyncio.create_task(start_web_server())
    print(" Бот запущен и ожидает команды!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
