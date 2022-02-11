import sys
import traceback
import asyncio
from threading import Thread
import json
import decimal
import math
import time
from decimal import Decimal
import logging

import requests
import telebot

from sqlalchemy import exc
from telebot import types

import database
from cfg import *
import cr_utils


class Callback:
    callback_funcs = {}
    inline_messages = {}
    sti = {}

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

    def delete_sti(self, uid):
        if uid in list(self.sti.keys()):
            if self.sti[uid]:
                try:
                    bot.delete_message(uid, self.sti[uid])
                except:
                    self.sti[uid] = None

    def send_sti(self, uid, path):
        self.sti[uid] = bot.send_sticker(uid, open(path, "rb")).id


db = database.Handler()
cb = Callback()
bot = telebot.TeleBot(BOT_TOKEN)
cr_utils.save_escrow_chats()
logging.basicConfig(format='%(asctime)s  ---  %(message)s \n', level=logging.WARNING, filename='log.txt')


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


@bot.message_handler(commands=["users"])
def users_admin(message):
    if message.chat.id != WALLET_CHAT_ID:
        return
    users = db.get_users()
    msg = ""
    for user in users:
        balances = user.balance
        msg += f"{user.first_name} - {('@' + user.username) if user.username else ''} ({user.id}): {'; '.join([str(bal.amount) + ' ' + bal.currency for bal in balances])}\n"
    bot.send_message(WALLET_CHAT_ID, msg)


@bot.message_handler(commands=["user"])
def user_admin(message):
    if message.chat.id != WALLET_CHAT_ID:
        return
    user_id = message.text.split(" ")[-1]
    try:
        if "@" in user_id:
            user = db.get_user(username=user_id.replace("@", ""))
        else:
            user = db.get_user(tg_id=int(user_id))
    except exc.NoResultFound:
        msg = "Пользователь не найден"
    except ValueError:
        msg = "Ошибка форматирования"
    else:
        msg = f"{user.first_name} - {('@' + user.username) if user.username else ''} ({user.id}): {'; '.join([str(bal.amount) + ' ' + bal.currency for bal in user.balance])}"
        rate_ = (user.sum_rate / user.exchanges if user.exchanges else 0)
        msg += f"\n{user.exchanges} завершенных обменов, средний рейтинг - {rate_:.1f}"
        msg += f"Язык - {user.lang}"
    bot.send_message(WALLET_CHAT_ID, msg)


@bot.message_handler(commands=["add_escrow_chat"])
def add_escrow(message):
    chat = bot.get_chat(message.chat.id)
    admins = bot.get_chat_administrators(message.chat.id)
    admins = [admin.user.id for admin in admins]
    bot_id = bot.send_message(chat.id, "Проверка...").from_user.id
    if bot_id in admins:
        bot.send_message(chat.id, "Чат успешно добавлен")
        cr_utils.save_escrow_chats(chat.id)
    else:
        bot.reply_to(message, f"Бот не является админом в {chat.first_name}, добавте и повторите.")


@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    data = json.loads(call.data)
    if "placeholder" in data:
        return
    cb.delete_sti(call.from_user.id)
    cb.run_callback(call, data)


# start, menu and some starting funcs

@bot.message_handler(commands=["start"])
def start(message):
    try:
        db.create_user(message.from_user.id, message.from_user.username, DEFAULT_LANGUAGE, message.from_user.first_name)
    except exc.IntegrityError:
        main_menu(db.get_user(message.from_user.id))
    else:
        user = db.get_user(message.from_user.id)
        select_language1(user, select_fiat1)
        log(f"{user.username} впервые воспользовался ботом")


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


last_sti = {}


def main_menu(user):
    cb.delete_old_inline(user.id)
    cb.send_sti(user.id, "stickers/welcome.tgs")
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
    cb.delete_sti(user.id)
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
    cb.send_sti(user.id, "stickers/exchange.tgs")
    message = bot.send_message(user.id, MSGS[user.lang]["OperationsMenu"], reply_markup=operations_menu_keyboard(user),
                               parse_mode="HTML")
    cb.register_callback(message, operations_menu2)


def operations_menu2(call, data):
    user = db.get_user(call.from_user.id)
    if "FastExchange" in data:
        fast_exchange(user)
    elif "EscrowExchange" in data:
        escrow_exchange_start(user)
    elif "P2P" in data:
        p2p_exchange(user)


def p2p_exchange(user):
    if not user.balance:
        bot.send_message(user.id, MSGS[user.lang]["NoBalance"])
        return
    currencies = [user.fiat] + CRYPTO_CURRENCIES
    message = bot.send_message(user.id, MSGS[user.lang]["SelectOrderSellCur"],
                               reply_markup=currencies_keyboard(currencies))
    cb.register_callback(message, p2p_exchange2)


def p2p_exchange2(call, data):
    sell_cur = data["currency"]
    user = db.get_user(call.from_user.id)
    if sell_cur in FIAT_CURRENCIES:
        currencies = list(CRYPTO_CURRENCIES)
    else:
        currencies = [user.fiat] + CRYPTO_CURRENCIES
    if sell_cur in currencies:
        currencies.pop(currencies.index(sell_cur))
    bot.send_message(user.id, MSGS[user.lang]["CurrencyChosen"].format(sell_cur))
    message = bot.send_message(user.id, MSGS[user.lang]["SelectOrderBuyCur"],
                               reply_markup=currencies_keyboard(currencies))
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
    user = db.get_user(call.from_user.id)
    if "back" in data:
        p2p_exchange4(user, sell_cur, buy_cur)
        return
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
        if amount <= 0:
            raise decimal.InvalidOperation
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, create_order2, sell_cur, but_cur)
        return
    if amount > user.balance_in(sell_cur):
        bot.send_message(user.id, MSGS[user.lang]["NotEnough"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, create_order2, sell_cur, but_cur)
        return
    bot.send_message(user.id, MSGS[user.lang]["MinTradeAmount"])
    bot.register_next_step_handler(message, create_order3, sell_cur, but_cur, amount)


def create_order3(message, sell_cur, buy_cur, sell_amount):
    user = db.get_user(message.from_user.id)
    amount = message.text
    if amount == MSGS[user.lang]["Back"]:
        p2p_exchange4(user, sell_cur, buy_cur)
        return
    try:
        amount = Decimal(amount.replace(",", "."))
        if amount <= 0:
            raise decimal.InvalidOperation
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, create_order3, sell_cur, buy_cur, sell_amount)
        return
    min_trade_amount = amount
    rate_ = str(cr_utils.rate(sell_cur, buy_cur, True))
    bot.send_message(user.id, MSGS[user.lang]["YourRate"].format(sell_cur, buy_cur, rate_))
    bot.register_next_step_handler(message, create_order4, sell_cur, buy_cur, sell_amount, min_trade_amount)


def create_order4(message, sell_cur, buy_cur, sell_amount, min_trade_amount):
    user = db.get_user(message.from_user.id)
    amount = message.text
    if amount == MSGS[user.lang]["Back"]:
        p2p_exchange4(user, sell_cur, buy_cur)
        return
    try:
        amount = Decimal(amount.replace(",", "."))
        if amount <= 0:
            raise decimal.InvalidOperation
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, create_order4, sell_cur, buy_cur, sell_amount, min_trade_amount)
        return
    rate = amount
    db.create_order(user.id, sell_cur, buy_cur, min_trade_amount, sell_amount, rate)
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
    user = db.get_user(call.from_user.id)
    if "back" in data:
        p2p_exchange4(user, sell_cur, buy_cur)
        return
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
        msg = MSGS[user.lang]["OfferForOrder"].format(f"{order.min_trade_amount:.{SYMBOLS[order.sell_currency]}f}",
                                                      f"{order.sell_amount:.{SYMBOLS[order.sell_currency]}f}",
                                                      order.sell_currency)
        message = bot.send_message(user.id, msg,
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
        if amount <= 0:
            raise decimal.InvalidOperation
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, p2p_exchange6, order_id)
        return

    if amount < order.min_trade_amount:
        bot.send_message(user.id, MSGS[user.lang]["ToSmallAmount"].format(order.min_trade_amount, order.buy_currency),
                         reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, p2p_exchange6, order_id)
        return

    if amount > order.sell_amount:
        bot.send_message(user.id, MSGS[user.lang]["ToBigAmount"].format(order.sell_amount, order.buy_currency),
                         reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, p2p_exchange6, order_id)
        return

    if amount * order.rate > db.get_user(user.id).balance_in(order.buy_currency):
        bot.send_message(user.id, MSGS[user.lang]["NotEnough"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, p2p_exchange6, order_id)
        return

    message = bot.send_message(user.id,
                               order.format(user.lang) + "\n" + MSGS[user.lang][
                                   "YourOffer"].format(amount,
                                                       order.sell_currency),
                               reply_markup=get_confirm_keyboard(user))
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
                               MSGS[order.user.lang]["CPNotificationOrder"].format(
                                   order.format(order.user.lang, status=False, to_me=True),
                                   user.username, amount,
                                   order.buy_currency),
                               reply_markup=get_confirm_keyboard(order.user))
    cb.register_callback(message, p2p_exchange8, order_id, user.id, amount)


def p2p_exchange8(call, data, order_id, user_id, sell_amount):
    c_user = db.get_user(call.from_user.id)
    if not data["confirm"]:
        return
    order = db.get_order(order_id)
    buy_amount = sell_amount * order.rate
    user = db.get_user(user_id)
    if buy_amount > user.balance_in(order.buy_currency):
        bot.send_message(c_user.id, MSGS[c_user.lang]["CounterpartyNotEnough"].format(user.username))
        return
    op = db.create_linked_operations("EscrowExchange", order.user_id, user_id, order.sell_currency, sell_amount,
                                     order.buy_currency, buy_amount)
    db.freeze_order(order_id, False)
    db.update_order(order_id, sell_amount=order.sell_amount - sell_amount)
    db.freeze_order(order_id, True)
    db.freeze_operation(op.id)
    db.freeze_operation(op.linked_operation_id)
    op = db.get_operation(op.id)
    log("Завершена операция\n" + op.format(counterparty=True, lang="en", op_name="P2P Exchange"))
    close_escrow(op.id, None, True, False)


def paginator_keyboard(lang, orders, prev, next):
    k = types.InlineKeyboardMarkup()
    for order in orders:
        k.row(
            types.InlineKeyboardButton(text=order.format(lang=lang, status=False),
                                       callback_data=json.dumps({"order_id": order.id}))
        )
    btns = []
    if prev:
        btns.append(types.InlineKeyboardButton(text="⬅️", callback_data=json.dumps({"prev": ""})))
    else:
        btns.append(types.InlineKeyboardButton(text=" ", callback_data=json.dumps({"placeholder": ""})))
    btns.append(types.InlineKeyboardButton(text=MSGS[lang]["Back"], callback_data=json.dumps({"back": ""})))
    if next:
        btns.append(types.InlineKeyboardButton(text="➡️", callback_data=json.dumps({"next": ""})))
    else:
        btns.append(types.InlineKeyboardButton(text=" ", callback_data=json.dumps({"placeholder": ""})))
    k.row(*btns)
    return k


def p2p_exchange_keyboard(user):
    k = types.InlineKeyboardMarkup()
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["SeeOrders"], callback_data=json.dumps({"SeeOrders": ""})),
        types.InlineKeyboardButton(text=MSGS[user.lang]["CreateOrder"], callback_data=json.dumps({"CreateOrder": ""})),
    )
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["SeeOwnOrders"], callback_data=json.dumps({"SeeOwnOrders": ""}))
    )
    return k


def escrow_exchange_start(user):
    message = bot.send_message(user.id, MSGS[user.lang]["EscrowExplanation"], reply_markup=escrow_types_keyboard(user))
    cb.register_callback(message, escrow_exchange)


def escrow_types_keyboard(user):
    k = types.InlineKeyboardMarkup()
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["ChatEscrow"], callback_data=json.dumps({"_": "chat_escrow"})),
        types.InlineKeyboardButton(text=MSGS[user.lang]["NoChatEscrow"],
                                   callback_data=json.dumps({"_": "no_chat_escrow"}))
    )
    k.row(
        types.InlineKeyboardButton(text=MSGS[user.lang]["DeleteEscrow"],
                                   callback_data=json.dumps({"delete_escrow": ""}))
    )
    return k


def escrow_exchange(call, data):
    user = db.get_user(call.from_user.id)
    if "delete_escrow" in data:
        delete_escrow_paginator(user)
        return
    type_ = data["_"]
    if type_ == "no_chat_escrow" and not user.balance:
        bot.send_message(user.id, MSGS[user.lang]["NoBalance"])
        return
    message = bot.send_message(user.id, MSGS[user.lang]["EnterUsername"], reply_markup=back_keyboard(user))
    bot.register_next_step_handler(message, escrow_exchange1, type_)


def delete_escrow_paginator(user, start=0, end=9):
    operations = db.get_escrows(user.id)
    if not operations:
        bot.send_message(user.id, MSGS[user.lang]["NoOffers"])
        escrow_exchange_start(user)
        return
    pages = math.ceil(len(operations) / 9)
    page = int(start / 9) + 1
    message = bot.send_message(user.id, MSGS[user.lang]["OrdersView"].format(page, pages),
                               reply_markup=paginator_keyboard(user.lang, operations[start:end], page != 1,
                                                               page != pages))
    cb.register_callback(message, delete_escrow_paginator2, start, end)


def delete_escrow_paginator2(call, data, start, end):
    user = db.get_user(call.from_user.id)
    if "back" in data:
        escrow_exchange_start(user)
        return
    if "prev" in data or "next" in data:
        if "prev" in data:
            end = start
            start = start - 9
        else:
            start = end
            end = end + 9
        delete_escrow_paginator(user, start, end)
        return
    op_id = data["order_id"]
    operation = db.get_operation(op_id)
    message = bot.send_message(user.id,
                               MSGS[user.lang]["DeleteOrder"].format(operation.format()),
                               reply_markup=get_confirm_keyboard(user))
    cb.register_callback(message, remove_operation, op_id)


def remove_operation(call, data, op_id):
    user = db.get_user(call.from_user.id)
    if not data["confirm"]:
        escrow_exchange_start(user)
        return
    op = db.get_operation(op_id)
    if op.frozen:
        db.freeze_operation(op_id, False)
    if op.notification_id:
        bot.delete_message(op.linked_operation.user_id, op.notification_id)
    db.delete_operation(op_id)
    bot.send_message(user.id, MSGS[user.lang]["OrderDeleted"])
    escrow_exchange_start(user)


def escrow_exchange1(message, type_):
    user = db.get_user(message.from_user.id)
    username = message.text.replace("@", "").lower()
    if message.text == MSGS[user.lang]["Back"]:
        main_menu(user)
        return
    try:
        contr_user = db.get_user(username=username)
        if username == message.from_user.username:
            raise exc.NoResultFound
    except exc.NoResultFound:
        bot.send_message(user.id, MSGS[user.lang]["NoSuchUser"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, escrow_exchange1, type_)
        return
    user = db.get_user(message.from_user.id)
    currencies = [balance_obj.currency for balance_obj in user.balance]
    message = select_currency(user, currencies, "Sell")
    cb.register_callback(message, escrow_exchange2, username, type_)


def escrow_exchange2(call, data, username, type_):
    sell_cur = data["currency"]
    user = db.get_user(call.from_user.id)
    bot.send_message(user.id, MSGS[user.lang]["CurrencyChosen"].format(sell_cur))
    if type_ == "no_chat_escrow" or sell_cur in CRYPTO_CURRENCIES:
        msg = MSGS[user.lang]["CurrentBalance"].format(user.balance_in(sell_cur), sell_cur)
    else:
        msg = ""
    msg += "\n" + MSGS[user.lang]["EnterSellSum"]
    message = bot.send_message(user.id, msg, reply_markup=back_keyboard(user))
    bot.register_next_step_handler(message, escrow_exchange3, sell_cur, username, type_)


def escrow_exchange3(message, sell_cur, username, type_):
    user = db.get_user(message.from_user.id)
    amount = message.text
    if amount == MSGS[user.lang]["Back"]:
        main_menu(user)
        return
    try:
        amount = Decimal(amount.replace(",", "."))
        if amount <= 0:
            raise decimal.InvalidOperation
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, escrow_exchange3, sell_cur, username, type_)
        return
    if amount > user.balance_in(sell_cur) and (type_ == "no_chat_escrow" or sell_cur in CRYPTO_CURRENCIES):
        bot.send_message(user.id, MSGS[user.lang]["NotEnough"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, escrow_exchange3, sell_cur, username, type_)
        return
    sell_amount = amount
    currencies = list(CRYPTO_CURRENCIES)
    if sell_cur not in FIAT_CURRENCIES:
        currencies.append(user.fiat)
    message = select_currency(user, currencies, "Buy")
    cb.register_callback(message, escrow_exchange4, username, sell_cur, sell_amount, type_)


def escrow_exchange4(call, data, username, sell_cur, sell_amount, type_):
    buy_cur = data["currency"]
    user = db.get_user(call.from_user.id)
    bot.send_message(user.id, MSGS[user.lang]["CurrencyChosen"].format(buy_cur))
    msg = MSGS[user.lang]["OperationAmount"].format(MSGS[user.lang]["Buy"])
    message = bot.send_message(user.id, msg, reply_markup=back_keyboard(user))
    bot.register_next_step_handler(message, escrow_exchange5, username, sell_cur, sell_amount, buy_cur, type_)


def escrow_exchange5(message, username, sell_cur, sell_amount, buy_cur, type_):
    user = db.get_user(message.from_user.id)
    amount = message.text
    if amount == MSGS[user.lang]["Back"]:
        main_menu(user)
        return
    try:
        amount = Decimal(amount.replace(",", "."))
        if amount <= 0:
            raise decimal.InvalidOperation
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"], reply_markup=back_keyboard(user))
        bot.register_next_step_handler(message, escrow_exchange5, sell_cur, sell_amount, buy_cur, type_)
        return
    buy_amount = amount
    countr_user = db.get_user(username=username)
    operation = db.create_linked_operations("EscrowExchange", user.id, countr_user.id, sell_cur, sell_amount, buy_cur,
                                            buy_amount)
    if sell_cur not in FIAT_CURRENCIES or type_ == "no_chat_escrow":
        db.freeze_operation(operation.id)
    operation = db.get_operation(operation.id)
    message = bot.send_message(user.id, operation.format(counterparty=True), reply_markup=get_confirm_keyboard(user))
    cb.register_callback(message, escrow_exchange6, operation.id, countr_user, type_)


def escrow_exchange6(call, data, operation_id, countr_user, type_):
    user = db.get_user(call.from_user.id)
    if not data["confirm"]:
        db.freeze_operation(operation_id, False)
        bot.send_message(user.id, MSGS[user.lang]["OperationCancelled"])
        main_menu(user)
        return
    bot.send_message(user.id, MSGS[user.lang]["CPNotified"], reply_markup=menu_keyboard(user))
    operation = db.get_operation(operation_id)
    if type_ == "chat_escrow":
        msg = MSGS[user.lang]["CPNotificationChat"].format(user.username,
                                                           MSGS[user.lang]["EscrowDescription"].format(user.username,
                                                                                                       operation.format(
                                                                                                           user=countr_user,
                                                                                                           rate=True)))
    else:
        msg = MSGS[user.lang]["CPNotificationNoChat"].format(user.username,
                                                             MSGS[user.lang]["EscrowDescription"].format(user.username,
                                                                                                         operation.format(
                                                                                                             user=countr_user,
                                                                                                             rate=True)))

    message = bot.send_message(countr_user.id, msg, operation,
                               reply_markup=countr_user_notification_keygboard(user))
    db.update_operation(operation.id, notification_id=message.id)
    cb.register_callback(message, escrow_exchange7, operation.id, user.id, type_)


def escrow_exchange7(call, data, operation_id, user_id, type_):
    countr_user = db.get_user(call.from_user.id)
    if not data["Accept"]:
        bot.send_message(countr_user.id, MSGS[countr_user.lang]["OperationCancelled"])
        bot.send_message(user_id,
                         MSGS[db.get_user(user_id).lang]["OperationRejected"].format(db.get_operation(operation_id)))
        db.freeze_operation(operation_id, False)
        db.delete_operation(operation_id)

        return

    op = db.get_operation(operation_id)
    if type_ == "no_chat_escrow":
        if op.linked_operation.amount > db.get_user(call.from_user.id).balance_in(op.linked_operation.currency):
            bot.send_message(countr_user.id, MSGS[countr_user.lang]["NotEnough"])
            return
        db.freeze_operation(db.get_operation(operation_id).linked_operation_id)
        log("Завершена операция\n" + op.format(counterparty=True, lang="en", op_name="Escrow Exchange (without chat)"))
        close_escrow(operation_id, None, True)
    else:
        if op.currency in FIAT_CURRENCIES:
            db.freeze_operation(op.linked_operation.id)
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
    bot.send_message(user.id,
                     MSGS[user.lang]["Accepted"].format(operation.format(counterparty=True)) + "\n" + MSGS[user.lang][
                         "Invite"].format(link))
    c_user = operation.linked_operation.user
    bot.send_message(c_user.id, MSGS[c_user.lang][
        "Invite"].format(link))
    msg = MSGS[user.lang]["EscrowDescription"].format(user.username, operation.format(user=user))
    if operation.currency in CRYPTO_CURRENCIES:
        seller = user
        buyer = c_user
    else:
        seller = c_user
        buyer = user

    msg += "\n" + MSGS[user.lang]["EscrowInstructions"].format(seller.username, buyer.username)
    notify_admin_escrow(link, operation_id)
    message = bot.send_message(chat_id, msg)
    self_id = message.from_user.id

    bot.register_next_step_handler(message, escrow_wait_for_commands, operation_id, chat_id, seller.id, self_id)
    target = lambda: scan_for_noobs(chat_id, msg)
    t = Thread(target=target)
    t.start()


def scan_for_noobs(chat_id, msg):
    c = bot.get_chat_members_count(chat_id)
    while True:
        time.sleep(15)
        nc = bot.get_chat_members_count(chat_id)
        if nc > c:
            c = nc
            bot.send_message(chat_id, msg)
            if c >= 4:
                return


def notify_admin_escrow(link, operation_id):
    operation = db.get_operation(operation_id)
    user = operation.user
    c_user = operation.linked_operation.user
    msg = f"Escrow exchange: @{user.username} | @{c_user.username}\n" \
          f"{operation.format(lang='en', counterparty=True)}\nЧат с сторонами - {link}"
    bot.send_message(WALLET_CHAT_ID, msg)


def escrow_wait_for_commands(message, operation_id, chat_id, seller_id, self_id):
    if message.from_user.id == self_id:
        bot.register_next_step_handler(message, escrow_wait_for_commands, operation_id, chat_id, seller_id, self_id)
    if not message.text:
        bot.register_next_step_handler(message, escrow_wait_for_commands, operation_id, chat_id, seller_id, self_id)
        return
    if "/cancel" in message.text:
        close_escrow(operation_id, chat_id, False, chat=True)
        return
    elif "/confirm" in message.text and message.from_user.id == seller_id:
        log("Завершена операция\n" + db.get_operation(operation_id).format(counterparty=True, lang="en",
                                                                           op_name="Escrow Exchange"))
        close_escrow(operation_id, chat_id, chat=True)
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


def close_escrow(operation_id, chat_id=None, confirm=True, chat=False):
    op = db.get_operation(operation_id)
    user = op.user
    c_user = op.linked_operation.user
    if chat:
        bot.kick_chat_member(chat_id, user.id)
        bot.kick_chat_member(chat_id, c_user.id)
        cr_utils.mark_as_free(chat_id)
    if confirm:
        if chat:  # опция обмена с чатом, подтверждаем первую не фиатную операцию
            if op.currency not in FIAT_CURRENCIES:
                db.update_operation(op.id, confirm=True)
            else:
                db.update_operation(op.linked_operation_id, confirm=True)
        else:  # опция обмена без чата, подтверждаем обе операции
            db.update_operation(op.id, confirm=True)
            db.update_operation(op.linked_operation_id, confirm=True)
        rate_user(user, c_user)
        rate_user(c_user, user)
    else:
        if chat:  # опция обмена с чатом, размораживаем первую не фиатную операцию
            if op.currency not in FIAT_CURRENCIES:
                db.freeze_operation(op.id, False)
            else:
                db.freeze_operation(op.linked_operation_id, False)
        else:  # опция обмена без чата, размораживаем обе операции
            db.freeze_operation(op.id, False)
            db.freeze_operation(op.linked_operation_id, False)
        db.delete_operation(operation_id)


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
        if amount <= 0:
            raise decimal.InvalidOperation
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
    str_amount = f"{buy_amount:.{SYMBOLS[buy_cur]}f}"
    message = bot.send_message(user.id, MSGS[user.lang]["ExchangeResult"].format(str_amount, buy_cur),
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
    cb.send_sti(user.id, "stickers/balance.tgs")
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
        if amount <= 0:
            raise decimal.InvalidOperation
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
    log("Операция поступила в обработку\n" + str(operation))
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
        if amount <= 0:
            raise decimal.InvalidOperation
    except decimal.InvalidOperation:
        bot.send_message(user.id, MSGS[user.lang]["FormatError"])
        bot.register_next_step_handler(message, deposit3, currency)
        return

    if amount < MIN_DEPOSIT[currency]:
        bot.send_message(user.id, MSGS[user.lang]["ToSmallAmount"].format(MIN_DEPOSIT[currency], currency))
        bot.register_next_step_handler(message, deposit3, currency)
        return
    op = db.create_operation(user.id, 'Deposit', currency, amount)
    if currency in CRYPTO_CURRENCIES:
        msg = MSGS[user.lang]["AccountAddress"] + "\n" + \
              MSGS[user.lang]["CryptoDepositAddress"].format(currency, *CURRENCIES_ADDRESSES[currency]) + "\n\n"
    else:
        msg = MSGS[user.lang]["AccountAddress"] + CURRENCIES_ADDRESSES[currency] + "\n\n"
    if currency in CRYPTO_CURRENCIES:
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
    cb.send_sti(user.id, "stickers/settings.tgs")
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


async def polling_coro():
    print("Бот запущен.")
    while True:
        try:
            loop = asyncio.get_running_loop()
            polling = loop.run_in_executor(None, bot.polling)
            await polling
        except Exception:
            msg, type_, tb = sys.exc_info()
            tb = '\n'.join(traceback.format_tb(tb))
            logging.warning(f"{msg}, {type_}\n {tb}")


async def depo_check_coroutine():
    print("Цикл проверки депозита запущен.")
    while True:
        await asyncio.sleep(60 * 5)
        depo_check()


def depo_check():
    uids = cr_utils.get_new_confirmed_uids()
    for uid in uids:
        try:
            op = db.get_operation(uid=uid)
        except exc.NoResultFound:
            print("Поступила незарегестрирированная в системе крипта")
        else:
            db.update_operation(op.id, confirm=True)
            bot.send_message(WALLET_CHAT_ID, str(op) + "\nСтатус: была подтверждена автоматически")
            user = op.user
            bot.send_message(user.id,
                             MSGS[user.lang]["OperationConfirmed"].format(
                                 op.format()))


def main():
    loop = asyncio.get_event_loop()

    loop.create_task(depo_check_coroutine())
    loop.create_task(polling_coro())
    loop.run_forever()


def log(msg):
    bot.send_message(LOG_CHAT_ID, msg)


if __name__ == '__main__':
    main()
