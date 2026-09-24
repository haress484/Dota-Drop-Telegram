import asyncio
import json
import os
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, LabeledPrice, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup, PreCheckoutQuery
from aiohttp import web

# ================= НАСТРОЙКИ =================
# Берем токен из переменных окружения Render, или используем твой (если не задано)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8877203912:AAGZlkkgJZZV1suF9EyqEWKp7PIRv2VxOz4")
CHANNEL_USERNAME = "@the_kubicki"
# Ссылка на Cloudflare Pages будет вставлена позже, пока оставь заглушку или свою текущую
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://haress484.github.io/Dota-Drop-Telegram/")
DB_FILE = "balances.json"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= БАЗА ДАННЫХ =================
def get_db():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def add_balance(user_id: int, amount: int):
    db = get_db()
    uid = str(user_id)
    db[uid] = db.get(uid, 0) + amount
    save_db(db)
    return db[uid]

# ================= ПРОВЕРКА ПОДПИСКИ =================
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        print(f"Ошибка проверки подписки: {e}")
        return False

def get_subscribe_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
        [InlineKeyboardButton(text="✅ Я подписался, проверить", callback_data="check_sub")]
    ])

def get_play_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 ИГРАТЬ", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])

# ================= ОБРАБОТЧИКИ =================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer(
            f"👋 Привет! Чтобы получить доступ к боту, подпишись на канал:\n\n"
            f"📢 {CHANNEL_USERNAME}\n\n"
            f"После подписки нажми кнопку ниже.",
            reply_markup=get_subscribe_keyboard()
        )
        return

    db = get_db()
    balance = db.get(str(user_id), 0)
    await message.answer(
        f"🎉 Добро пожаловать в Dota Drop!\n💰 Баланс: {balance} монет.\n\n"
        f"Нажми кнопку ниже, чтобы играть!",
        reply_markup=get_play_keyboard()
    )

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_subscription(user_id):
        db = get_db()
        balance = db.get(str(user_id), 0)
        await callback.message.edit_text(
            f"✅ Подписка подтверждена!\n💰 Баланс: {balance} монет.\n\n"
            f"Нажми кнопку ниже, чтобы играть!",
            reply_markup=get_play_keyboard()
        )
        await callback.answer("Спасибо за подписку!")
    else:
        await callback.answer("⚠️ Вы всё ещё не подписаны!", show_alert=True)

# ================= ОПЛАТА =================
@dp.pre_checkout_query()
async def on_pre_checkout_query(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def on_successful_payment(message: Message):
    user_id = message.from_user.id
    payment = message.successful_payment
    coins_to_add = 1000
    new_balance = add_balance(user_id, coins_to_add)
    await message.answer(
        f"✅ Оплата {payment.total_amount} {payment.currency} прошла!\n"
        f"🎁 Начислено {coins_to_add} монет.\n💰 Баланс: {new_balance}",
        reply_markup=get_play_keyboard()
    )

# ================= ВЕБ-СЕРВЕР (API) =================
async def handle_balance(request):
    user_id = request.query.get('user_id')
    if not user_id:
        return web.json_response({"error": "No user_id"}, status=400)
    db = get_db()
    balance = db.get(str(user_id), 0)
    return web.json_response({"balance": balance}, headers={"Access-Control-Allow-Origin": "*"})

async def handle_create_invoice(request):
    user_id = request.query.get('user_id')
    stars = int(request.query.get('stars', 15))
    if not user_id:
        return web.json_response({"error": "No user_id"}, status=400)
    try:
        invoice_link = await bot.create_invoice_link(
            title="Пополнение Dota Drop",
            description=f"Пополнение на {stars} Stars (1000 монет)",
            payload=f"topup_{user_id}_{stars}",
            currency="XTR",
            prices=[LabeledPrice(label="Пополнение", amount=stars)]
        )
        return web.json_response({"invoice_link": invoice_link}, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/balance', handle_balance)
    app.router.add_get('/create_invoice', handle_create_invoice)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # ВАЖНО для Render: слушаем все интерфейсы (0.0.0.0) и порт из переменной окружения
    PORT = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"🌐 Веб-сервер запущен на порту {PORT}")

# ================= ЗАПУСК =================
async def main():
    print("🚀 Запуск...")
    asyncio.create_task(start_web_server())
    print("🤖 Бот запущен и ожидает команды!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
