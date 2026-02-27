import asyncio
import logging
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import Database
from config import Config
from payments import SBPPayment
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot      = Bot(token=Config.BOT_TOKEN, parse_mode="HTML")
dp       = Dispatcher(storage=MemoryStorage())
db       = Database()
sbp_pay = SBPPayment()

REFERRAL_BONUS   = 100   # ₽ рефереру за каждого приведённого друга
REFERRAL_DISCOUNT = 50   # ₽ скидка новому пользователю по реф-ссылке


# ─── STATES ────────────────────────────────────────────────────────────────────

class AdminStates(StatesGroup):
    withdraw_amount   = State()
    withdraw_details  = State()
    withdraw_confirm  = State()
    broadcast_text    = State()
    delivery_data     = State()
    delivery_expiry   = State()   # новый: ввод даты окончания подписки


# ─── KEYBOARDS ─────────────────────────────────────────────────────────────────

def main_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🛍 Открыть магазин",  web_app=WebAppInfo(url=Config.WEBAPP_URL))
    kb.button(text="📋 Мои заказы",        callback_data="my_orders")
    kb.button(text="🎁 Реферальная программа", callback_data="referral")
    kb.button(text="💬 Поддержка",         url=f"https://t.me/{Config.SUPPORT_USERNAME}")
    kb.adjust(1)
    return kb.as_markup()


def admin_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика",       callback_data="adm_stats")
    kb.button(text="💰 Баланс и вывод",   callback_data="adm_balance")
    kb.button(text="📦 Активные заказы",  callback_data="adm_orders")
    kb.button(text="👥 Пользователи",     callback_data="adm_users")
    kb.button(text="📢 Рассылка",         callback_data="adm_broadcast")
    kb.button(text="⚙️ Услуги",           callback_data="adm_services")
    kb.adjust(2, 2, 2)
    return kb.as_markup()


def back_to_admin_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад в админку", callback_data="adm_main")
    return kb.as_markup()


# ─── /START (с поддержкой реф-ссылки) ─────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    args = message.text.split()
    ref_code = args[1] if len(args) > 1 else None

    referred_by = None
    discount_text = ""

    if ref_code:
        referrer = await db.get_user_by_ref(ref_code)
        if referrer and referrer['tg_id'] != user.id:
            referred_by = referrer['tg_id']
            discount_text = f"\n\n🎁 Ты пришёл по реферальной ссылке — тебе <b>скидка {REFERRAL_DISCOUNT}₽</b> на первый заказ!"

    await db.upsert_user(user.id, user.username or "", user.full_name, referred_by=referred_by)

    if user.id in Config.ADMIN_IDS:
        await message.answer(
            f"👑 Добро пожаловать, <b>{user.first_name}</b>!\n\nИспользуй /admin для управления магазином.",
            reply_markup=admin_kb()
        )
        return

    text = (
        f"👋 Привет, <b>{user.first_name}</b>!{discount_text}\n\n"
        f"🔑 <b>KeyFlow</b> — зарубежные подписки из России\n\n"
        f"✅ Spotify, ChatGPT, Claude, Discord и другие\n"
        f"✅ Оплата СБП, картой РФ или криптой\n"
        f"✅ Выдача за 15 минут · Поддержка 24/7\n"
        f"✅ Напомним за 3 дня до окончания подписки"
    )
    await message.answer(text, reply_markup=main_kb())


# ─── /ADMIN ────────────────────────────────────────────────────────────────────

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in Config.ADMIN_IDS:
        return
    await message.answer("👑 <b>Панель администратора</b>", reply_markup=admin_kb())


# ─── МОИ ЗАКАЗЫ (история + кнопка «купить снова») ─────────────────────────────

@dp.callback_query(F.data == "my_orders")
async def cb_my_orders(callback: types.CallbackQuery):
    orders = await db.get_user_orders(callback.from_user.id)

    if not orders:
        await callback.message.answer(
            "📭 У тебя пока нет заказов.\n\nОткрой магазин и оформи первый!",
            reply_markup=main_kb()
        )
        await callback.answer()
        return

    status_icons = {
        'completed':       '✅',
        'pending':         '⏳',
        'waiting_confirm': '🔍',
        'processing':      '🔄',
        'paid':            '💰',
        'cancelled':       '❌',
    }

    text = "📋 <b>Твои заказы:</b>\n\n"
    kb   = InlineKeyboardBuilder()

    for o in orders[:8]:
        icon    = status_icons.get(o['status'], '❓')
        expires = f" · до {o['expires_at'][:10]}" if o.get('expires_at') else ""
        text += (
            f"{icon} <b>#{o['id']}</b> {o.get('service_name','?')} — {o.get('duration','')}\n"
            f"   {o['amount']}₽ · {o['created_at'][:10]}{expires}\n\n"
        )
        # Кнопка «купить снова» только для выполненных
        if o['status'] == 'completed':
            kb.button(
                text=f"🔄 Купить снова: {o.get('service_name','?')} {o.get('duration','')}",
                callback_data=f"reorder:{o['service_id']}:{o['variant_id']}:{o['amount']}"
            )

    kb.button(text="🛍 В магазин", web_app=WebAppInfo(url=Config.WEBAPP_URL))
    kb.button(text="◀️ Назад",     callback_data="back_main")
    kb.adjust(1)

    await callback.message.answer(text, reply_markup=kb.as_markup())
    await callback.answer()


# ─── КУПИТЬ СНОВА (1 клик) ─────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("reorder:"))
async def cb_reorder(callback: types.CallbackQuery):
    _, svc_id, var_id, amount = callback.data.split(":")
    svc_id = int(svc_id); var_id = int(var_id); amount = float(amount)

    service = await db.get_service(svc_id)
    variant = await db.get_variant(var_id)
    if not service or not variant:
        await callback.answer("❌ Услуга недоступна", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="🏦 Оплатить через СБП", callback_data=f"ro_pay:sbp:{svc_id}:{var_id}:{amount}")
    kb.button(text="◀️ Отмена", callback_data="my_orders")
    kb.adjust(1)

    await callback.message.answer(
        f"🔄 <b>Повторный заказ</b>\n\n"
        f"📦 {service['name']} — {variant['duration']}\n"
        f"💰 Сумма: <b>{amount}₽</b>\n\n"
        f"Выбери способ оплаты:",
        reply_markup=kb.as_markup()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("ro_pay:"))
async def cb_reorder_pay(callback: types.CallbackQuery):
    _, method, svc_id, var_id, amount = callback.data.split(":")
    svc_id = int(svc_id); var_id = int(var_id); amount = float(amount)

    service = await db.get_service(svc_id)
    variant = await db.get_variant(var_id)

    order_id = await db.create_order(
        user_id=callback.from_user.id,
        service_id=svc_id,
        variant_id=var_id,
        amount=amount,
        payment_method=method,
    )

    fake_data = {
        'service_id': svc_id, 'variant_id': var_id,
        'service_name': service['name'], 'variant_dur': variant['duration'],
        'amount': amount, 'payment': method, 'order_id': order_id,
    }

    # Уведомляем пользователя и уведомляем админов
    await send_payment_instructions(callback.message, order_id, fake_data, callback.from_user)
    await notify_admins_new_order(order_id, callback.from_user, fake_data)
    await callback.answer()


# ─── РЕФЕРАЛЬНАЯ ПРОГРАММА ─────────────────────────────────────────────────────

@dp.callback_query(F.data == "referral")
async def cb_referral(callback: types.CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return

    ref_code  = user.get('ref_code', '—')
    ref_link  = f"https://t.me/{(await bot.get_me()).username}?start={ref_code}"
    ref_count = await db.get_referral_count(callback.from_user.id)
    bonus     = user.get('bonus_balance', 0)

    await callback.message.answer(
        f"🎁 <b>Реферальная программа KeyFlow</b>\n\n"
        f"Приглашай друзей — зарабатывай бонусы!\n\n"
        f"💰 <b>Ты получаешь:</b> {REFERRAL_BONUS}₽ за каждого друга\n"
        f"🎉 <b>Друг получает:</b> скидку {REFERRAL_DISCOUNT}₽ на первый заказ\n\n"
        f"👥 Приглашено друзей: <b>{ref_count}</b>\n"
        f"💳 Бонусный баланс: <b>{bonus}₽</b>\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"Нажми на ссылку чтобы скопировать и поделиться!",
        reply_markup=InlineKeyboardBuilder()
            .button(text="📤 Поделиться ссылкой",
                    url=f"https://t.me/share/url?url={ref_link}&text=Покупай зарубежные подписки через KeyFlow — быстро, надёжно, из России!")
            .button(text="◀️ Назад", callback_data="back_main")
            .adjust(1).as_markup()
    )
    await callback.answer()


@dp.callback_query(F.data == "back_main")
async def cb_back_main(callback: types.CallbackQuery):
    await callback.message.answer("Главное меню:", reply_markup=main_kb())
    await callback.answer()


# ─── WEBAPP DATA HANDLER ───────────────────────────────────────────────────────

@dp.message(F.web_app_data)
async def handle_webapp_data(message: types.Message):
    try:
        data   = json.loads(message.web_app_data.data)
        action = data.get('action')

        if action in ('create_order', 'create_cart_order'):
            await process_new_order(message, data)
        elif action == 'sbp_paid':
            await process_sbp_paid(message, data)

    except json.JSONDecodeError:
        logger.error(f"Invalid JSON from WebApp: {message.web_app_data.data}")
    except Exception as e:
        logger.error(f"WebApp data error: {e}", exc_info=True)


async def process_new_order(message: types.Message, data: dict):
    # Корзина — несколько товаров
    if data.get('action') == 'create_cart_order':
        items    = data.get('items', [])
        total    = data.get('total', 0)
        payment  = data.get('payment', 'sbp')
        order_ids = []
        for item in items:
            oid = await db.create_order(
                user_id=message.from_user.id,
                service_id=item['service_id'],
                variant_id=item['variant_id'],
                amount=item['amount'] * item.get('qty', 1),
                payment_method=payment,
                webapp_order_id=data.get('order_id')
            )
            order_ids.append(oid)
        summary = ', '.join(f"{i['service_name']} {i['variant_dur']}" for i in items)
        cart_data = {
            'service_name': summary, 'variant_dur': '',
            'amount': total, 'payment': payment,
            'order_id': data.get('order_id'),
        }
        await send_payment_instructions(message, order_ids[0], cart_data, message.from_user)
        await notify_admins_new_order(order_ids[0], message.from_user, cart_data)
        return

    # Одиночный заказ
    order_id = await db.create_order(
        user_id=message.from_user.id,
        service_id=data['service_id'],
        variant_id=data['variant_id'],
        amount=data['amount'],
        payment_method=data['payment'],
        webapp_order_id=data.get('order_id')
    )
    await send_payment_instructions(message, order_id, data, message.from_user)
    await notify_admins_new_order(order_id, message.from_user, data)


async def send_payment_instructions(message, order_id, data, user):
    """Единая функция отправки инструкций по оплате"""
    service_name = data.get('service_name', 'Услуга')
    variant_dur  = data.get('variant_dur', '')
    amount       = data['amount']
    payment      = data['payment']

    # Пуш: заказ создан
    await message.answer(
        f"🛍 <b>Заказ #{order_id} создан!</b>\n\n"
        f"📦 {service_name}{' — ' + variant_dur if variant_dur else ''}\n"
        f"💰 Сумма: <b>{amount}₽</b>\n\n"
        f"⏳ Ожидаем оплату..."
    )

    # Все заказы идут через СБП — ручная верификация
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Я оплатил", callback_data=f"sbp_confirm:{order_id}")
    kb.adjust(1)
    await message.answer(
        f"🏦 <b>Оплата через СБП</b>\n\n"
        f"Переведи <b>{amount}₽</b> по номеру:\n"
        f"📱 <code>{Config.SBP_PHONE}</code> ({Config.SBP_BANK})\n"
        f"👤 Получатель: <b>{Config.SBP_RECIPIENT}</b>\n\n"
        f"⚠️ Комментарий к переводу: <code>#{data.get('order_id', order_id)}</code>\n\n"
        f"После перевода нажми кнопку ниже 👇",
        reply_markup=kb.as_markup()
    )


# ─── СБП: клиент нажал "Я оплатил" ───────────────────────────────────────────

@dp.callback_query(F.data.startswith("sbp_confirm:"))
async def cb_sbp_confirm(callback: types.CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    await db.update_order_status(order_id, 'waiting_confirm')

    # Пуш клиенту
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"🔍 <b>Проверяем оплату по заказу #{order_id}</b>\n\n"
        f"Обычно подтверждение занимает 5–15 минут.\n"
        f"Мы сразу уведомим тебя!"
    )

    # Уведомляем админов
    for admin_id in Config.ADMIN_IDS:
        try:
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Подтвердить оплату", callback_data=f"adm_confirm_sbp:{order_id}")
            kb.button(text="❌ Отклонить",           callback_data=f"adm_reject:{order_id}")
            kb.adjust(1)
            order = await db.get_order(order_id)
            await bot.send_message(
                admin_id,
                f"💰 <b>Клиент заявил об оплате СБП — Заказ #{order_id}</b>\n\n"
                f"👤 ID: {order['user_id']}\n"
                f"💰 {order['amount']}₽\n"
                f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                reply_markup=kb.as_markup()
            )
        except Exception:
            pass
    await callback.answer("✅ Заявка отправлена!")


async def process_sbp_paid(message: types.Message, data: dict):
    """Старый хендлер из WebApp (оставлен для совместимости)"""
    webapp_order_id = data.get('order_id')
    order = await db.get_order_by_webapp_id(webapp_order_id)
    if not order:
        return
    await db.update_order_status(order['id'], 'waiting_confirm')
    for admin_id in Config.ADMIN_IDS:
        try:
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Подтвердить", callback_data=f"adm_confirm_sbp:{order['id']}")
            kb.button(text="❌ Отклонить",   callback_data=f"adm_reject:{order['id']}")
            kb.adjust(1)
            await bot.send_message(admin_id, f"💰 Клиент оплатил СБП — заказ #{order['id']}", reply_markup=kb.as_markup())
        except Exception:
            pass






# ─── КРИПТО: проверка ─────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("check_crypto:"))

# ─── ADMIN: статистика ─────────────────────────────────────────────────────────

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in Config.ADMIN_IDS:
        return
    await message.answer("👑 <b>Панель администратора</b>", reply_markup=admin_kb())


@dp.callback_query(F.data == "adm_main")
async def cb_adm_main(callback: types.CallbackQuery):
    if callback.from_user.id not in Config.ADMIN_IDS:
        return
    await callback.message.edit_text("👑 <b>Панель администратора</b>", reply_markup=admin_kb())


@dp.callback_query(F.data == "adm_stats")
async def cb_adm_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in Config.ADMIN_IDS:
        return
    s = await db.get_stats()
    await callback.message.edit_text(
        f"📊 <b>Статистика KeyFlow</b>\n\n"
        f"👥 Пользователей: <b>{s['total_users']}</b>\n\n"
        f"📦 Заказов всего: <b>{s['total_orders']}</b>\n"
        f"   ✅ Выполнено: {s['completed_orders']}\n"
        f"   🔄 Активных: {s['active_orders']}\n"
        f"   ❌ Отменено: {s['cancelled_orders']}\n\n"
        f"💰 Выручка:\n"
        f"   Сегодня: <b>{s['today_revenue']}₽</b> ({s['today_orders']} заказов)\n"
        f"   Неделя:  <b>{s['week_revenue']}₽</b>\n"
        f"   Месяц:   <b>{s['month_revenue']}₽</b>\n"
        f"   Всего:   <b>{s['total_revenue']}₽</b>\n\n"
        f"💳 По способам:\n"
        f"   СБП: {s['sbp_revenue']}₽ · Крипта: {s['crypto_revenue']}₽ · Карта: {s['card_revenue']}₽",
        reply_markup=back_to_admin_kb()
    )


@dp.callback_query(F.data == "adm_balance")
async def cb_adm_balance(callback: types.CallbackQuery):
    if callback.from_user.id not in Config.ADMIN_IDS:
        return
    b = await db.get_balance()
    kb = InlineKeyboardBuilder()
    kb.button(text="💸 Вывести средства", callback_data="adm_withdraw")
    kb.button(text="◀️ Назад",            callback_data="adm_main")
    kb.adjust(1)
    await callback.message.edit_text(
        f"💰 <b>Баланс</b>\n\n"
        f"Всего заработано: <b>{b['total_earned']}₽</b>\n"
        f"Доступно:         <b>{b['available']}₽</b>\n"
        f"Заморожено:       <b>{b['frozen']}₽</b>\n"
        f"Выведено:         <b>{b['withdrawn']}₽</b>",
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data == "adm_withdraw")
async def cb_adm_withdraw(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in Config.ADMIN_IDS:
        return
    await state.set_state(AdminStates.withdraw_amount)
    await callback.message.edit_text("💸 <b>Вывод средств</b>\n\nВведи сумму для вывода (₽):")


@dp.message(AdminStates.withdraw_amount)
async def adm_withdraw_amount(message: types.Message, state: FSMContext):
    if message.from_user.id not in Config.ADMIN_IDS:
        return
    try:
        amount = float(message.text.replace(',', '.'))
        b = await db.get_balance()
        if amount > b['available']:
            await message.answer(f"❌ Недостаточно средств. Доступно: {b['available']}₽")
            return
        await state.update_data(withdraw_amount=amount)
        await state.set_state(AdminStates.withdraw_details)
        await message.answer("Введи реквизиты для вывода (номер карты, СБП или крипто-адрес):")
    except ValueError:
        await message.answer("❌ Введи число")


@dp.message(AdminStates.withdraw_details)
async def adm_withdraw_details(message: types.Message, state: FSMContext):
    if message.from_user.id not in Config.ADMIN_IDS:
        return
    data = await state.get_data()
    amount = data['withdraw_amount']
    await db.create_withdrawal(message.from_user.id, amount, message.text)
    await state.clear()
    await message.answer(f"✅ Вывод <b>{amount}₽</b> зафиксирован.", reply_markup=back_to_admin_kb())


@dp.callback_query(F.data == "adm_orders")
async def cb_adm_orders(callback: types.CallbackQuery):
    if callback.from_user.id not in Config.ADMIN_IDS:
        return
    orders = await db.get_active_orders()
    if not orders:
        await callback.message.edit_text("📭 Активных заказов нет.", reply_markup=back_to_admin_kb())
        return
    text = "📦 <b>Активные заказы:</b>\n\n"
    kb   = InlineKeyboardBuilder()
    for o in orders:
        text += f"#{o['id']} @{o.get('username','?')} · {o.get('service_name','?')} {o.get('duration','')} · {o['amount']}₽ · {o['status']}\n"
        kb.button(text=f"📦 Выдать #{o['id']}", callback_data=f"adm_deliver:{o['id']}")
    kb.button(text="◀️ Назад", callback_data="adm_main")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


# ─── ADMIN: выдача подписки + дата окончания ──────────────────────────────────

@dp.callback_query(F.data.startswith("adm_deliver:"))
async def cb_adm_deliver(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in Config.ADMIN_IDS:
        return
    order_id = int(callback.data.split(":")[1])
    await state.update_data(delivery_order_id=order_id)
    await state.set_state(AdminStates.delivery_data)
    await callback.message.answer(
        f"📦 <b>Выдача подписки — Заказ #{order_id}</b>\n\n"
        f"Введи данные для клиента:\n\n"
        f"<code>Логин: example@gmail.com\nПароль: Pass123!\nПримечание: смени пароль после входа</code>"
    )


@dp.message(AdminStates.delivery_data)
async def adm_delivery_data(message: types.Message, state: FSMContext):
    if message.from_user.id not in Config.ADMIN_IDS:
        return
    await state.update_data(delivery_text=message.text)
    await state.set_state(AdminStates.delivery_expiry)
    await message.answer(
        "📅 Укажи дату окончания подписки (для авто-напоминания):\n\n"
        "Формат: <code>ДД.ММ.ГГГГ</code>\n"
        "Например: <code>27.05.2026</code>\n\n"
        "Или напиши <b>пропустить</b>"
    )


@dp.message(AdminStates.delivery_expiry)
async def adm_delivery_expiry(message: types.Message, state: FSMContext):
    if message.from_user.id not in Config.ADMIN_IDS:
        return
    data     = await state.get_data()
    order_id = data['delivery_order_id']
    order    = await db.get_order(order_id)
    service  = await db.get_service(order['service_id'])

    # Парсим дату
    expires_at = None
    if message.text.strip().lower() != 'пропустить':
        try:
            dt = datetime.strptime(message.text.strip(), "%d.%m.%Y")
            expires_at = dt.strftime("%Y-%m-%d")
        except ValueError:
            await message.answer("❌ Неверный формат даты. Введи ДД.ММ.ГГГГ или 'пропустить'")
            return

    await db.update_order_status(order_id, 'completed')
    if expires_at:
        await db.set_order_expiry(order_id, expires_at)
    await state.clear()

    # Начисляем бонус рефереру
    user = await db.get_user(order['user_id'])
    if user and user.get('referred_by'):
        await db.add_bonus(user['referred_by'], REFERRAL_BONUS)
        try:
            await bot.send_message(
                user['referred_by'],
                f"🎉 <b>Тебе начислен бонус {REFERRAL_BONUS}₽!</b>\n\n"
                f"Твой друг совершил первую покупку в KeyFlow.\n"
                f"Бонус доступен в разделе «Реферальная программа»."
            )
        except Exception:
            pass

    # Отправляем данные клиенту
    expires_text = f"\n\n📅 Подписка до: <b>{message.text}</b>" if expires_at else ""
    try:
        await bot.send_message(
            order['user_id'],
            f"🎉 <b>Твоя подписка готова!</b>\n\n"
            f"📦 Заказ #{order_id} · {service['name']}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{data['delivery_text']}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
            f"{expires_text}\n\n"
            f"✨ Спасибо за покупку в KeyFlow!\n"
            f"При проблемах: @{Config.SUPPORT_USERNAME}",
            reply_markup=main_kb()
        )
        exp_note = f" · До {expires_at}" if expires_at else ""
        await message.answer(f"✅ Данные отправлены клиенту — заказ #{order_id} выполнен!{exp_note}")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить клиенту: {e}\n\nДанные: {data['delivery_text']}")


# ─── ADMIN: подтверждение / отклонение СБП ────────────────────────────────────

@dp.callback_query(F.data.startswith("adm_confirm_sbp:"))
async def cb_adm_confirm_sbp(callback: types.CallbackQuery):
    if callback.from_user.id not in Config.ADMIN_IDS:
        return
    order_id = int(callback.data.split(":")[1])
    await db.update_order_status(order_id, 'paid')
    order = await db.get_order(order_id)

    # Пуш клиенту
    try:
        await bot.send_message(
            order['user_id'],
            f"✅ <b>Оплата подтверждена!</b>\n\n"
            f"Заказ #{order_id} принят в обработку.\n"
            f"Данные подписки придут в течение 15 минут."
        )
    except Exception:
        pass

    await callback.message.edit_text(
        f"✅ Оплата по заказу #{order_id} подтверждена. Выдай подписку клиенту.",
        reply_markup=InlineKeyboardBuilder()
            .button(text="📦 Выдать подписку", callback_data=f"adm_deliver:{order_id}")
            .as_markup()
    )


@dp.callback_query(F.data.startswith("adm_reject:"))
async def cb_adm_reject(callback: types.CallbackQuery):
    if callback.from_user.id not in Config.ADMIN_IDS:
        return
    order_id = int(callback.data.split(":")[1])
    await db.update_order_status(order_id, 'cancelled')
    order = await db.get_order(order_id)

    try:
        await bot.send_message(
            order['user_id'],
            f"❌ <b>Заказ #{order_id} отклонён.</b>\n\n"
            f"Оплата не найдена или отменена.\n"
            f"Если ты уже оплатил — напиши в поддержку: @{Config.SUPPORT_USERNAME}"
        )
    except Exception:
        pass

    await callback.message.edit_text(f"❌ Заказ #{order_id} отклонён.", reply_markup=back_to_admin_kb())


# ─── ADMIN: пользователи, рассылка, услуги ────────────────────────────────────

@dp.callback_query(F.data == "adm_users")
async def cb_adm_users(callback: types.CallbackQuery):
    if callback.from_user.id not in Config.ADMIN_IDS:
        return
    stats = await db.get_stats()
    users = await db.get_recent_users(limit=10)
    text  = f"👥 <b>Пользователи</b>\n\nВсего: <b>{stats['total_users']}</b>\n\n<b>Последние:</b>\n"
    for u in users:
        text += f"• @{u.get('username') or 'без ника'} — {u['created_at'][:10]}\n"
    await callback.message.edit_text(text, reply_markup=back_to_admin_kb())


@dp.callback_query(F.data == "adm_broadcast")
async def cb_adm_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in Config.ADMIN_IDS:
        return
    await state.set_state(AdminStates.broadcast_text)
    await callback.message.edit_text("📢 <b>Рассылка</b>\n\nВведи текст сообщения (поддерживается HTML):")


@dp.message(AdminStates.broadcast_text)
async def adm_broadcast_send(message: types.Message, state: FSMContext):
    if message.from_user.id not in Config.ADMIN_IDS:
        return
    await state.clear()
    users   = await db.get_all_users()
    success = 0
    for u in users:
        try:
            await bot.send_message(u['tg_id'], message.text, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f"✅ <b>Рассылка завершена</b>\n\nОтправлено: {success}/{len(users)}", reply_markup=back_to_admin_kb())


@dp.callback_query(F.data == "adm_services")
async def cb_adm_services(callback: types.CallbackQuery):
    if callback.from_user.id not in Config.ADMIN_IDS:
        return
    services = await db.get_services()
    text = "⚙️ <b>Управление услугами</b>\n\n"
    kb   = InlineKeyboardBuilder()
    for s in services:
        status = '✅' if s['is_active'] else '❌'
        text  += f"{status} {s['name']} — от {s['min_price']}₽\n"
        kb.button(text=f"{'🔴' if s['is_active'] else '🟢'} {s['name']}", callback_data=f"adm_toggle_svc:{s['id']}")
    kb.button(text="◀️ Назад", callback_data="adm_main")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


@dp.callback_query(F.data.startswith("adm_toggle_svc:"))
async def cb_adm_toggle_service(callback: types.CallbackQuery):
    if callback.from_user.id not in Config.ADMIN_IDS:
        return
    await db.toggle_service(int(callback.data.split(":")[1]))
    await cb_adm_services(callback)


# ─── NOTIFY HELPERS ───────────────────────────────────────────────────────────

async def notify_admins_new_order(order_id, user, data):
    pay_icons = {'sbp': '🏦', 'crypto': '₿', 'card': '💳'}
    pay_icon  = pay_icons.get(data.get('payment', ''), '💰')
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Выдать подписку", callback_data=f"adm_deliver:{order_id}")
    kb.adjust(1)
    for admin_id in Config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🔔 <b>Новый заказ #{order_id}</b>\n\n"
                f"👤 @{user.username or 'без ника'} (ID: {user.id})\n"
                f"🛍 {data.get('service_name')} {data.get('variant_dur','')}\n"
                f"💰 {data.get('amount')}₽ {pay_icon} {data.get('payment','').upper()}\n"
                f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                reply_markup=kb.as_markup()
            )
        except Exception:
            pass


async def notify_admins_payment_confirmed(order_id, method):
    pay_icons = {'sbp': '🏦', 'crypto': '₿', 'card': '💳'}
    order = await db.get_order(order_id)
    kb    = InlineKeyboardBuilder()
    kb.button(text="📦 Выдать подписку", callback_data=f"adm_deliver:{order_id}")
    for admin_id in Config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"✅ <b>Оплата подтверждена — #{order_id}</b>\n\n"
                f"💰 {order['amount']}₽ {pay_icons.get(method,'')} {method.upper()}\n"
                f"Выдай подписку клиенту:",
                reply_markup=kb.as_markup()
            )
        except Exception:
            pass


# ─── АВТО-НАПОМИНАНИЕ (фоновая задача) ────────────────────────────────────────

async def reminder_loop():
    """Каждый день в 10:00 проверяем истекающие подписки"""
    while True:
        now = datetime.now()
        # Следующий запуск в 10:00
        next_run = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())

        try:
            expiring = await db.get_expiring_orders(days_ahead=3)
            for order in expiring:
                try:
                    kb = InlineKeyboardBuilder()
                    kb.button(text="🔄 Продлить в 1 клик", callback_data=f"reorder:{order['service_id']}:{order['variant_id']}:{order['amount']}")
                    kb.button(text="🛍 В магазин", web_app=WebAppInfo(url=Config.WEBAPP_URL))
                    kb.adjust(1)
                    await bot.send_message(
                        order['user_id'],
                        f"⏰ <b>Напоминание о подписке</b>\n\n"
                        f"📦 <b>{order['service_name']}</b> — {order['duration']}\n"
                        f"⚠️ Заканчивается через <b>3 дня</b> ({order['expires_at'][:10]})\n\n"
                        f"Продли прямо сейчас в 1 клик 👇",
                        reply_markup=kb.as_markup()
                    )
                    await db.mark_reminded(order['id'])
                    logger.info(f"Reminder sent for order #{order['id']}")
                except Exception as e:
                    logger.error(f"Reminder error for order #{order['id']}: {e}")
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

async def main():
    await db.init()
    logger.info("🔑 KeyFlow Bot запущен!")
    # Запускаем фоновую задачу напоминаний
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
