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

# ПАКИ: прогрессивная выгода
PACKS = {1: 150, 5: 1000, 10: 2500, 25: 7500, 50: 20000}

# VIP
VIP_PRICE_STARS = 100
VIP_DAYS = 30

# РУЛЕТКА
ROULETTE_POSITIONS = [
    {"id": "x2", "weight": 20},
    {"id": "x05", "weight": 25},
    {"id": "lose", "weight": 32},
    {"id": "immortal", "weight": 3},
    {"id": "guardian", "weight": 20},
    {"id": "bear", "weight": 0},
]
ROULETTE_PRICES = [1000, 1500, 2250, 3400, 5000]
ROULETTE_DAILY_LIMIT = 5
ROULETTE_STARS_PRICE = 15
ROULETTE_STAR_STAKE = 5000
TEASER_CHANCE = 0.30

# PVP
PVP_COMMISSION = 0.05
PVP_ROUND_OPTS = (1, 3, 5)
PVP_WAIT_TIMEOUT_MIN = 5
PVP_STALE_TIMEOUT_MIN = 10

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

ALLOWED_PUSH_FIELDS = {"casesOpened", "coinsSpent", "balance", "inventory", "name", "achievements"}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

# ================= КАТАЛОГ ПРЕДМЕТОВ (СЕРВЕР) =================
SERVER_ITEMS = [
    ("royale_with_cheese", 2), ("tango_single", 30), ("blood_grenade", 50), ("courier", 50), ("smoke_of_deceit", 50), ("ward_dispenser", 50),
    ("ward_sentry", 50), ("branches", 55), ("clarity", 60), ("enchanted_mango", 65), ("faerie_fire", 65), ("tome_of_knowledge", 75),
    ("dust", 80), ("tango", 90), ("flask", 100), ("flying_courier", 100), ("quelling_blade", 100), ("stout_shield", 100),
    ("tpscroll", 100), ("gauntlets", 140), ("mantle", 140), ("slippers", 140), ("circlet", 155), ("ring_of_protection", 175),
    ("ring_of_regen", 175), ("sobi_mask", 175), ("magic_stick", 200), ("infused_raindrop", 225), ("wind_lace", 225), ("fluffy_hat", 250),
    ("wizard_hat", 250), ("blight_stone", 300), ("orb_of_frost", 300), ("orb_of_venom", 350), ("buckler", 425), ("headdress", 425),
    ("ring_of_basilius", 425), ("belt_of_strength", 450), ("blades_of_attack", 450), ("boots_of_elves", 450), ("crown", 450), ("gloves", 450),
    ("robe", 450), ("shawl", 450), ("magic_wand", 460), ("boots", 500), ("chainmail", 500), ("bracer", 505), ("null_talisman", 505),
    ("wraith_band", 505), ("voodoo_mask", 650), ("bottle", 675), ("ring_of_health", 700), ("void_stone", 700), ("energy_booster", 800),
    ("soul_ring", 805), ("urn_of_shadows", 825), ("quarterstaff", 875), ("chasm_stone", 900), ("cloak", 900), ("gem", 900), ("javelin", 900),
    ("lifesteal", 900), ("shadow_amulet", 900), ("tranquil_boots", 900), ("splintmail", 950), ("helm_of_iron_will", 975),
    ("blade_of_alacrity", 1000), ("blitz_knuckles", 1000), ("broadsword", 1000), ("cheese", 1000), ("diadem", 1000), ("ogre_axe", 1000),
    ("pocket_roshan", 1000), ("refresher_shard", 1000), ("staff_of_wizardry", 1000), ("vitality_booster", 1000), ("orb_of_corrosion", 1050),
    ("falcon_blade", 1125), ("cornucopia", 1200), ("point_booster", 1200), ("talisman_of_evasion", 1300), ("claymore", 1350), ("pavise", 1350),
    ("aghanims_shard", 1400), ("pers", 1400), ("platemail", 1400), ("power_treads", 1400), ("phase_boots", 1450), ("arcane_boots", 1500),
    ("ghost", 1500), ("mithril_hammer", 1600), ("drum", 1625), ("oblivion_staff", 1625), ("ring_of_tarrasque", 1700), ("tiara_of_selemene", 1700),
    ("vanguard", 1700), ("veil_of_discord", 1700), ("essence_distiller", 1775), ("mekansm", 1775), ("dragon_lance", 1900), ("mask_of_madness", 1900),
    ("hyperstone", 2000), ("crystalys", 2000), ("necronomicon", 2050), ("kaya", 2100), ("sange", 2100), ("yasha", 2100), ("glimmer_cape", 2150),
    ("demon_edge", 2200), ("force_staff", 2200), ("hand_of_midas", 2200), ("vladmir", 2200), ("blink", 2250), ("holy_locket", 2250),
    ("rod_of_atos", 2250), ("aether_lens", 2275), ("blade_mail", 2400), ("armlet", 2500), ("diffusal_blade", 2500), ("travel_boots", 2500),
    ("helm_of_the_dominator", 2550), ("specialists_array", 2550), ("solar_crest", 2575), ("consecrated_wraps", 2600), ("cyclone", 2600),
    ("phylactery", 2600), ("echo_sabre", 2700), ("spirit_vessel", 2725), ("witch_blade", 2775), ("eagle", 2800), ("mystic_staff", 2800),
    ("reaver", 2800), ("ultimate_orb", 2800), ("meteor_hammer", 2850), ("basher", 2875), ("maelstrom", 2950), ("aeon_disk", 3000),
    ("dagon", 3000), ("soul_booster", 3000), ("mage_slayer", 3100), ("invis_sword", 3250), ("orchid", 3275), ("necronomicon_2", 3300),
    ("revenants_brooch", 3300), ("heavens_halberd", 3400), ("relic", 3400), ("desolator", 3500), ("crimson_guard", 3725), ("pipe", 3725),
    ("wraith_pact", 3800), ("lotus_orb", 3850), ("bfury", 3900), ("eternal_shroud", 3900), ("moon_shard", 4000), ("black_king_bar", 4050),
    ("dagon_2", 4100), ("kaya_and_sange", 4200), ("sange_and_yasha", 4200), ("ultimate_scepter", 4200), ("yasha_and_kaya", 4200),
    ("boots_of_bearing", 4225), ("nullifier", 4350), ("guardian_greaves", 4450), ("hurricane_pike", 4450), ("shivas", 4500),
    ("travel_boots_2", 4500), ("necronomicon_3", 4550), ("gungir", 4650), ("manta", 4650), ("bloodstone", 4700), ("harpoon", 4700),
    ("radiance", 4700), ("crellas_crozier", 4800), ("sphere", 4800), ("octarine_core", 4900), ("monkey_king_bar", 5000), ("refresher", 5000),
    ("satanic", 5050), ("daedalus", 5100), ("assault", 5125), ("dagon_3", 5200), ("ethereal_blade", 5200), ("heart", 5200),
    ("scythe_of_vyse", 5200), ("butterfly", 5450), ("mjollnir", 5500), ("angels_demise", 5600), ("casters_rapier", 5600), ("rapier", 5600),
    ("helm_of_the_overlord", 5650), ("silver_edge", 5700), ("ultimate_scepter_2", 5800), ("hydras_breath", 5900), ("skadi", 5900),
    ("devastator", 5975), ("disperser", 6100), ("abyssal_blade", 6250), ("dagon_4", 6300), ("trident", 6301), ("bloodthorn", 6400),
    ("arcane_blink", 6800), ("overwhelming_blink", 6800), ("swift_blink", 6800), ("wind_waker", 6800), ("dagon_5", 7400),
]
CHEST_DEFS = {
    "recruit": (0, 1000, 0.97, 500),
    "guardian": (1000, 2500, 0.95, 1700),
    "knight": (2500, 4500, 0.94, 3600),
    "immortal": (4500, 10 ** 9, 0.93, 5000),
}

def chest_pool(case_id):
    mn, mx, decay, price = CHEST_DEFS[case_id]
    return sorted([(i, c) for i, c in SERVER_ITEMS if mn < c <= mx], key=lambda x: x[1])

def weighted_pick(pool, decay):
    w = [decay ** i for i in range(len(pool))]
    r = random.uniform(0, sum(w))
    for i, wi in enumerate(w):
        r -= wi
        if r <= 0:
            return pool[i]
    return pool[-1]

# ================= ПОДАРКИ =================
GIFT_CATALOG = {
    "gift_heart": {"id": "5170145012310081615", "price": 15, "name": "💝 Сердечко"},
    "gift_teddy": {"id": "5170233102089322756", "price": 15, "name": "🧸 Мишка"},
    "gift_box": {"id": "5170250947678437525", "price": 25, "name": "🎁 Подарок"},
    "gift_rose": {"id": "5168103777563050263", "price": 25, "name": "🌹 Роза"},
    "gift_cake": {"id": "5170144170496491616", "price": 50, "name": "🎂 Торт"},
    "gift_bouquet": {"id": "5170314324215857265", "price": 50, "name": "💐 Букет"},
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
            "Prefer": "return=representation",
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

def db_write_error(res):
    if res is None:
        return "пустой ответ Supabase"
    if isinstance(res, list):
        return None
    if isinstance(res, dict):
        return res.get("message") or res.get("error") or res.get("hint") or str(res)
    return str(res)

# ================= БАЛАНС: СЕРВЕР = ИСТОЧНИК ПРАВДЫ =================
async def get_stats(uid):
    rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
    if not rows:
        return None
    return rows[0].get("stats") or {}

async def get_balance(uid):
    st = await get_stats(uid)
    if st is None:
        return 0
    return int(st.get("balance", 0) or 0)

async def add_balance(uid, delta):
    rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
    if not rows:
        return None, "игрок не найден"
    cur = rows[0].get("stats") or {}
    new = max(0, int(cur.get("balance", 0) or 0) + delta)
    cur["balance"] = new
    res = await db.update("players", f"?user_id=eq.{uid}", {"stats": cur})
    err = db_write_error(res)
    if err:
        return None, err
    return new, None

async def get_display_identity(uid):
    """Имя/аватар для PVP: профиль игры → имя из Telegram → заглушка."""
    rows = await db.select("players", f"?user_id=eq.{uid}&select=first_name,stats")
    if not rows:
        return "Игрок", ""
    r = rows[0]
    st = r.get("stats") or {}
    name = st.get("name") or r.get("first_name") or "Игрок"
    avatar = st.get("avatar") or ""
    return name, avatar

async def merge_player_stats(uid, patch):
    rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
    cur = (rows[0].get("stats") if rows else None) or {}
    cur.update(patch)
    res = await db.update("players", f"?user_id=eq.{uid}", {"stats": cur})
    return db_write_error(res)

async def apply_balance_delta(uid, data):
    """Дельта-слияние баланса: клиент шлёт balance + balance_base, сервер применяет разницу поверх правды."""
    bal = data.get("balance")
    base = data.get("balance_base")
    if isinstance(bal, int) and isinstance(base, int):
        delta = bal - base
        if delta != 0:
            _, err = await add_balance(uid, delta)
            if err:
                print(f"🚨 BALANCE DELTA ERROR uid={uid}: {err}")

def vip_info_from_until(until):
    if not until:
        return False, 0
    try:
        dt = datetime.fromisoformat(until)
    except Exception:
        return False, 0
    now = datetime.now(timezone.utc)
    if dt <= now:
        return False, 0
    delta = dt - now
    return True, delta.days + (1 if delta.seconds else 0)

async def touch_player(user_id, username=None, first_name=None):
    row = {"user_id": user_id, "last_seen": now_iso()}
    if username and username.strip():
        row["username"] = username
    if first_name and first_name.strip() and first_name.upper() != "EMPTY":
        row["first_name"] = first_name
    await db.upsert("players", [row])

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

# ================= КРЕДИТЫ РУЛЕТКИ =================
async def get_roulette_credits(uid):
    rows = await db.select("meta", "?key=eq.roulette_credits")
    if not rows:
        return 0
    try:
        return int(json.loads(rows[0].get("value") or "{}").get(str(uid), 0))
    except Exception:
        return 0

async def add_roulette_credits(uid, delta):
    rows = await db.select("meta", "?key=eq.roulette_credits")
    data = {}
    if rows:
        try:
            data = json.loads(rows[0].get("value") or "{}")
        except Exception:
            data = {}
    data[str(uid)] = max(0, int(data.get(str(uid), 0)) + delta)
    await db.upsert("meta", [{"key": "roulette_credits", "value": json.dumps(data)}])
    return data[str(uid)]

# ================= ТРОЛЛИНГ / СОБЫТИЯ =================
async def get_active_events():
    now = now_iso()
    rows = await db.select("scheduled_events", f"?active=eq.true&starts_at=lte.{now}&ends_at=gte.{now}")
    return [r["event_type"] for r in rows]

async def get_fake_add(uid):
    now = now_iso()
    rows = await db.select("fake_transactions", f"?user_id=eq.{uid}&reverted=eq.false&revert_at=gt.{now}")
    return sum(r.get("amount", 0) for r in rows)

async def get_troll_extras(uid):
    rows = await db.select("troll_settings", f"?user_id=eq.{uid}")
    if not rows:
        return {}
    t = rows[0]
    return {
        "fake_name": t.get("fake_name"),
        "fake_avatar": t.get("fake_avatar"),
        "frozen": bool(t.get("frozen")),
        "price_overrides": t.get("price_overrides") or {},
        "art_overrides": t.get("art_overrides") or {},
        "fake_achievements": t.get("fake_achievements") or [],
    }

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
            "details": details or {},
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
    [InlineKeyboardButton(text="✅ Я подписался, проверить", callback_data="check_sub")],
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

@dp.message(Command("allitem"))
async def cmd_allitem(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Эта команда доступна только владельцу бота.")
        return
    parts = (message.text or "").split()
    target = message.from_user.id
    if len(parts) > 1 and parts[1].strip().isdigit():
        target = int(parts[1].strip())
    await db.insert("grants", [{
        "user_id": target,
        "type": "all_items",
        "amount": 0,
        "reason": "Команда /allitem",
    }])
    await log_player_action(target, "admin_all_items", {"by": OWNER_ID})
    if target == message.from_user.id:
        await message.answer("✅ Грант создан! Зайди в игру (или подожди пару секунд, если уже там) — все предметы упадут в инвентарь.")
    else:
        await message.answer(f"✅ Грант «все предметы» создан для {target}. Предметы придут при следующем синке игрока.")

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

# ================= INLINE =================
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
            input_message_content=InputTextMessageContent(message_text="💎 Спонсорство Dota Drop: напиши @бот и число звёзд"),
        )
        await iq.answer([hint], cache_time=0, is_personal=True)
        return
    n = int(q)
    if n < 1 or n > INLINE_MAX_STARS:
        hint = InlineQueryResultArticle(
            id="hint_range",
            title=f"Число от 1 до {INLINE_MAX_STARS}",
            description="Столько звёзд сможет внести спонсор",
            input_message_content=InputTextMessageContent(message_text="💎 Введи число звёзд от 1 до 10000"),
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

# ================= ПОДАРОК (FSM) =================
@dp.callback_query(F.data == "admin_gift")
async def cb_admin_gift(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("⛔ Доступ запрещён", show_alert=True)
        return
    await cb.message.edit_text("🎁 <b>Отправка подарка</b>\n\nВведите <b>ID пользователя</b> (число):", parse_mode="HTML")
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
    await cb.message.answer("👥 Отправлю ВСЕМ игрокам.\n\nТеперь пришли сообщение для рассылки (текст, фото, файл, видео, стикер) — скопирую как есть.")
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
    await message.answer(f"👤 Получатель: <code>{uid}</code>\n\nТеперь пришли сообщение для отправки (текст, фото, файл, видео, стикер) — скопирую как есть.", parse_mode="HTML")
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
            msg = await bot.send_photo(OWNER_ID, image_url, caption=text, parse_mode="HTML")
        else:
            msg = await bot.send_message(OWNER_ID, text, parse_mode="HTML")
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
                    await bot.edit_message_caption("😔 Раскупили без нас — остаток 0.", chat_id=chat_id, message_id=msg_id)
                except Exception:
                    try:
                        await bot.edit_message_text("😔 Раскупили без нас — остаток 0.", chat_id=chat_id, message_id=msg_id)
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
        await status.edit_text(f"🎯 Сканирование завершено\n🔥 Новых лимиток: {new_found}\n📦 Лимиток в каталоге: {total}")
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

    if payload.startswith("roulette_cred_"):
        await add_roulette_credits(user_id, 1)
        await message.answer(f"✅ Оплачено! Получен 1 кредит рулетки ({ROULETTE_STARS_PRICE}⭐). Крути сверх лимита!")
        return

    if payload.startswith("vip_"):
        if stars != VIP_PRICE_STARS:
            await message.answer("⚠️ Ошибка оплаты VIP.")
            return
        now = datetime.now(timezone.utc)
        base = now
        st = await get_stats(user_id) or {}
        old = st.get("vip_until")
        if old:
            try:
                old_dt = datetime.fromisoformat(old)
                if old_dt > now:
                    base = old_dt
            except Exception:
                pass
        new_until = base + timedelta(days=VIP_DAYS)
        err = await merge_player_stats(user_id, {"vip_until": new_until.isoformat()})
        if err:
            print(f"🚨 VIP WRITE ERROR uid={user_id}: {err}")
        await db.insert("payments", [{"user_id": user_id, "stars": stars, "coins": 0}])
        await db.insert("grants", [{
            "user_id": user_id, "type": "item", "item_id": "gift_case",
            "amount": 1, "reason": "Покупка VIP",
        }])
        await log_player_action(user_id, "vip_purchase", {"stars": stars, "until": new_until.isoformat()})
        await message.answer("💎 VIP активирован на 30 дней! x2 продажа, Иммортал раз в день, подарочный кейс уже в инвентаре.")
        return

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
                "amount": 1, "reason": "Покупка подарочного кейса",
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
        coins = PACKS.get(stars, stars * 150)
        await db.insert("payments", [{"user_id": user_id, "stars": stars, "coins": coins}])
        new_bal, err = await add_balance(user_id, coins)
        if err:
            print(f"🚨 TOPUP BALANCE ERROR: {err}")
        await db.insert("grants", [{
            "user_id": user_id, "type": "coins", "amount": coins,
            "reason": "Покупка осколков", "pre_applied": True,
        }])
        await message.answer(f"✅ Оплата {stars} ⭐ подтверждена! +{coins} осколков уже на балансе.")
        return

# ================= ВЕБ-СЕРВЕР =================
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
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
        if request.query.get("vip") == "1":
            link = await bot.create_invoice_link(
                title="Dota Drop VIP",
                description="VIP на 30 дней: x2 продажа, Иммортал раз в день, подарочный кейс",
                payload=f"vip_{uid}",
                currency="XTR",
                prices=[LabeledPrice(label="VIP 30 дней", amount=VIP_PRICE_STARS)])
            return json_resp({"invoice_link": link})
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
            if stars not in PACKS:
                return json_resp({"error": "bad pack"}, 400)
            coins = PACKS[stars]
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
            "ban_price": banned[0].get("ban_price", 0),
        })
    grants = await db.select("grants", f"?user_id=eq.{uid}&consumed=eq.false&order=created_at.asc")
    if grants:
        ids = ",".join(str(g["id"]) for g in grants)
        await db.update("grants", f"?id=in.({ids})", {"consumed": True})
    name = request.query.get("name")
    if name and name.strip() and name.upper() != "EMPTY":
        await touch_player(uid, first_name=name)
        await merge_player_stats(uid, {"name": name})
    else:
        await touch_player(uid)
    stats_raw = request.query.get("stats")
    if stats_raw:
        try:
            data = json.loads(stats_raw)
            filtered = {k: v for k, v in data.items() if k in ALLOWED_PUSH_FIELDS}
            filtered.pop("balance", None)
            await apply_balance_delta(uid, data)
            await merge_player_stats(uid, filtered)
        except Exception:
            pass
    response = {"banned": False, "grants": grants}
    extras = await get_troll_extras(uid)
    if extras.get("fake_name"): response["fake_name"] = extras["fake_name"]
    if extras.get("fake_avatar"): response["fake_avatar"] = extras["fake_avatar"]
    if extras.get("frozen"): response["frozen"] = True
    if extras.get("price_overrides"): response["price_overrides"] = extras["price_overrides"]
    if extras.get("art_overrides"): response["art_overrides"] = extras["art_overrides"]
    if extras.get("fake_achievements"): response["fake_achievements"] = extras["fake_achievements"]
    fa = await get_fake_add(uid)
    if fa: response["fake_add"] = fa
    ev = await get_active_events()
    if ev: response["events"] = ev
    response["server_balance"] = await get_balance(uid)
    st = await get_stats(uid)
    v_on, v_days = vip_info_from_until((st or {}).get("vip_until"))
    response["vip"] = v_on
    response["vip_days"] = v_days
    return json_resp(response)

async def handle_game_profile(request):
    uid = int(request.query.get("user_id", 0))
    if not uid:
        return json_resp({"error": "no user_id"}, 400)
    rows = await db.select("players", f"?user_id=eq.{uid}")
    if not rows:
        return json_resp({"balance": 2000, "name": "", "avatar": "", "achievements": [],
                          "fake_achievements": [], "price_overrides": {}, "art_overrides": {},
                          "fake_add": 0, "events": [], "frozen": False, "vip": False, "vip_days": 0})
    stats = rows[0].get("stats") or {}
    extras = await get_troll_extras(uid)
    name = stats.get("name", "")
    avatar = stats.get("avatar", "")
    if extras.get("fake_name"):
        name = extras["fake_name"]
    if extras.get("fake_avatar"):
        avatar = extras["fake_avatar"]
    v_on, v_days = vip_info_from_until(stats.get("vip_until"))
    return json_resp({
        "balance": stats.get("balance", 2000),
        "name": name,
        "avatar": avatar,
        "achievements": stats.get("achievements", []),
        "fake_achievements": extras.get("fake_achievements", []),
        "price_overrides": extras.get("price_overrides", {}),
        "art_overrides": extras.get("art_overrides", {}),
        "fake_add": await get_fake_add(uid),
        "events": await get_active_events(),
        "frozen": extras.get("frozen", False),
        "vip": v_on,
        "vip_days": v_days,
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

async def handle_game_case_drop(request):
    try:
        d = await request.json()
    except Exception:
        d = {}
    init = d.get("initData") or ""
    user = validate_init_data(init)
    if not user:
        return json_resp({"override": None})
    uid = int(user["id"])
    chest = d.get("chest_id", "")
    if not chest:
        return json_resp({"override": None})
    rows = await db.select("drop_overrides", f"?user_id=eq.{uid}&chest_id=eq.{chest}&active=eq.true")
    if not rows:
        return json_resp({"override": None})
    overrides = rows[0].get("overrides") or []
    if not overrides:
        return json_resp({"override": None})
    total = sum(o.get("chance", 0) for o in overrides)
    if total <= 0:
        return json_resp({"override": None})
    r = random.uniform(0, total)
    acc = 0
    pick = None
    for o in overrides:
        acc += o.get("chance", 0)
        if r <= acc:
            pick = o.get("item_id")
            break
    return json_resp({"override": pick})

async def handle_game_top100(request):
    rows = await db.select("players", "?select=user_id,first_name,username,balance:stats->>balance,avatar:stats->>avatar,vip_until:stats->>vip_until&limit=5000")
    for r in rows:
        try:
            r["balance"] = int(r.get("balance") or 0)
        except Exception:
            r["balance"] = 0
    rows.sort(key=lambda r: r["balance"], reverse=True)
    rows = rows[:100]
    uids = [r["user_id"] for r in rows]
    troll_map = {}
    if uids:
        uids_str = ",".join(str(u) for u in uids)
        trolls = await db.select("troll_settings", f"?user_id=in.({uids_str})")
        troll_map = {t["user_id"]: t for t in trolls}
    out = []
    for i, r in enumerate(rows):
        t = troll_map.get(r["user_id"]) or {}
        out.append({
            "place": i + 1,
            "user_id": r["user_id"],
            "name": t.get("fake_name") or r.get("first_name") or "Игрок",
            "avatar": t.get("fake_avatar") or r.get("avatar") or "",
            "balance": r["balance"],
            "vip": vip_info_from_until(r.get("vip_until"))[0],
        })
    return json_resp({"top": out})

async def handle_push_stats(request):
    uid = int(request.query.get("user_id", 0))
    if not uid:
        return json_resp({"ok": False})
    raw = request.query.get("stats")
    if raw:
        try:
            data = json.loads(raw)
            filtered = {k: v for k, v in data.items() if k in ALLOWED_PUSH_FIELDS}
            filtered.pop("balance", None)
            await apply_balance_delta(uid, data)
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

# ================= РУЛЕТКА =================
def roulette_roll_position():
    weights = [p["weight"] for p in ROULETTE_POSITIONS]
    return random.choices(ROULETTE_POSITIONS, weights=weights, k=1)[0]

async def roulette_apply_prize(uid, pos_id, stake):
    res = {"position": pos_id, "teaser": False}
    if pos_id == "x2":
        amount = stake * 2
        new_bal, err = await add_balance(uid, amount)
        if err:
            return None, err
        res.update({"amount": amount, "new_balance": new_bal})
    elif pos_id == "x05":
        amount = stake // 2
        new_bal, err = await add_balance(uid, amount)
        if err:
            return None, err
        res.update({"amount": amount, "new_balance": new_bal})
    elif pos_id == "lose":
        res["teaser"] = random.random() < TEASER_CHANCE
        res.update({"amount": 0, "new_balance": await get_balance(uid)})
    elif pos_id in ("immortal", "guardian"):
        pool = chest_pool(pos_id)
        decay = CHEST_DEFS[pos_id][2]
        item_id, item_cost = weighted_pick(pool, decay)
        st = await get_stats(uid)
        inv = dict((st or {}).get("inventory", {}))
        inv[item_id] = inv.get(item_id, 0) + 1
        err = await merge_player_stats(uid, {"inventory": inv})
        if err:
            return None, err
        res.update({"item_id": item_id, "item_cost": item_cost, "new_balance": await get_balance(uid)})
    else:
        return None, "invalid position"
    return res, None

async def handle_roulette(request):
    path = request.path
    try:
        d = await request.json()
    except Exception:
        d = {}
    init = d.get("initData") or ""
    user = validate_init_data(init)
    if not user:
        return json_resp({"error": "forbidden"}, 403)
    uid = int(user["id"])
    today = now_iso()[:10]

    if path == "/roulette/status":
        spins = await db.select("roulette_spins", f"?user_id=eq.{uid}&spin_date=eq.{today}&paid_stars=eq.false")
        n = len(spins)
        return json_resp({
            "spins_today": n,
            "daily_limit": ROULETTE_DAILY_LIMIT,
            "next_price": ROULETTE_PRICES[n] if n < ROULETTE_DAILY_LIMIT else None,
            "stars_price": ROULETTE_STARS_PRICE,
            "star_credits": await get_roulette_credits(uid),
            "prices": ROULETTE_PRICES,
            "balance": await get_balance(uid),
        })

    if path == "/roulette/buy_credits":
        try:
            link = await bot.create_invoice_link(
                title="Кредит рулетки Dota Drop",
                description=f"1 крут рулетки сверх лимита за {ROULETTE_STARS_PRICE} Stars",
                payload=f"roulette_cred_{uid}",
                currency="XTR",
                prices=[LabeledPrice(label="Кредит рулетки", amount=ROULETTE_STARS_PRICE)])
            return json_resp({"invoice_link": link})
        except Exception as e:
            return json_resp({"error": str(e)}, 500)

    if path == "/roulette/spin":
        spins = await db.select("roulette_spins", f"?user_id=eq.{uid}&spin_date=eq.{today}&paid_stars=eq.false")
        n = len(spins)
        if n >= ROULETTE_DAILY_LIMIT:
            return json_resp({"error": "limit", "stars_price": ROULETTE_STARS_PRICE}, 402)
        price = ROULETTE_PRICES[n]
        bal = await get_balance(uid)
        if bal < price:
            return json_resp({"error": f"Не хватает осколков: нужно {price}"}, 400)
        new_bal, err = await add_balance(uid, -price)
        if err:
            return json_resp({"error": err}, 500)
        pos = roulette_roll_position()
        prize, err = await roulette_apply_prize(uid, pos["id"], price)
        if err:
            await add_balance(uid, price)
            return json_resp({"error": err}, 500)
        await db.insert("roulette_spins", [{
            "user_id": uid, "spin_date": today, "spin_number": n + 1,
            "position_id": pos["id"], "item_id": prize.get("item_id"),
            "amount": prize.get("amount"), "paid_stars": False, "teaser": prize.get("teaser", False),
        }])
        await log_player_action(uid, "roulette_spin", {"pos": pos["id"], "price": price})
        return json_resp({"ok": True, "paid_stars": False, "price": price, "spins_today": n + 1, **prize})

    if path == "/roulette/spin_stars":
        credits = await get_roulette_credits(uid)
        if credits < 1:
            return json_resp({"error": "no_credits", "stars_price": ROULETTE_STARS_PRICE}, 402)
        await add_roulette_credits(uid, -1)
        stake = ROULETTE_STAR_STAKE
        pos = roulette_roll_position()
        prize, err = await roulette_apply_prize(uid, pos["id"], stake)
        if err:
            await add_roulette_credits(uid, 1)
            return json_resp({"error": err}, 500)
        await db.insert("roulette_spins", [{
            "user_id": uid, "spin_date": today, "spin_number": 0,
            "position_id": pos["id"], "item_id": prize.get("item_id"),
            "amount": prize.get("amount"), "paid_stars": True, "teaser": prize.get("teaser", False),
        }])
        await log_player_action(uid, "roulette_spin_stars", {"pos": pos["id"]})
        return json_resp({"ok": True, "paid_stars": True, "price": ROULETTE_STARS_PRICE,
                          "spins_today": ROULETTE_DAILY_LIMIT, **prize})

    return json_resp({"error": "unknown path"}, 404)

# ================= PVP БАТТЛЫ =================
def gen_battle_code():
    s = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(s) for _ in range(4))

async def pvp_room_state(code):
    battles = await db.select("pvp_battles", f"?code=eq.{code}")
    if not battles:
        return None
    b = battles[0]
    players = await db.select("pvp_players", f"?battle_code=eq.{code}&order=seat.asc")
    rounds = await db.select("pvp_rounds", f"?battle_code=eq.{code}&order=round_num.asc")
    uids = [p["user_id"] for p in players]
    vip_map = {}
    if uids:
        ustr = ",".join(str(u) for u in uids)
        prow = await db.select("players", f"?user_id=in.({ustr})&select=user_id,stats")
        for pr in prow:
            vip_map[pr["user_id"]] = vip_info_from_until((pr.get("stats") or {}).get("vip_until"))[0]
    for p in players:
        p["vip"] = vip_map.get(p["user_id"], False)
    return {"battle": b, "players": players, "rounds": rounds}

async def pvp_finalize(b, players):
    stake = int(b["stake"])
    bank = stake * 2
    s0 = int(players[0].get("score", 0) or 0) if len(players) > 0 else 0
    s1 = int(players[1].get("score", 0) or 0) if len(players) > 1 else 0
    prize = int(bank * (1 - PVP_COMMISSION))
    winner_uid = None
    if s0 > s1:
        winner_uid = players[0]["user_id"]
        await add_balance(winner_uid, prize)
    elif s1 > s0:
        winner_uid = players[1]["user_id"]
        await add_balance(winner_uid, prize)
    else:
        for p in players:
            await add_balance(p["user_id"], stake)
        prize = 0
    await db.update("pvp_battles", f"?code=eq.{b['code']}",
                    {"status": "finished", "winner_uid": winner_uid, "prize": prize})
    return winner_uid, prize

async def handle_pvp(request):
    path = request.path
    try:
        d = await request.json()
    except Exception:
        d = {}
    init = d.get("initData") or ""
    user = validate_init_data(init)
    if not user:
        return json_resp({"error": "forbidden"}, 403)
    uid = int(user["id"])

    if path == "/pvp/list":
        rows = await db.select("pvp_battles", "?status=eq.waiting&order=created_at.desc&limit=20")
        out = []
        for b in rows:
            ps = await db.select("pvp_players", f"?battle_code=eq.{b['code']}&seat=eq.0")
            owner = ps[0] if ps else None
            out.append({
                "code": b["code"], "case_id": b["case_id"], "rounds": b["rounds"], "stake": b["stake"],
                "owner": {"user_id": owner["user_id"], "name": owner.get("name"), "avatar": owner.get("avatar")} if owner else None,
                "mine": bool(owner and owner["user_id"] == uid),
            })
        return json_resp({"battles": out})

    if path == "/pvp/create":
        case_id = d.get("case_id")
        rounds = int(d.get("rounds", 0))
        if case_id not in CHEST_DEFS or rounds not in PVP_ROUND_OPTS:
            return json_resp({"error": "bad params"}, 400)
        stake = CHEST_DEFS[case_id][3] * rounds
        my_seats = await db.select("pvp_players", f"?user_id=eq.{uid}&seat=eq.0")
        for ms in my_seats:
            bs = await db.select("pvp_battles", f"?code=eq.{ms['battle_code']}&status=eq.waiting")
            if bs:
                room = await pvp_room_state(ms["battle_code"])
                if room:
                    return json_resp({"ok": True, "reused": True, **room})
        bal = await get_balance(uid)
        if bal < stake:
            return json_resp({"error": f"Не хватает осколков: нужно {stake}"}, 400)
        new_bal, err = await add_balance(uid, -stake)
        if err:
            return json_resp({"error": err}, 500)
        code = gen_battle_code()
        for _ in range(5):
            exists = await db.select("pvp_battles", f"?code=eq.{code}")
            if not exists:
                break
            code = gen_battle_code()
        me_name, me_ava = await get_display_identity(uid)
        r1 = await db.insert("pvp_battles", [{
            "code": code, "case_id": case_id, "rounds": rounds, "stake": stake,
            "status": "waiting", "round_now": 0,
        }])
        err = db_write_error(r1)
        if err:
            await add_balance(uid, stake)
            return json_resp({"error": err}, 500)
        r2 = await db.insert("pvp_players", [{
            "battle_code": code, "seat": 0, "user_id": uid,
            "name": me_name, "avatar": me_ava, "score": 0,
        }])
        err = db_write_error(r2)
        if err:
            await add_balance(uid, stake)
            await db.delete("pvp_battles", f"?code=eq.{code}")
            return json_resp({"error": err}, 500)
        await log_player_action(uid, "pvp_create", {"code": code, "stake": stake})
        room = await pvp_room_state(code)
        return json_resp({"ok": True, "new_balance": new_bal, **room})

    if path == "/pvp/join":
        code = (d.get("code") or d.get("battle_id") or "").strip().upper()
        battles = await db.select("pvp_battles", f"?code=eq.{code}")
        if not battles or battles[0]["status"] != "waiting":
            return json_resp({"error": "Батл не найден или уже занят"}, 404)
        b = battles[0]
        ps = await db.select("pvp_players", f"?battle_code=eq.{code}&order=seat.asc")
        if any(p["user_id"] == uid for p in ps):
            return json_resp({"error": "Ты уже в этом батле"}, 400)
        stake = int(b["stake"])
        bal = await get_balance(uid)
        if bal < stake:
            return json_resp({"error": f"Не хватает осколков: нужно {stake}"}, 400)
        new_bal, err = await add_balance(uid, -stake)
        if err:
            return json_resp({"error": err}, 500)
        j_name, j_ava = await get_display_identity(uid)
        r = await db.insert("pvp_players", [{
            "battle_code": code, "seat": 1, "user_id": uid,
            "name": j_name, "avatar": j_ava, "score": 0,
        }])
        err = db_write_error(r)
        if err or not r:
            await add_balance(uid, stake)
            return json_resp({"error": err or "место занято"}, 500)
        await db.update("pvp_battles", f"?code=eq.{code}&status=eq.waiting",
                        {"status": "active", "updated_at": now_iso()})
        await log_player_action(uid, "pvp_join", {"code": code, "stake": stake})
        room = await pvp_room_state(code)
        return json_resp({"ok": True, "new_balance": new_bal, **room})

    if path == "/pvp/room":
        code = (d.get("code") or request.query.get("code") or "").strip().upper()
        room = await pvp_room_state(code)
        if not room:
            return json_resp({"error": "not found"}, 404)
        room["balance"] = await get_balance(uid)
        return json_resp(room)

    if path == "/pvp/roll":
        code = (d.get("code") or "").strip().upper()
        battles = await db.select("pvp_battles", f"?code=eq.{code}")
        if not battles:
            return json_resp({"error": "not found"}, 404)
        b = battles[0]
        if b["status"] != "active":
            return json_resp({"error": "battle not active"}, 400)
        ps = await db.select("pvp_players", f"?battle_code=eq.{code}&order=seat.asc")
        if not any(p["user_id"] == uid for p in ps):
            return json_resp({"error": "not a participant"}, 403)
        if len(ps) < 2 or int(b["round_now"]) >= int(b["rounds"]):
            return json_resp({"error": "no rounds left"}, 400)
        old_round = int(b["round_now"])
        guard = await db.update("pvp_battles", f"?code=eq.{code}&round_now=eq.{old_round}",
                                {"round_now": old_round + 1, "updated_at": now_iso()})
        if not guard:
            room = await pvp_room_state(code)
            return json_resp({"ok": True, "race": True, **room})
        pool = chest_pool(b["case_id"])
        decay = CHEST_DEFS[b["case_id"]][2]
        i0, c0 = weighted_pick(pool, decay)
        i1, c1 = weighted_pick(pool, decay)
        await db.insert("pvp_rounds", [{
            "battle_code": code, "round_num": old_round + 1,
            "p0_item": i0, "p1_item": i1, "p0_cost": c0, "p1_cost": c1,
        }])
        await db.update("pvp_players", f"?battle_code=eq.{code}&seat=eq.0", {"score": int(ps[0].get("score", 0)) + c0})
        await db.update("pvp_players", f"?battle_code=eq.{code}&seat=eq.1", {"score": int(ps[1].get("score", 0)) + c1})
        room = await pvp_room_state(code)
        if old_round + 1 >= int(b["rounds"]):
            winner_uid, prize = await pvp_finalize(b, room["players"])
            room["battle"]["status"] = "finished"
            room["battle"]["winner_uid"] = winner_uid
            room["battle"]["prize"] = prize
            await log_player_action(uid, "pvp_finish", {"code": code, "winner": winner_uid})
        room["balance"] = await get_balance(uid)
        return json_resp({"ok": True, **room})

    if path == "/pvp/leave":
        code = (d.get("code") or "").strip().upper()
        battles = await db.select("pvp_battles", f"?code=eq.{code}")
        if not battles:
            return json_resp({"error": "not found"}, 404)
        b = battles[0]
        ps = await db.select("pvp_players", f"?battle_code=eq.{code}&order=seat.asc")
        me = next((p for p in ps if p["user_id"] == uid), None)
        if not me:
            return json_resp({"error": "not a participant"}, 403)
        stake = int(b["stake"])
        if b["status"] == "waiting":
            await add_balance(uid, stake)
            await db.update("pvp_battles", f"?code=eq.{code}", {"status": "canceled"})
            await db.delete("pvp_players", f"?battle_code=eq.{code}")
            return json_resp({"ok": True, "refunded": stake, "new_balance": await get_balance(uid)})
        if b["status"] == "active":
            opp = next((p for p in ps if p["user_id"] != uid), None)
            prize = int(stake * 2 * (1 - PVP_COMMISSION))
            if opp:
                await add_balance(opp["user_id"], prize)
                winner = opp["user_id"]
            else:
                winner = None
                await add_balance(uid, stake)
            await db.update("pvp_battles", f"?code=eq.{code}",
                            {"status": "finished", "winner_uid": winner, "prize": prize if opp else 0})
            await log_player_action(uid, "pvp_leave_forfeit", {"code": code})
            return json_resp({"ok": True, "forfeit": True, "winner_uid": winner})
        return json_resp({"ok": True})

    return json_resp({"error": "unknown path"}, 404)

# ================= PC ADMIN =================
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
            "user_agent": request.headers.get("User-Agent"),
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
        uid = int(data.get("user_id") or request.query.get("user_id") or 0)
        if not uid:
            return json_resp({"error": "no user_id"})
        if request.method == "GET":
            rows = await db.select("troll_settings", f"?user_id=eq.{uid}")
            return json_resp({"troll": rows[0] if rows else {}})
        patch = {k: v for k, v in data.items() if k in {"fake_name", "fake_avatar", "frozen", "price_overrides", "art_overrides", "fake_achievements"}}
        if not patch:
            return json_resp({"error": "no fields"})
        existing = await db.select("troll_settings", f"?user_id=eq.{uid}")
        if existing:
            res = await db.update("troll_settings", f"?user_id=eq.{uid}", patch)
        else:
            res = await db.insert("troll_settings", [{"user_id": uid, **patch}])
        err = db_write_error(res)
        if err:
            print(f"🚨 TROLL WRITE ERROR uid={uid}: {err}")
            return json_resp({"ok": False, "error": f"База не приняла запись: {err}"}, 500)
        if isinstance(res, list) and len(res) == 0:
            return json_resp({"ok": False, "error": "База не нашла/не создала строку троллинга"}, 500)
        return json_resp({"ok": True})

    if path == "/admin_pc/drop_override":
        uid = int(data.get("user_id") or request.query.get("user_id") or 0)
        chest = data.get("chest_id") or request.query.get("chest_id")
        if not uid or not chest:
            return json_resp({"error": "bad request"})
        if request.method == "GET":
            rows = await db.select("drop_overrides", f"?user_id=eq.{uid}&chest_id=eq.{chest}")
            return json_resp({"overrides": (rows[0].get("overrides") or []) if rows else []})
        overrides = data.get("overrides", [])
        existing = await db.select("drop_overrides", f"?user_id=eq.{uid}&chest_id=eq.{chest}")
        if existing:
            res = await db.update("drop_overrides", f"?user_id=eq.{uid}&chest_id=eq.{chest}", {"overrides": overrides})
        else:
            res = await db.insert("drop_overrides", [{"user_id": uid, "chest_id": chest, "overrides": overrides}])
        err = db_write_error(res)
        if err:
            return json_resp({"ok": False, "error": f"База не приняла запись: {err}"}, 500)
        return json_resp({"ok": True})

    if path == "/admin_pc/event":
        etype = data.get("event_type")
        starts = data.get("starts_at")
        ends = data.get("ends_at")
        if not etype or not starts or not ends:
            return json_resp({"error": "bad request"})
        res = await db.insert("scheduled_events", [{"event_type": etype, "starts_at": starts, "ends_at": ends}])
        err = db_write_error(res)
        if err:
            return json_resp({"ok": False, "error": f"База не приняла запись: {err}"}, 500)
        return json_resp({"ok": True})

    if path == "/admin_pc/note":
        uid = int(data.get("user_id", 0))
        note = data.get("note", "")
        if not uid or not note:
            return json_resp({"error": "bad request"})
        res = await db.insert("admin_notes", [{"user_id": uid, "note": note, "created_by": OWNER_ID}])
        err = db_write_error(res)
        if err:
            return json_resp({"ok": False, "error": f"База не приняла запись: {err}"}, 500)
        return json_resp({"ok": True})

    if path == "/admin_pc/logs":
        uid = request.query.get("user_id")
        q = "?order=created_at.desc&limit=50"
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
        res = await db.insert("fake_transactions", [{
            "user_id": uid, "amount": amount, "type": "fake_grant", "revert_at": revert_at,
        }])
        err = db_write_error(res)
        if err:
            return json_resp({"ok": False, "error": f"База не приняла запись: {err}"}, 500)
        return json_resp({"ok": True, "revert_at": revert_at})

    if path == "/admin_pc/set_balance":
        uid = int(data.get("user_id", 0))
        bal = int(data.get("balance", 0))
        if not uid:
            return json_resp({"error": "bad request"})
        rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
        cur = (rows[0].get("stats") if rows else None) or {}
        cur["balance"] = bal
        res = await db.update("players", f"?user_id=eq.{uid}", {"stats": cur})
        err = db_write_error(res)
        if err:
            return json_resp({"ok": False, "error": f"База не приняла запись: {err}"}, 500)
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
        res = await db.update("players", f"?user_id=eq.{uid}", {"stats": cur})
        err = db_write_error(res)
        if err:
            return json_resp({"ok": False, "error": f"База не приняла запись: {err}"}, 500)
        await log_player_action(uid, "admin_set_inventory", {"items_count": len(inv)})
        return json_resp({"ok": True})

    if path == "/admin_pc/transfer_item":
        from_uid = int(data.get("from_user_id", 0))
        to_uid = int(data.get("to_user_id", 0))
        item_id = data.get("item_id")
        amount = int(data.get("amount", 1))
        if not from_uid or not to_uid or not item_id:
            return json_resp({"error": "bad request", "details": "missing params"})
        p1_rows = await db.select("players", f"?user_id=eq.{from_uid}")
        p2_rows = await db.select("players", f"?user_id=eq.{to_uid}")
        if not p1_rows:
            return json_resp({"error": "Игрок-отправитель не найден", "user_id": from_uid})
        if not p2_rows:
            return json_resp({"error": "Игрок-получатель не найден", "user_id": to_uid})
        stats1 = (p1_rows[0].get("stats") or {}).copy()
        stats2 = (p2_rows[0].get("stats") or {}).copy()
        inv1 = stats1.get("inventory", {})
        inv2 = stats2.get("inventory", {})
        current_count = inv1.get(item_id, 0)
        if current_count < amount:
            return json_resp({"error": f"Недостаточно предметов у отправителя. Есть: {current_count}, нужно: {amount}"})
        inv1[item_id] = current_count - amount
        if inv1[item_id] <= 0:
            del inv1[item_id]
        inv2[item_id] = inv2.get(item_id, 0) + amount
        stats1["inventory"] = inv1
        stats2["inventory"] = inv2
        r1 = await db.update("players", f"?user_id=eq.{from_uid}", {"stats": stats1})
        e1 = db_write_error(r1)
        if e1:
            return json_resp({"error": f"База не приняла запись отправителя: {e1}"}, 500)
        r2 = await db.update("players", f"?user_id=eq.{to_uid}", {"stats": stats2})
        e2 = db_write_error(r2)
        if e2:
            return json_resp({"error": f"База не приняла запись получателя: {e2}"}, 500)
        await log_player_action(from_uid, "transfer_item_out", {"item": item_id, "to": to_uid, "amount": amount})
        await log_player_action(to_uid, "transfer_item_in", {"item": item_id, "from": from_uid, "amount": amount})
        print(f"✅ TRANSFER: {item_id} x{amount} from {from_uid} to {to_uid}")
        return json_resp({
            "ok": True,
            "from_inventory": inv1,
            "to_inventory": inv2,
            "item": item_id,
            "amount": amount,
            "from_uid": from_uid,
            "to_uid": to_uid,
        })

    if path == "/admin_pc/events_list":
        events = await db.select("scheduled_events", "?order=starts_at.desc")
        return json_resp({"events": events})

    if path == "/admin_pc/notes_list":
        uid = request.query.get("user_id")
        q = "?order=created_at.desc"
        if uid:
            q = f"?user_id=eq.{uid}&order=created_at.desc"
        notes = await db.select("admin_notes", q)
        return json_resp({"notes": notes})

    return json_resp({"error": "unknown path"}, 404)

# ================= МОБИЛЬНАЯ АДМИНКА =================
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
            "grants": grants_count, "promos": promos_count,
        })

    if path == "/admin/grant":
        uid = int(data["user_id"])
        gtype = data.get("type", "coins")
        amount = int(data.get("amount", 0))
        item_id = data.get("item_id")
        reason = data.get("reason") or None
        pre = False
        if gtype == "coins":
            new_bal, err = await add_balance(uid, amount)
            if err:
                return json_resp({"ok": False, "error": err}, 500)
            pre = True
        elif gtype == "clear_coins":
            await add_balance(uid, -await get_balance(uid))
            pre = True
        elif gtype == "clear_items":
            rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
            cur = (rows[0].get("stats") if rows else None) or {}
            cur["inventory"] = {}
            cur["gift_inv"] = {}
            await db.update("players", f"?user_id=eq.{uid}", {"stats": cur})
            pre = True
        elif gtype == "vip":
            days = amount if amount and amount > 0 else VIP_DAYS
            now = datetime.now(timezone.utc)
            base = now
            st = await get_stats(uid) or {}
            old = st.get("vip_until")
            if old:
                try:
                    old_dt = datetime.fromisoformat(old)
                    if old_dt > now:
                        base = old_dt
                except Exception:
                    pass
            new_until = base + timedelta(days=days)
            err = await merge_player_stats(uid, {"vip_until": new_until.isoformat()})
            if err:
                return json_resp({"ok": False, "error": err}, 500)
            pre = True
        res = await db.insert("grants", [{
            "user_id": uid, "type": gtype, "amount": amount,
            "item_id": item_id, "reason": reason, "pre_applied": pre,
        }])
        err = db_write_error(res)
        if err:
            return json_resp({"ok": False, "error": f"База не приняла выдачу: {err}"}, 500)
        if gtype == "item" and (item_id in GIFT_CATALOG or item_id == "gift_case"):
            stats, ginv = await get_gift_inv(uid)
            ginv[item_id] = ginv.get(item_id, 0) + 1
            await set_gift_inv(uid, stats, ginv)
        return json_resp({"ok": True, "pre_applied": pre})

    if path == "/admin/annihilate":
        uid = int(data.get("user_id", 0))
        gtype = data.get("type", "coins")
        if not uid:
            return json_resp({"error": "no user_id"})
        pre = False
        if gtype == "coins":
            await add_balance(uid, -await get_balance(uid))
            pre = True
        else:
            rows = await db.select("players", f"?user_id=eq.{uid}&select=stats")
            cur = (rows[0].get("stats") if rows else None) or {}
            cur["inventory"] = {}
            cur["gift_inv"] = {}
            await db.update("players", f"?user_id=eq.{uid}", {"stats": cur})
            pre = True
        await db.insert("grants", [{
            "user_id": uid,
            "type": "clear_coins" if gtype == "coins" else "clear_items",
            "amount": 0, "reason": "Аннуляция администратором", "pre_applied": pre,
        }])
        return json_resp({"ok": True})

    if path == "/admin/reset":
        uid = int(data.get("user_id", 0))
        if not uid:
            return json_resp({"error": "no user_id"})
        await db.update("players", f"?user_id=eq.{uid}", {
            "stats": {"casesOpened": 0, "coinsSpent": 0, "balance": 2000, "inventory": {}, "gift_inv": {}},
        })
        await db.insert("grants", [{
            "user_id": uid, "type": "reset", "amount": 0, "reason": "Сброс прогресса администратором",
        }])
        return json_resp({"ok": True})

    if path == "/admin/grant_all":
        players = await db.select("players", "?select=user_id")
        amount = int(data.get("amount", 0))
        rows = []
        for p in players:
            await add_balance(p["user_id"], amount)
            rows.append({
                "user_id": p["user_id"], "type": "coins",
                "amount": amount, "reason": data.get("reason") or None, "pre_applied": True,
            })
        if rows:
            res = await db.insert("grants", rows)
            err = db_write_error(res)
            if err:
                return json_resp({"ok": False, "error": f"База не приняла выдачу: {err}"}, 500)
        return json_resp({"ok": True, "count": len(rows)})

    if path == "/admin/ban":
        uid_b = int(data["user_id"])
        await db.delete("bans", f"?user_id=eq.{uid_b}")
        res = await db.insert("bans", [{
            "user_id": uid_b,
            "reason": data.get("reason") or None,
            "ban_price": int(data.get("ban_price", 0)),
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
            "active": True,
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
                    "image": image_url,
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
    app = web.Application(middlewares=[cors_middleware], client_max_size=16 * 1024 * 1024)
    app.router.add_get("/create_invoice", handle_create_invoice)
    app.router.add_get("/create_unban_invoice", handle_create_unban_invoice)
    app.router.add_get("/game/profile", handle_game_profile)
    app.router.add_route("*", "/game/case_drop", handle_game_case_drop)
    app.router.add_get("/game/top100", handle_game_top100)
    app.router.add_route("*", "/game/avatar", handle_game_avatar)
    app.router.add_route("*", "/sync", handle_sync)
    app.router.add_route("*", "/push_stats", handle_push_stats)
    app.router.add_route("*", "/promo", handle_promo)
    app.router.add_route("*", "/open_gift_case_inv", handle_open_gift_case_inv)
    app.router.add_route("*", "/claim_gift_inv", handle_claim_gift_inv)

    for p in ["/roulette/status", "/roulette/spin", "/roulette/spin_stars", "/roulette/buy_credits"]:
        app.router.add_route("*", p, handle_roulette)

    for p in ["/pvp/list", "/pvp/create", "/pvp/join", "/pvp/room", "/pvp/roll", "/pvp/leave"]:
        app.router.add_route("*", p, handle_pvp)

    pc_paths = [
        "/admin_pc/login", "/admin_pc/players", "/admin_pc/troll",
        "/admin_pc/drop_override", "/admin_pc/event", "/admin_pc/note",
        "/admin_pc/logs", "/admin_pc/fake_tx", "/admin_pc/set_balance",
        "/admin_pc/set_inventory", "/admin_pc/transfer_item",
        "/admin_pc/events_list", "/admin_pc/notes_list",
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
        "/admin/available_gifts", "/admin/send_gift",
    ]
    for p in admin_paths:
        app.router.add_route("*", p, handle_admin)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Веб-сервер запущен на порту {port}")

async def pvp_cleanup_tick():
    try:
        now = datetime.now(timezone.utc)
        waiting = await db.select("pvp_battles", "?status=eq.waiting")
        for b in waiting:
            created = datetime.fromisoformat(b["created_at"])
            if (now - created) > timedelta(minutes=PVP_WAIT_TIMEOUT_MIN):
                ps = await db.select("pvp_players", f"?battle_code=eq.{b['code']}&seat=eq.0")
                if ps:
                    await add_balance(ps[0]["user_id"], int(b["stake"]))
                await db.update("pvp_battles", f"?code=eq.{b['code']}", {"status": "canceled"})
                print(f"🧹 PVP waiting timeout: {b['code']}")
        active = await db.select("pvp_battles", "?status=eq.active")
        for b in active:
            upd = datetime.fromisoformat(b.get("updated_at") or b["created_at"])
            if (now - upd) > timedelta(minutes=PVP_STALE_TIMEOUT_MIN):
                ps = await db.select("pvp_players", f"?battle_code=eq.{b['code']}")
                for p in ps:
                    await add_balance(p["user_id"], int(b["stake"]))
                await db.update("pvp_battles", f"?code=eq.{b['code']}", {"status": "canceled"})
                print(f"🧹 PVP stale timeout: {b['code']}")
    except Exception as e:
        print(f"PVP cleanup error: {e}")

async def cleanup_loop():
    while True:
        try:
            await db.delete("admin_sessions", f"?expires_at=lt.{now_iso()}")
        except Exception as e:
            print(f"Cleanup error: {e}")
        await pvp_cleanup_tick()
        await asyncio.sleep(60)

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
