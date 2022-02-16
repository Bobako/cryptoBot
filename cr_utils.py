import json
import requests
from decimal import Decimal

from binance.client import Client

from cfg import *


def update_fiat_rates(fiat, buy, sell):
    """Update USDT/fiat rate"""
    if fiat == "USD":
        fiat = "USD (Ecuador)"
    with open(USDT_FIAT_RATES_JSON, "r") as file:
        rates = json.load(file)
    buy = buy.replace(",", ".")
    sell = sell.replace(",", ".")
    rates[fiat] = [buy, sell]
    with open(USDT_FIAT_RATES_JSON, "w") as file:
        json.dump(rates, file)


def get_fiat_rate(fiat):
    """Get USDT/fiat rate. Returns [buy, sell]"""
    with open(USDT_FIAT_RATES_JSON, "r") as file:
        rates = json.load(file)
    buy, sell = rates[fiat]
    buy = Decimal(buy)
    sell = Decimal(sell)
    return buy, sell


def update_crypto_rates():
    rates = {}
    for cr in ["BTC", "ETH"]:
        rates[cr] = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={cr}USDT").json()["price"]
    with open(CRYPTO_RATES_JSON, "w") as file:
        json.dump(rates, file)


def crypt_to_fiat_rate(fiat, crypt, buy) -> Decimal:
    if crypt != "USDT":
        with open(CRYPTO_RATES_JSON, "r") as file:
            rates = json.load(file)
        crypt_to_usdt = Decimal(rates[crypt])
    else:
        crypt_to_usdt = Decimal(1)

    usdt_to_fiat = Decimal(get_fiat_rate(fiat)[int(not buy)])

    rate = crypt_to_usdt * usdt_to_fiat
    return rate


def crypt_to_usdt_rate(crypt) -> Decimal:
    if crypt == "USDT":
        return Decimal(1)
    with open(CRYPTO_RATES_JSON, "r") as file:
        rates = json.load(file)
    return Decimal(rates[crypt])


def crypt_to_crypt_rate(cr1, cr2) -> Decimal:
    cr1_to_usdt = crypt_to_usdt_rate(cr1)
    cr2_to_usdt = crypt_to_usdt_rate(cr2)
    return cr1_to_usdt / cr2_to_usdt


def rate(cur1, cur2, buy):
    if cur1 in CRYPTO_CURRENCIES and cur2 in CRYPTO_CURRENCIES:
        return crypt_to_crypt_rate(cur1, cur2)
    elif cur1 in CRYPTO_CURRENCIES and cur2 in FIAT_CURRENCIES:
        return crypt_to_fiat_rate(cur2, cur1, buy)
    elif cur1 in FIAT_CURRENCIES and cur2 in CRYPTO_CURRENCIES:
        return Decimal(1) / crypt_to_fiat_rate(cur1, cur2, not buy)


def save_escrow_chats(new_chat=None):
    try:
        with open(CHATS_JSON, "r") as file:
            chats = json.load(file)
    except Exception:
        chats = {}

    if new_chat:
        chats[new_chat] = True

    with open(CHATS_JSON, "w") as file:
        json.dump(chats, file)


def get_chat():
    with open(CHATS_JSON, "r") as file:
        chats = json.load(file)
    for chat, free in zip(chats.keys(), chats.values()):
        if free:
            chats[chat] = False
            with open(CHATS_JSON, "w") as file:
                json.dump(chats, file)
            return int(chat)

    return None


def mark_as_free(chat):
    with open(CHATS_JSON, "r") as file:
        chats = json.load(file)
    chats[str(chat)] = True
    with open(CHATS_JSON, "w") as file:
        json.dump(chats, file)


def get_bin_balance():
    client = Client(API_KEY, SECRET_KEY)
    res = client.get_account()
    bals = res["balances"]
    balances = UID_DIVIDER
    for balance in balances:
        balances[balance] = Decimal(0)
    for balance in bals:
        try:
            balances[balance["asset"]] += Decimal(balance["Free"])
        except KeyError:
            pass
    return balances


def get_dep_addresses(dict_):
    client = Client(API_KEY, SECRET_KEY)
    btc = client.get_deposit_address("BTC", "BTC")["address"]
    eth = client.get_deposit_address("ETH", "ETH")["address"]
    usd = client.get_deposit_address("USDT", "TRX")["address"]
    dict_["BTC"] = [btc, "BTC"]
    dict_["ETH"] = [eth, "ETH"]
    dict_["USDT"] = [usd, "TRX"]
    return dict_


def get_new_confirmed_uids():
    client = Client(API_KEY, SECRET_KEY)
    hist = client.get_deposit_history()
    i = 0
    with open("dep_history.json", "r") as file:
        old_hist = json.load(file)
    new_confirmed_uids = []
    while True:
        if i >= len(hist):
            break
        if hist[i] in old_hist:
            break
        dep = hist[i]
        i += 1
        coin = dep["coin"]
        amount = dep["amount"]
        uid = get_uid(amount, coin)
        new_confirmed_uids.append(uid)
    with open("dep_history.json", "w") as file:
        json.dump(hist, file)
    return new_confirmed_uids


def get_uid(amount, currency):
    amount = str(amount)
    amount = amount[amount.find(".") + 1:]
    divider = UID_DIVIDER[currency]
    uid = int(amount[divider - 2:divider])
    return uid


if __name__ == '__main__':
    print(get_new_confirmed_uids())
