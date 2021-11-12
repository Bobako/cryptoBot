import json
import decimal
import math
import time
from decimal import Decimal

import telebot

from sqlalchemy import exc
from telebot import types

import database
from cfg import *
import cr_utils


class Callback:
    callback_funcs = {}
    inline_messages = {}

    def __init__(self):
        pass

    def register_callback(self, message, func, *args):
        self.delete_old_inline(message.chat.id)
        key = str(message.chat.id) + str(message.id)
        self.callback_funcs[key] = [func, args]
        self.inline_messages[message.chat.id] = message.id

    def run_callback(self, call, data):
        bot.answer_callback_query(call.id)
        bot.delete_message(call.message.chat.id, call.message.id)
        key = str(call.message.chat.id) + str(call.message.id)
        try:
            func, args = self.callback_funcs[key]
        except KeyError:
            return
        func(call, data, *args)

    def delete_old_inline(self, uid):
        if uid in self.inline_messages:
            if self.inline_messages[uid]:
                try:
                    bot.delete_message(uid, self.inline_messages[uid])
                except:
                    pass
                self.inline_messages[uid] = None


db = database.Handler()
cb = Callback()
bot = telebot.TeleBot(BOT_TOKEN)
cr_utils.save_escrow_chats()


# admin commands
@bot.message_handler(commands=["id"])
def check_id(message):
    bot.reply_to(message, message.chat.id)


@bot.message_handler(commands=["rate"])
def rate(message):
    if not (message.from_user.username in ADMINS and message.chat.id == RATE_CHANGE_CHAT_ID):
        return
    try:
        _, fiat_name, buy_rate, sell_rate = message.text.split(" ")
    except ValueError:
        bot.reply_to(message, "Ошибка форматирования")
        return

    cr_utils.update_fiat_rates(fiat_name, buy_rate, sell_rate)
    bot.reply_to(message, "Курс обновлен")


@bot.message_handler(commands=["balance"])
def balance_admin(message=None):
    if message:
        if message.chat.id != WALLET_CHAT_ID:
            return
    sys_bal = db.count_system_balances()
    bin_bal = cr_utils.get_bin_balance()
    msg = "Общий баланс пользователей:\n"
    for val, bal in zip(sys_bal.keys(), sys_bal.values()):
        msg += f"{bal} {val};  "
    msg += "\nБаланс binance:\n"
    for val, bal in zip(bin_bal.keys(), bin_bal.values()):
        msg += f"{bal} {val};  "
    bot.send_message(WALLET_CHAT_ID, msg)


@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    data = json.loads(call.data)
    if "placeholder" in data:
        return
    cb.run_callback(call, data)


@bot.message_handler(content_types=["new_chat_members"])
def handler_new_member(message):
    chat_id = message.chat.id
    if chat_id in (chats.keys()):
        bot.send_message(chat_id, chats[chat_id])


# start, menu and some starting funcs
@bot.message_handler(commands=["start"])
def start(message):
    try:
        db.create_user(message.from_user.id, message.from_user.username, DEFAULT_LANGUAGE, message.from_user.first_name)
    except exc.IntegrityError:
        main_menu(db.get_user(message.from_user.id))
    else:
        select_language1(db.get_user(message.from_user.id), select_fiat1)


def select_language1(user, next_func):
    message = bot.send_message(user.id, MSGS[user.lang]["ChooseLang"],
                               reply_markup=select_language_keyboard())
    cb.register_callback(message, select_language2, next_func)


def select_language_keyboard():
    k = types.InlineKeyboardMarkup()
    langs = list(MSGS.keys())
    icons = [lang["Icon"] for lang in list(MSGS.values())]
    for lang, icon in zip(langs, icons):
        k.add(types.InlineKeyboardButton(text=icon, callback_data=json.dumps({"lang": lang})))
    return k


def select_language2(call, data, next_func):
    lang = data["lang"]
    user = db.get_user(call.from_user.id)
    db.update_user(user.id, lang=lang)
    bot.send_message(user.id, MSGS[user.lang]["LangUpdated"].format(lang))
    user = db.get_user(call.from_user.id)
    if next_func:
        next_func(user)


def select_fiat1(user):
    message = bot.send_message(user.id, MSGS[user.lang]["ChooseFiat"],
                               reply_markup=currencies_keyboard(FIAT_CURRENCIES))
    cb.register_callback(message, select_fiat2)


def select_fiat2(call, data):
    user = db.get_user(call.from_user.id)
    fiat = data["currency"]
    db.update_user(user.id, fiat=fiat)
    bot.send_message(user.id, MSGS[user.lang]["FiatUpdated"].format(fiat))
    main_menu(user)


def currencies_keyboard(currencies):
    k = types.InlineKeyboardMarkup()
    for currency in currencies:
        k.add(types.InlineKeyboardButton(text=currency, callback_data=json.dumps({"currency": currency})))
    return k


def main_menu(user):
    cb.delete_old_inline(user.id)
    bot.send_message(user.id, MSGS[user.lang]["MainMenu"].format(user.first_name), reply_markup=menu_keyboard(user),
                     parse_mode="HTML")


def menu_keyboard(user):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.row(MSGS[user.lang]["Operations"], MSGS[user.lang]["Wallet"])
    k.row(MSGS[user.lang]["Settings"], MSGS[user.lang]["Support"])
    return k


@bot.message_handler()
def menu_handler(message):
    try:
        user = db.get_user(message.from_user.id)
    except exc.NoResultFound:
        start(message)
        return
    cb.delete_old_inline(user.id)
    if message.text == MSGS[user.lang]["Operations"]:
        operations_menu(user)
    elif message.text == MSGS[user.lang]["Wallet"]:
        wallet_menu(user)
    elif message.text == MSGS[user.lang]["Settings"]:
        settings_menu(user)
    elif message.text == MSGS[user.lang]["Support"]:
        support_menu(user)
    elif message.text == MSGS[user.lang]["Back"]:
        main_menu(user)


# operations menu
def operations_menu(user):
    message = bot.send_message(user.id, MSGS[user.lang]["OperationsMenu"], reply_markup=operations_menu_keyboard(user),
                     parse_mode="HTML")
    cb.register_callback(message, operations_menu2)


def operations_menu2(call, data):
    user = db.get_user(call.from_user.id)
    if "FastExchange" in data:
        fast_exchange(user)
    elif "EscrowExchange" in data:
        escrow_exchange(user)
    elif "P2P" in data:
        p2p_exchange(user)


def p2p_exchange(user):
    if not user.balance:
        bot.send_message(user.id, MSGS[user.lang]["NoBalance"])
        return
    currencies = [balance_obj.currency for balance_obj in user.balance]
    message = select_currency(user, currencies, "Sell")
    cb.register_callback(message, p2p_exchange2)


def p2p_exchange2(call, data):
    sell_cur = data["currency"]
    user = db.get_user(call.from_user.id)
    if sell_cur in FIAT_CURRENCIES:
        currencies = CRYPTO_CURRENCIES
    else:
        currencies = [user.fiat] + CRYPTO_CURRENCIES
    bot.send_message(user.id, MSGS[user.lang]["CurrencyChosen"].format(sell_cur))
    message = select_currency(user, currencies, "Buy")
    cb.register_callback(message, p2p_exchange3, sell_cur)


def p2p_exchange3(call, data, sell_cur):
    user = db.get_user(call.from_user.id)
    buy_cur = data["currency"]
    bot.send_message(user.id, MSGS[user.lang]["CurrencyChosen"].format(buy_cur))
    user = db.get_user(call.from_user.id)
    p2p_exchange4(user, sell_cur, buy_cur)


def p2p_exchange4(user, sell_cur, buy_cur):
    message = bot.send_message(user.id, MSGS[user.lang]["P2PMenu"], reply_markup=p2p_exchange_keyboard(user))
    cb.register_callback(message, p2p_exchange5, sell_cur, buy_cur)


def p2p_exchange5(call, data, sell_cur, buy_cur):
    user = db.get_user(call.from_user.id)
    if "SeeOrders" in data:
        orders_paginator(user, sell_cur, buy_cur)
        return

    elif "CreateOrder" in data:
        create_order(user, sell_cur, buy_cur)

    elif "SeeOwnOrders" in data:
        my_orders_paginator(user, sell_cur, buy_cur)


def my_orders_paginator(user, sell_cur, buy_cur, start=0, end=9):
    orders = db.get_orders(sell_cur, buy_cur, user.id, self_=True)
    if not orders:
        bot.send_message(user.id, MSGS[user.lang]["NoOrders"])
        p2p_exchange4(user, sell_cur, buy_cur)
        return
    pages = math.ceil(len(orders) / 9)
    page = int(start / 9) + 1
    message = bot.send_message(user.id, MSGS[user.lang]["OrdersView"].format(page, pages),
                               reply_markup=paginator_keyboard(user.lang, orders[start:end], page != 1, page != pages))
    cb.register_callback(message, my_orders_paginator2, sell_cur, buy_cur, start, end)


def my_orders_paginator2(call, data, sell_cur, buy_cur, start, end):
    user = db.get_user(call)
    if "prev" in data or "next" in data:
        if "prev" in data:
            end = start
            start = start - 9
        else:
            start = end
            end = end + 9
        orders_paginator(user, sell_cur, buy_cur, start, end)
        return
    else:
        order_id = data["order_id"]
        order = db.get_order(order_id)
        message = bot.send_message(user.id,
                                   MSGS[user.lang]["DeleteOrder"].format(order.format(user.lang, status=False)),
                                   reply_markup=get_confirm_keyboard(user))
        cb.register_callback(message, remove_order1, order_id)


def remove_order1(call, data, order_id):
    user = db.get_user(call.from_user.id)
    order = db.get_order(order_id)
    if data["confirm"]:
        db.freeze_order(order_id, False)
        db.delete_order(order_id)
        bot.send_message(user.id, MSGS[user.lang]["OrderDeleted"])
    p2p_exchange4(user, order.sell_currency, order.buy_currency)


def create_order(user, sell_cur, buy_cur):
    msg = MSGS[user.lang]["CurrentBalance"].format(user.balance_in(sell_cur), sell_cur)
    msg += "\n" + MSGS[user.lang]["EnterSellSum"]
    message = bot.send_message(user.id, msg, reply_markup=back_keyboard(user))
    bot.register_next_step_handler(message, create_order2, sell_cur, buy_cur)


def create_order2(message, sell_cur, but_cur):
    user = db.get_user(message.from_user.id)
    amount = message.text
    if amount == MSGS[user.lang]["Back"]:
        p2p_exchange4(user, sell_cur, but_cur)
        return
    try:
        amount = Decimal(amount.replace(",", "."))
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, create_order2, sell_cur, but_cur)
        return
    if amount > user.balance_in(sell_cur):
        bot.send_message(user.id, MSGS[user.lang]["NotEnough"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, create_order2, sell_cur, but_cur)
        return
    bot.send_message(user.id, MSGS[user.lang]["EnterMinBuy"])
    bot.register_next_step_handler(message, create_order3, sell_cur, but_cur, amount)


def create_order3(message, sell_cur, buy_cur, sell_amount):
    user = db.get_user(message.from_user.id)
    amount = message.text
    if amount == MSGS[user.lang]["Back"]:
        p2p_exchange4(user, sell_cur, buy_cur)
        return
    try:
        amount = Decimal(amount.replace(",", "."))
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, create_order3, sell_cur, buy_cur, sell_amount)
        return
    db.create_order(sell_cur, buy_cur, user.id, sell_amount, amount)
    bot.send_message(user.id, MSGS[user.lang]["OrderCreated"])
    p2p_exchange4(user, sell_cur, buy_cur)


def orders_paginator(user, sell_cur, buy_cur, start=0, end=9):
    orders = db.get_orders(sell_cur, buy_cur, user.id)
    if not orders:
        bot.send_message(user.id, MSGS[user.lang]["NoOrders"])
        p2p_exchange4(user, sell_cur, buy_cur)
        return
    pages = math.ceil(len(orders) / 9)
    page = int(start / 9) + 1
    message = bot.send_message(user.id, MSGS[user.lang]["OrdersView"].format(page, pages),
                               reply_markup=paginator_keyboard(user.lang, orders[start:end], page != 1, page != pages))
    cb.register_callback(message, orders_paginator2, sell_cur, buy_cur, start, end)


def orders_paginator2(call, data, sell_cur, buy_cur, start, end):
    user = db.get_user(call)
    if "prev" in data or "next" in data:
        if "prev" in data:
            end = start
            start = start - 9
        else:
            start = end
            end = end + 9
        orders_paginator(user, sell_cur, buy_cur, start, end)
        return
    else:
        order_id = data["order_id"]
        p2p_exchange6(user, order_id)
        message = bot.send_message(user.id, MSGS[user.lang]["OfferForOrder"].format(db.get_order(order_id).min_buy),
                                   reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, p2p_exchange6, order_id)


def p2p_exchange6(message, order_id):
    user = db.get_user(message.from_user.id)
    amount = message.text
    order = db.get_order(order_id)
    if amount == MSGS[user.lang]["Back"]:
        p2p_exchange4(user, order.sell_currency, order.buy_currency)
        return
    try:
        amount = Decimal(amount.replace(",", "."))
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, p2p_exchange6, order_id)
        return

    if amount > order.buy_min:
        bot.send_message(user.id, MSGS[user.lang]["ToSmallAmount"].format(order.buy_min, order.buy_currency),
                         reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, p2p_exchange6, order_id)
        return
    message = bot.send_message(user.id, order.format(user.lang), reply_markup=get_confirm_keyboard(user))
    cb.register_callback(message, p2p_exchange7, order_id, amount)


def p2p_exchange7(call, data, order_id, amount):
    user = db.get_user(call.from_user.id)

    if not data["confirm"]:
        order = db.get_order(order_id)
        sell_cur = order.sell_currency
        buy_cur = order.buy_currency
        p2p_exchange4(user, sell_cur, buy_cur)
        return
    order = db.get_order(order_id)
    bot.send_message(user.id, MSGS[user.lang]["CPNotified"], reply_markup=menu_keyboard(user))
    message = bot.send_message(order.user_id,
                               MSGS[order.user.lang]["OrderAccepted"].format(order.format(order.user.lang, False),
                                                                             user.username, amount,
                                                                             order.buy_currency),
                               reply_markup=get_confirm_keyboard(order.user))
    cb.register_callback(message, p2p_exchange8, order_id, user.id, amount)


def p2p_exchange8(call, data, order_id, user_id, buy_amount):
    c_user = db.get_user(call.from_user.id)
    if not data["confirm"]:
        return

    order = db.get_order(order_id)
    op = db.create_linked_operations("EscrowExchange", order.user_id, user_id, order.sell_currency, order.sell_amount,
                                     order.buy_currency, buy_amount)
    db.freeze_order(order_id, False)
    db.delete_order(order_id)
    db.freeze_operation(op.id)

    chat = cr_utils.get_chat()
    if not chat:
        message = bot.send_message(WALLET_CHAT_ID,
                                   "Закончились свободные чаты для ескроу, просьба создать новый, сделать бота админом и прислать"
                                   " id сюда.")
        bot.register_next_step_handler(message, get_new_escrow_chat, op.id, message.from_user.id)
        return
    escrow_exchange8(op.id, chat)


def paginator_keyboard(lang, orders, prev, next):
    k = types.InlineKeyboardMarkup()
    for order in orders:
        k.row(
            types.InlineKeyboardButton(text=order.format(lang, status=False),
                                       callback_data=json.dumps({"order_id": order.id}))
        )
    btns = []
    if prev:
        btns.append(types.InlineKeyboardButton(text="⬅️", callback_data=json.dumps({"prev": ""})))
    else:
        btns.append(types.InlineKeyboardButton(text=" ", callback_data=json.dumps({"placeholder": ""})))
    if next:
        btns.append(types.InlineKeyboardButton(text="➡️", callback_data=json.dumps({"next": ""})))
    else:
        btns.append(types.InlineKeyboardButton(text=" ", callback_data=json.dumps({"placeholder": ""})))

    return k


def p2p_exchange_keyboard(user):
    k = types.InlineKeyboardMarkup()
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["SeeOrders"], callback_data=json.dumps({"SeeOrders": ""})),
        types.InlineKeyboardButton(text=MSGS[user.lang]["CreateOrder"], callback_data=json.dumps({"CreateOrder": ""})),
    )
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["SeeOwnOrders"], callback_data=json.dumps({"SeeOrders": ""}))
    )
    return k


def escrow_exchange(user):
    if not user.balance:
        bot.send_message(user.id, MSGS[user.lang]["NoBalance"])
        return
    message = bot.send_message(user.id, MSGS[user.lang]["EnterUsername"], reply_markup=back_keyboard(user))
    bot.register_next_step_handler(message, escrow_exchange1)


def escrow_exchange1(message):
    user = db.get_user(message.from_user.id)
    username = message.text.replace("@", "").lower()
    if message.text == MSGS[user.lang]["Back"]:
        main_menu(user)
        return
    try:
        contr_user = db.get_user(username=username)
    except exc.NoResultFound:
        bot.send_message(user.id, MSGS[user.lang]["NoSuchUser"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, escrow_exchange1)
        return
    user = db.get_user(message.from_user.id)
    currencies = [balance_obj.currency for balance_obj in user.balance]
    message = select_currency(user, currencies, "Sell")
    cb.register_callback(message, escrow_exchange2, username)


def escrow_exchange2(call, data, username):
    sell_cur = data["currency"]
    user = db.get_user(call.from_user.id)
    bot.send_message(user.id, MSGS[user.lang]["CurrencyChosen"].format(sell_cur))
    msg = MSGS[user.lang]["CurrentBalance"].format(user.balance_in(sell_cur), sell_cur)
    msg += "\n" + MSGS[user.lang]["EnterSellSum"]
    message = bot.send_message(user.id, msg, reply_markup=back_keyboard(user))
    bot.register_next_step_handler(message, escrow_exchange3, sell_cur, username)


def escrow_exchange3(message, sell_cur, username):
    user = db.get_user(message.from_user.id)
    amount = message.text
    if amount == MSGS[user.lang]["Back"]:
        main_menu(user)
        return
    try:
        amount = Decimal(amount.replace(",", "."))
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, escrow_exchange3, sell_cur, username)
        return
    if amount > user.balance_in(sell_cur):
        bot.send_message(user.id, MSGS[user.lang]["NotEnough"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, escrow_exchange3, sell_cur, username)
        return
    sell_amount = amount
    currencies = CRYPTO_CURRENCIES
    if sell_cur not in FIAT_CURRENCIES:
        currencies.append(user.fiat)
    message = select_currency(user, currencies, "Buy")
    cb.register_callback(message, escrow_exchange4, username, sell_cur, sell_amount)


def escrow_exchange4(call, data, username, sell_cur, sell_amount):
    buy_cur = data["currency"]
    user = db.get_user(call.from_user.id)
    bot.send_message(user.id, MSGS[user.lang]["CurrencyChosen"].format(buy_cur))
    msg = MSGS[user.lang]["OperationAmount"].format(MSGS[user.lang]["Buy"])
    message = bot.send_message(user.id, msg, reply_markup=back_keyboard(user))
    bot.register_next_step_handler(message, escrow_exchange5, username, sell_cur, sell_amount, buy_cur)


def escrow_exchange5(message, username, sell_cur, sell_amount, buy_cur):
    user = db.get_user(message.from_user.id)
    amount = message.text
    if amount == MSGS[user.lang]["Back"]:
        main_menu(user)
        return
    try:
        amount = Decimal(amount.replace(",", "."))
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, escrow_exchange5, sell_cur, sell_amount, buy_cur)
        return
    buy_amount = amount
    countr_user = db.get_user(username=username)
    operation = db.create_linked_operations("EscrowExchange", user.id, countr_user.id, sell_cur, sell_amount, buy_cur,
                                            buy_amount)
    db.freeze_operation(operation.id)
    operation = db.get_operation(operation.id)
    message = bot.send_message(user.id, operation.format(), reply_markup=get_confirm_keyboard(user))
    cb.register_callback(message, escrow_exchange6, operation.id, countr_user)


def escrow_exchange6(call, data, operation_id, countr_user):
    user = db.get_user(call.from_user.id)
    if not data["confirm"]:
        bot.send_message(user.id, MSGS[user.lang]["OperationCancelled"])
        main_menu(user)
        return
    bot.send_message(user.id, MSGS[user.lang]["CPNotified"], reply_markup=menu_keyboard(user))
    operation = db.get_operation(operation_id)
    msg = MSGS[user.lang]["CPNotification"].format(user.username)
    msg += "\n" + MSGS[user.lang]["EscrowDescription"].format(user.username,
                                                              operation.format(user=countr_user, short=True))
    message = bot.send_message(countr_user.id, msg, operation,
                               reply_markup=countr_user_notification_keygboard(user))
    cb.register_callback(message, escrow_exchange7, operation.id, user.id)


def escrow_exchange7(call, data, operation_id, user_id):
    countr_user = db.get_user(call.from_user.id)
    if not data["Accept"]:
        bot.send_message(countr_user.id, MSGS[countr_user.lang]["OperationCancelled"])
        bot.send_message(user_id,
                         MSGS[db.get_user(user_id).lang]["OperationRejected"].format(db.get_operation(operation_id)))
        db.freeze_operation(operation_id, False)
        db.delete_operation(operation_id)

        return

    chat = cr_utils.get_chat()
    if not chat:
        message = bot.send_message(WALLET_CHAT_ID,
                                   "Закончились свободные чаты для ескроу, просьба создать новый, сделать бота админом и прислать"
                                   " id сюда.")
        bot.register_next_step_handler(message, get_new_escrow_chat, operation_id, message.from_user.id)
        return
    escrow_exchange8(operation_id, chat)


chats = {}


def escrow_exchange8(operation_id, chat_id):
    operation = db.get_operation(operation_id)
    user = operation.user
    link = bot.create_chat_invite_link(chat_id).invite_link
    bot.send_message(user.id, MSGS[user.lang]["Accepted"].format(operation.format(short=True)) + "\n" + MSGS[user.lang][
        "Invite"].format(link))
    c_user = operation.linked_operation.user
    bot.send_message(c_user.id, MSGS[c_user.lang][
        "Invite"].format(link))
    msg = MSGS[user.lang]["EscrowDescription"].format(user.username, operation.format(user=user, short=True))
    msg += "\n" + MSGS[user.lang]["EscrowInstructions"].format(user.username, c_user.username)
    notify_admin_escrow(link, operation_id)
    message = bot.send_message(chat_id, msg)
    self_id = message.from_user.id
    chats[chat_id] = msg

    bot.register_next_step_handler(message, escrow_wait_for_commands, operation_id, chat_id, user.id, self_id)


def notify_admin_escrow(link, operation_id):
    operation = db.get_operation(operation_id)
    user = operation.user
    c_user = operation.linked_operation.user
    msg = f"Escrow exchange: @{user.username} | @{c_user.username}\n" \
          f"{operation.format(lang_='en', short=True, status=False)}\nЧат с сторонами - {link}"
    bot.send_message(WALLET_CHAT_ID, msg)


def escrow_wait_for_commands(message, operation_id, chat_id, seller_id, self_id):
    if message.from_user.id == self_id:
        bot.register_next_step_handler(message, escrow_wait_for_commands, operation_id, chat_id, seller_id, self_id)
    if not message.text:
        bot.register_next_step_handler(message, escrow_wait_for_commands, operation_id, chat_id, seller_id, self_id)
        return
    if "/cancel" in message.text:
        close_escrow(operation_id, chat_id, False)
        return
    elif "/confirm" in message.text and message.from_user.id == seller_id:
        close_escrow(operation_id, chat_id)
    else:
        bot.register_next_step_handler(message, escrow_wait_for_commands, operation_id, chat_id, seller_id, self_id)


def rate_user(user, c_user):
    message = bot.send_message(user.id, MSGS[user.lang]["EscrowFinished"].format(c_user.username),
                               reply_markup=rate_keyboard())
    cb.register_callback(message, register_rate, c_user)


def register_rate(call, data, c_user):
    rate_ = data["rate"]
    user = db.get_user(call.from_user.id)
    bot.send_message(user.id, MSGS[user.lang]["Thanks"], reply_markup=menu_keyboard(user))
    db.update_user(user.id, exchanges=user.exchanges + 1, sum_rate=user.sum_rate + rate_)


def rate_keyboard():
    k = types.InlineKeyboardMarkup()
    k.row(*[types.InlineKeyboardButton(text=i, callback_data=json.dumps({"rate": i})) for i in range(1, 6)])
    k.row(*[types.InlineKeyboardButton(text=i, callback_data=json.dumps({"rate": i})) for i in range(6, 11)])
    return k


def close_escrow(operation_id, chat_id, confirm=True):
    op = db.get_operation(operation_id)
    user = op.user
    c_user = op.linked_operation.user
    if confirm:
        db.update_operation(operation_id, confirm=True)
        rate_user(user, c_user)
        rate_user(c_user, user)
    else:
        db.freeze_operation(operation_id, False)
        db.delete_operation(operation_id)
    bot.kick_chat_member(chat_id, user.id)
    bot.kick_chat_member(chat_id, c_user.id)
    cr_utils.mark_as_free(chat_id)


def get_new_escrow_chat(message, operation_id, self_id):
    try:
        chat_id = int(message.text)
    except ValueError:
        bot.reply_to(message, "Ошибка форматирования, повторите")
        bot.register_next_step_handler(message, get_new_escrow_chat, operation_id)
    else:
        chat = bot.get_chat(chat_id)

        admins = bot.get_chat_administrators(chat_id)
        admins = [admin.user.id for admin in admins]
        if self_id in admins:
            bot.reply_to(message, "Успешно.")
            cr_utils.save_escrow_chats(chat_id)
            escrow_exchange8(operation_id, chat_id)
        else:
            bot.reply_to(message, f"Бот не является админом в {chat.first_name}, добавте и повторите.")
            bot.register_next_step_handler(message, get_new_escrow_chat, operation_id)
            return


def countr_user_notification_keygboard(user):
    k = types.InlineKeyboardMarkup()
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["Accept"], callback_data=json.dumps({"Accept": True})),
        types.InlineKeyboardButton(text=MSGS[user.lang]["Deny"], callback_data=json.dumps({"Accept": False})),
    )
    return k


def fast_exchange(user):
    if not user.balance:
        bot.send_message(user.id, MSGS[user.lang]["NoBalance"])
        return
    currencies = [balance_obj.currency for balance_obj in user.balance]
    message = select_currency(user, currencies, "Sell")
    cb.register_callback(message, fast_exchange2)


def fast_exchange2(call, data):
    sell_cur = data["currency"]
    user = db.get_user(call.from_user.id)
    if sell_cur in FIAT_CURRENCIES:
        currencies = CRYPTO_CURRENCIES
    else:
        currencies = [user.fiat] + CRYPTO_CURRENCIES
    bot.send_message(user.id, MSGS[user.lang]["CurrencyChosen"].format(sell_cur))
    message = select_currency(user, currencies, "Buy")
    cb.register_callback(message, fast_exchange3, sell_cur)


def fast_exchange3(call, data, sell_cur):
    buy_cur = data["currency"]
    user = db.get_user(call.from_user.id)
    if buy_cur in FIAT_CURRENCIES:
        rate_msg = MSGS[user.lang]["FastExchangeRate"].format(
            f"{sell_cur}/{buy_cur}: {cr_utils.rate(sell_cur, buy_cur, False)}")
    else:
        rate_msg = MSGS[user.lang]["FastExchangeRate"].format(
            f"{buy_cur}/{sell_cur}: {cr_utils.rate(buy_cur, sell_cur, True)}")
    rate_msg += "\n" + MSGS[user.lang]["CurrentBalance"].format(user.balance_in(sell_cur), sell_cur)
    rate_msg += "\n" + MSGS[user.lang]["EnterSellSum"]
    message = bot.send_message(user.id, rate_msg, reply_markup=back_keyboard(user))
    bot.register_next_step_handler(message, fast_exchange4, sell_cur, buy_cur)


def fast_exchange4(message, sell_cur, buy_cur):
    user = db.get_user(message.from_user.id)
    amount = message.text
    if amount == MSGS[user.lang]["Back"]:
        main_menu(user)
        return
    try:
        amount = Decimal(amount.replace(",", "."))
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"])
        bot.register_next_step_handler(message, fast_exchange4, sell_cur, buy_cur)
        return
    if amount > user.balance_in(sell_cur):
        bot.send_message(user.id, MSGS[user.lang]["NotEnough"])
        bot.register_next_step_handler(message, fast_exchange4, sell_cur, buy_cur)
        return
    sell_amount = amount
    buy_amount = amount / cr_utils.rate(buy_cur, sell_cur, buy_cur not in FIAT_CURRENCIES)

    message = bot.send_message(user.id, MSGS[user.lang]["ExchangeResult"].format(buy_amount, buy_cur),
                               reply_markup=get_confirm_keyboard(user))
    cb.register_callback(message, fast_exchange5, sell_cur, buy_cur, sell_amount, buy_amount)


def fast_exchange5(call, data, sell_cur, buy_cur, sell_amount, buy_amount):
    user = db.get_user(call.from_user.id)
    confirm = data["confirm"]
    if not confirm:
        main_menu(user)
        return

    op = db.create_linked_operations("FastExchange", user.id, sell_cur=sell_cur, sell_amount=sell_amount,
                                     buy_cur=buy_cur,
                                     buy_amount=buy_amount)
    bot.send_message(user.id, MSGS[user.lang]["OperationProceed"].format(op.id), reply_markup=menu_keyboard(user))
    notify_admin(op.id, WALLET_CHAT_ID)


def operations_menu_keyboard(user):
    k = types.InlineKeyboardMarkup()
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["FastExchange"],
                                   callback_data=json.dumps({"FastExchange": ""})),
        types.InlineKeyboardButton(text=MSGS[user.lang]["EscrowExchange"],
                                   callback_data=json.dumps({"EscrowExchange": ""})),
    )
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["P2P"],
                                   callback_data=json.dumps({"P2P": ""})),
    )
    return k


# wallet menu
def wallet_menu(user):
    message = bot.send_message(user.id, MSGS[user.lang]["WalletMenu"], reply_markup=wallet_menu_keyboard(user),
                     parse_mode="HTML")
    cb.register_callback(message, wallet_menu2)


def wallet_menu_keyboard(user):
    k = types.InlineKeyboardMarkup()
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["Deposit"], callback_data=json.dumps({"deposit": ""})),
        types.InlineKeyboardButton(text=MSGS[user.lang]["Withdraw"], callback_data=json.dumps({"withdraw": ""})),
    )
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["Balance"], callback_data=json.dumps({"balance": ""})),
    )
    return k


def wallet_menu2(call, data):
    user = db.get_user(call.from_user.id)
    if "balance" in data:
        balance(user)
    elif "withdraw" in data:
        withdraw(user)
    elif "deposit" in data:
        deposit(user)


def balance(user):
    bot.send_message(user.id, get_balance_msg(user))


def withdraw(user):
    if not user.balance:
        bot.send_message(user.id, MSGS[user.lang]["NoBalance"])
        return
    currencies = [balance_obj.currency for balance_obj in user.balance]
    message = select_currency(user, currencies, "Withdraw")
    cb.register_callback(message, withdraw2)


def withdraw2(call, data):
    user = db.get_user(call.from_user.id)
    currency = data["currency"]
    msg = MSGS[user.lang]["CurrentBalance"].format(str(user.balance_in(currency)), currency) + "\n" + MSGS[user.lang][
        "OperationAmount"].format(MSGS[user.lang]["Withdraw"].lower())
    bot.send_message(user.id, MSGS[user.lang]["CurrencyChosen"].format(currency))
    message = bot.send_message(user.id, msg, reply_markup=back_keyboard(user))
    bot.register_next_step_handler(message, withdraw3, currency)


def withdraw3(message, currency):
    user = db.get_user(message.from_user.id)
    amount = message.text
    if amount == MSGS[user.lang]["Back"]:
        return
    try:
        amount = Decimal(amount.replace(",", "."))
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"])
        bot.register_next_step_handler(message, withdraw3, currency)
        return
    if amount > user.balance_in(currency):
        bot.send_message(user.id, MSGS[user.lang]["NotEnough"])
        bot.register_next_step_handler(message, withdraw3, currency)
        return
    bot.send_message(user.id, MSGS[user.lang]["AddressToWithdraw"],
                     reply_markup=address_history_keyboard(user, currency))
    bot.register_next_step_handler(message, withdraw4, currency, amount)


def withdraw4(message, currency, amount):
    user = db.get_user(message.from_user.id)
    address = message.text
    if address == MSGS[user.lang]["Back"]:
        main_menu(user)
        return
    op = db.create_operation(user.id, "Withdraw", currency, amount, address)
    bot.send_message(user.id, MSGS[user.lang]["OperationProceed"].format(op.id), reply_markup=menu_keyboard(user))
    notify_admin(op.id, WALLET_CHAT_ID)


def notify_admin(operation_id, chat):
    operation = db.get_operation(operation_id)
    message = bot.send_message(chat, str(operation), reply_markup=admin_notification_keyboard())
    cb.register_callback(message, admin_confirm, operation)


def admin_notification_keyboard():
    k = types.InlineKeyboardMarkup()
    k.row(
        types.InlineKeyboardButton(text="Подтвердить", callback_data=json.dumps({"confirm": True})),
        types.InlineKeyboardButton(text="Отклонить", callback_data=json.dumps({"confirm": False})),
    )
    return k


def admin_confirm(call, data, operation):
    confirm = data["confirm"]
    db.update_operation(operation.id, confirm=confirm)
    bot.send_message(call.message.chat.id,
                     f"{str(operation)}\nСтатус: {('Отклонен', 'Подтвержден')[confirm]} модератором"
                     f" @{call.from_user.username}")
    user = operation.user
    bot.send_message(user.id,
                     MSGS[user.lang][("OperationRejected", "OperationConfirmed")[confirm]].format(operation.format()))


def address_history_keyboard(user, currency):
    history = [(op.address if op.currency == currency else None) for op in user.operations]
    history = list(set(history))
    try:
        history.pop(history.index(None))
    except ValueError:
        pass
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for address in history[:10]:
        k.row(address)
    k.row(MSGS[user.lang]["Back"])
    return k


def back_keyboard(user):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.row(MSGS[user.lang]["Back"])
    return k


def select_currency(user, currencies, type_):
    return bot.send_message(user.id, MSGS[user.lang]["OperationCurrency"].format(MSGS[user.lang][type_].lower()),
                            reply_markup=currencies_keyboard(currencies))


def deposit(user):
    currencies = [user.fiat] + CRYPTO_CURRENCIES
    message = select_currency(user, currencies, "Deposit")
    cb.register_callback(message, deposit2)


def deposit2(call, data):
    user = db.get_user(call.from_user.id)
    currency = data["currency"]
    bot.send_message(user.id, MSGS[user.lang]["CurrencyChosen"].format(currency))
    msg = MSGS[user.lang]["OperationAmount"].format(MSGS[user.lang]["Deposit"].lower())
    msg += f"\n{MSGS[user.lang]['MinDeposit'].format(f'{MIN_DEPOSIT[currency]:.{SYMBOLS[currency]}f}', currency)}"
    message = bot.send_message(user.id, msg,
                               reply_markup=back_keyboard(user))
    bot.register_next_step_handler(message, deposit3, currency)


def deposit3(message, currency):
    user = db.get_user(message.from_user.id)
    amount = message.text
    if amount == MSGS[user.lang]["Back"]:
        main_menu(user)
        return
    try:
        amount = Decimal(amount.replace(",", "."))
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"])
        bot.register_next_step_handler(message, deposit3, currency)
        return

    if amount < MIN_DEPOSIT[currency]:
        bot.send_message(user.id, MSGS[user.lang]["ToSmallAmount"].format(MIN_DEPOSIT[currency], currency))
        bot.register_next_step_handler(message, deposit3, currency)
        return
    op = db.create_operation(user.id, 'Deposit', currency, amount)
    msg = MSGS[user.lang]["AccountAddress"] + CURRENCIES_ADDRESSES[currency] + "\n\n"
    if op.amount != amount:
        msg += MSGS[user.lang]["CryptoDeposit"].format(op.amount) + "\n"
    msg += MSGS[user.lang]["TransferConfirmation"]
    message = bot.send_message(user.id, msg, reply_markup=get_confirm_keyboard(user))
    cb.register_callback(message, deposit4, op)


def get_confirm_keyboard(user):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["Confirm"],
                                   callback_data=json.dumps({"confirm": True})),
        types.InlineKeyboardButton(text=MSGS[user.lang]["Back"], callback_data=json.dumps({"confirm": False}))
    )
    return keyboard


def deposit4(call, data, operation):
    user = db.get_user(call.from_user.id)
    confirm = data["confirm"]
    if not confirm:
        db.delete_operation(operation.id)
        bot.send_message(user.id, MSGS[user.lang]["OperationCancelled"])
        return
    bot.send_message(user.id, MSGS[user.lang]["OperationProceed"].format(operation.id),
                     reply_markup=menu_keyboard(user))
    notify_admin(operation.id, WALLET_CHAT_ID)


# setting menu
def settings_menu(user):
    message = bot.send_message(user.id, MSGS[user.lang]["SettingsMenu"], reply_markup=settings_menu_keyboard(user),
                     parse_mode="HTML")
    cb.register_callback(message, settings_menu2)


def settings_menu2(call, data):
    user = db.get_user(call.from_user.id)
    if "lang" in data:
        select_language1(user, main_menu)
    elif "fiat" in data:
        select_fiat1(user)


def settings_menu_keyboard(user):
    k = types.InlineKeyboardMarkup()
    k.row(
        types.InlineKeyboardButton(MSGS[user.lang]["ChangeLanguage"], callback_data=json.dumps({"lang": ""})),
        types.InlineKeyboardButton(MSGS[user.lang]["ChangeFiat"], callback_data=json.dumps({"fiat": ""})),
    )
    return k


# support menu
def support_menu(user):
    message = bot.send_message(user.id, MSGS[user.lang]["SupportMenu"], reply_markup=support_menu_keyboard(user))
    cb.register_callback(message, support_menu2)


def support_menu2(call, data):
    user = db.get_user(call.from_user.id)
    if "fees" in data:
        bot.send_message(user.id, MSGS[user.lang]["FeesText"])
    elif 'rates' in data:
        bot.send_message(user.id, get_rates_msg(user))


def support_menu_keyboard(user):
    k = types.InlineKeyboardMarkup()
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["Ask"], url=MSGS[user.lang]["AskLink"]),
        types.InlineKeyboardButton(text=MSGS[user.lang]["JoinCommunity"], url=MSGS[user.lang]["CommunityLink"])
    )
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["Fees"], callback_data=json.dumps({"fees": ""})),
        types.InlineKeyboardButton(text=MSGS[user.lang]["Rates"], callback_data=json.dumps({"rates": ""}))
    )
    return k


# other
def get_rates_msg(user):
    msg = MSGS[user.lang]["Rates"] + ":\n"
    buy = MSGS[user.lang]["Buy"]
    sell = MSGS[user.lang]["Sell"]
    fiat = user.fiat
    msg += f"USDT / {fiat} - {buy}: {cr_utils.get_fiat_rate(fiat)[0]:.8f}, {sell}: {cr_utils.get_fiat_rate(fiat)[1]:.8f}\n" \
           f"BTC / {fiat} - {buy}: {cr_utils.crypt_to_fiat_rate(fiat, 'BTC', 1):.8f}, {sell}: {cr_utils.crypt_to_fiat_rate(fiat, 'BTC', 0):.8f}\n" \
           f"ETH / {fiat} - {buy}: {cr_utils.crypt_to_fiat_rate(fiat, 'ETH', 1):.8f}, {sell}: {cr_utils.crypt_to_fiat_rate(fiat, 'ETH', 0):.8f}\n" \
           f"BTC / USDT: {cr_utils.crypt_to_crypt_rate('BTC', 'USDT'):.8f}\n" \
           f"BTC / ETH: {cr_utils.crypt_to_crypt_rate('BTC', 'ETH'):.8f}\n" \
           f"ETH / USDT: {cr_utils.crypt_to_crypt_rate('ETH', 'USDT'):.8f}"
    return msg


def get_balance_msg(user):
    balance = user.balance
    if balance:
        msg = f"{MSGS[user.lang]['Balance']}:\n"
        for cur in balance:
            msg += f"{cur.amount:.{SYMBOLS[cur.currency]}f} {cur.currency}\n"
    else:
        msg = f"{MSGS[user.lang]['NoBalance']}"
    return msg


if __name__ == '__main__':
    bot.infinity_polling()
