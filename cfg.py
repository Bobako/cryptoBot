# DATABASE CONFIG
DB_STRING = "sqlite:///database.db"

# BOT CONFIG
BOT_TOKEN = "2143260005:AAGpdMdfNFZ81gX-9SZ6-y0Cu6AcDpfxlCE"
ADMINS = ["bobak00"]

"ID чата, в котором разрешено менять обменные курсы."
"Администратор может узнать ID командой /id в соответствующем чатe"
RATE_CHANGE_CHAT_ID = -770031154

"ID чата, в котором разрешено подтверждать операции."
WALLET_CHAT_ID = -770031154

"ID чата, в который будет присылаться информация о операциях"
LOG_CHAT_ID = -770031154


# LANGUAGE CONFIGS
DEFAULT_LANGUAGE = 'en'

FIAT_CURRENCIES = ["BRL", "COP", "GHS", "NGN", "USD (Ecuador)", "VES", "XOF"]
CRYPTO_CURRENCIES = ["BTC", "ETH", "USDT"]

# BINANCE
API_KEY = "IPKB37BJdgQVcgko9eTZLx4uabVq7dpmutZZ1Aq7pqJa91JbB1jRuvJL1QRLNV6C"
SECRET_KEY = "Cq73RUtcPf584tCUmohmOIHuQIjQJcewe5CmoamJYS47xZjlxk07YZjWfZTfkny7"

# CURRENCIES
MIN_DEPOSIT = {
    "BTC": 0.000001,
    "USDT": 1,
    "ETH": 0.0001,
    "BRL": 1,
    "COP": 1,
    "GHS": 1,
    "NGN": 1,
    "USD (Ecuador)": 1,
    "VES": 1,
    "XOF": 1,
}

UID_DIVIDER = {
    "BTC": 8,
    "USDT": 2,
    "ETH": 6,
}

SYMBOLS = {
    "BTC": 8,
    "USDT": 2,
    "ETH": 6,
    "BRL": 2,
    "COP": 2,
    "GHS": 2,
    "NGN": 2,
    "USD (Ecuador)": 2,
    "VES": 2,
    "XOF": 2,
}

# OTHER
USDT_FIAT_RATES_JSON = "usdt_fiat_rates.json"
CRYPTO_RATES_JSON = "crypto_rates.json"
CHATS_JSON = "CHATS_JSON"
LANGS_TABLE_FILENAME = "langs.xlsx"

import lang_engine

MSGS = lang_engine.load_langs_table_from_google(LANGS_TABLE_FILENAME)
CURRENCIES_ADDRESSES = lang_engine.load_reqs()

from cr_utils import get_dep_addresses

CURRENCIES_ADDRESSES = get_dep_addresses(CURRENCIES_ADDRESSES)
