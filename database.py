import datetime
import json
from decimal import Decimal

import sqlalchemy
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, desc, ForeignKey, or_, exc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, backref

from cfg import *


class SQLiteNumeric(sqlalchemy.types.TypeDecorator):
    impl = sqlalchemy.types.String

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(sqlalchemy.types.VARCHAR(200))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)


Base = declarative_base()


class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True)
    username = Column(String)
    first_name = Column(String)
    lang = Column(String)
    fiat = Column(String)
    exchanges = Column(Integer)
    sum_rate = Column(Integer)

    def __init__(self, tg_id, username, lang, name):
        self.id = tg_id
        self.username = username.lower()
        self.lang = lang
        self.first_name = name
        self.exchanges = 0
        self.sum_rate = 0

    def get_average_rate(self):
        return f"{(self.sum_rate / self.exchanges):.1f}"

    def balance_in(self, currency):
        for balance in self.balance:
            if balance.currency == currency:
                return balance.amount
        return 0


class Operation(Base):
    __tablename__ = "operation"
    id = Column(Integer, primary_key=True)
    type_ = Column(String)
    currency = Column(String)
    amount = Column(SQLiteNumeric)
    user_id = Column(Integer, ForeignKey("user.id"))
    user = relationship("User", backref="operations")
    confirmed = Column(Boolean)
    pseudo_uid = Column(String)
    date = Column(DateTime)
    address = Column(String)
    linked_operation_id = Column(Integer)
    linked_operation = None
    frozen = Column(Boolean)
    notification_id = Column(Integer)

    def __init__(self, user_id, type_, currency, amount, pseudo_uid=None, address=None):
        self.user_id = user_id
        self.type_ = type_
        self.currency = currency
        self.amount = amount
        self.pseudo_uid = pseudo_uid
        self.confirmed = False
        self.date = datetime.datetime.now()
        self.address = address
        self.frozen = False
        self.notification_id = None

    def link(self, session):
        if self.linked_operation_id:
            self.linked_operation = session.query(Operation).filter(Operation.id == self.linked_operation_id).one()

    def __repr__(self):
        if self.type_ == "EscrowSell":
            badge_type = "EscrowExchange"
        else:
            badge_type = self.type_
        r = f"{badge_type} #{self.id} от @{self.user.username}: {self.amount:.{SYMBOLS[self.currency]}f} {self.currency}\n"
        if self.linked_operation:
            r += f"за {self.linked_operation.amount:.{SYMBOLS[self.linked_operation.currency]}f} {self.linked_operation.currency}"
        if self.address:
            r += f"Реквезиты: {self.address}"
        if (self.currency in CRYPTO_CURRENCIES and self.type_ == "Deposit") \
                or self.type_ == "FastSell" and self.currency in CRYPTO_CURRENCIES and self.linked_operation.currency in CRYPTO_CURRENCIES:
            r += "Эта операция будет совершена автоматически"

        return r

    def format(self, user=None, counterparty=False, lang=None, rate=False, op_name=None, **kwargs):
        if not user:
            user = self.user

        if not lang:
            lang = user.lang

        if self.type_ in ["Deposit", "Withdraw"]:
            return f"{self.amount:.{SYMBOLS[self.currency]}f} {self.currency}  {MSGS[lang][self.type_]} #{self.id}"
        else:
            if self.type_ == "FastSell":
                badge_type = "FastExchange"
            elif self.type_ == "EscrowSell":
                badge_type = "EscrowExchange"
            else:
                badge_type = self.type_
            if not op_name is None:
                if op_name:
                    msg = op_name
                else:
                    msg = f"{badge_type}:\n"
            else:
                msg = ""
            msg += f"{MSGS[lang]['Buy']} {self.linked_operation.amount:.{SYMBOLS[self.linked_operation.currency]}f} {self.linked_operation.currency} |" \
                  f"{MSGS[lang]['Sell']} {self.amount:.{SYMBOLS[self.currency]}f} {self.currency}"
            if rate:
                if self.user.exchanges:
                    msg += f"\n{MSGS[lang]['UserRate'].format(self.user.username, self.user.exchanges, self.user.get_average_rate())}"
                else:
                    msg += f"\n{MSGS[lang]['FirstExchange']}"

            if self.type_ == "EscrowSell" and counterparty:
                msg += f"\n{MSGS[lang]['Counterparty']}: @{self.linked_operation.user.username}"
            return msg


class Balance(Base):
    __tablename__ = "balance"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"))
    user = relationship("User", backref="balance")
    currency = Column(String)
    amount = Column(SQLiteNumeric)

    def __init__(self, user_id, currency, amount: Decimal):
        self.user_id = user_id
        self.currency = currency
        self.amount = amount


class Order(Base):
    __tablename__ = "order"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"))
    user = relationship("User", backref="orders")

    sell_currency = Column(String)
    sell_amount = Column(SQLiteNumeric)

    buy_currency = Column(String)
    buy_min = Column(SQLiteNumeric)

    def __init__(self, user_id, sell_currency, buy_currency, buy_min, sell_amount):
        self.user_id = user_id
        self.sell_currency = sell_currency
        self.buy_currency = buy_currency
        self.buy_min = buy_min
        self.sell_amount = sell_amount

    def format(self, lang="en", user=None, status=True):
        if user:
            self.user = user
        r = MSGS[lang]["OrderFormat"].format(self.user.username, self.sell_amount, self.sell_currency, self.buy_min,
                                             self.buy_currency)
        if status:
            if self.user.exchanges:
                r += f"\n{MSGS[lang]['UserRate'].format(self.user.username, self.user.exchanges, self.user.get_average_rate())}"
            else:
                r += f"\n{MSGS[lang]['FirstExchange']}"
        return r


class Handler:

    def __init__(self, database_path=None, base=Base):
        if database_path:
            self.database_path = database_path
        engine = sqlalchemy.create_engine(DB_STRING + '?check_same_thread=False')
        base.metadata.create_all(engine)
        self.sessionmaker = sessionmaker(bind=engine, expire_on_commit=False)
        print("База данных подключена.")

    def create_user(self, tg_id, username, lang, first_name):
        session = self.sessionmaker()
        user = User(tg_id, username, lang, first_name)
        session.add(user)
        session.commit()

    def get_user(self, tg_id=None, username=None):
        session = self.sessionmaker()
        if tg_id:
            user = session.query(User).filter(User.id == tg_id).one()
        else:
            user = session.query(User).filter(User.username == username).one()
        # session.close()
        return user

    def update_user(self, tg_id, **kwargs):
        session = self.sessionmaker()
        user = session.query(User).filter(User.id == tg_id).one()
        for attr_name in kwargs:
            value = kwargs[attr_name]
            setattr(user, attr_name, value)
        session.commit()

    def create_operation(self, user_id, type_, currency, pre_amount, address=None):
        if type_ == "Deposit" and currency in CRYPTO_CURRENCIES:
            deadline = datetime.datetime.now() - datetime.timedelta(days=7)
            session = self.sessionmaker()
            ops = session.query(Operation).filter(Operation.date < deadline).all()
            for op in ops:
                op.pseudo_uid = None
            session.commit()

        session = self.sessionmaker()

        if type_ == "Deposit" and currency in CRYPTO_CURRENCIES:
            uid = get_uid(pre_amount, currency)
            while session.query(Operation).filter(Operation.confirmed == False).filter(
                    Operation.pseudo_uid == uid).first():
                pre_amount += Decimal(1) / Decimal(10 ** UID_DIVIDER[currency])
                uid = get_uid(pre_amount, currency)
            amount = pre_amount
        else:
            amount = pre_amount
            uid = None

        operation = Operation(user_id, type_, currency, amount, uid, address)
        session.add(operation)
        session.commit()
        return operation

    def create_linked_operations(self, type_, user1_id, user2_id=None, sell_cur=None, sell_amount=None, buy_cur=None,
                                 buy_amount=None):
        session = self.sessionmaker()

        if type_ == "FastExchange":
            op_sell = Operation(user1_id, "FastSell", sell_cur, sell_amount)
            session.add(op_sell)
            op_buy = Operation(user1_id, "FastBuy", buy_cur, buy_amount)
            session.add(op_buy)
            session.commit()
            op_sell.linked_operation_id = op_buy.id
            op_sell.link(session)
            session.commit()
            return op_sell
        elif type_ == "EscrowExchange":
            op_sell = Operation(user1_id, "EscrowSell", sell_cur, sell_amount)
            session.add(op_sell)
            op_buy = Operation(user2_id, "EscrowBuy", buy_cur, buy_amount)
            session.add(op_buy)
            session.commit()
            op_sell.linked_operation_id = op_buy.id
            op_sell.link(session)
            op_buy.linked_operation_id = op_sell.id
            session.commit()
            return op_sell

    def freeze_operation(self, operation_id, freeze=True):
        session = self.sessionmaker()
        operation = session.query(Operation).filter(Operation.id == operation_id).one()
        bal = session.query(Balance).filter(Balance.user_id == operation.user_id).filter(
            Balance.currency == operation.currency).one()
        if freeze:
            bal.amount = bal.amount - operation.amount
        else:
            bal.amount = bal.amount + operation.amount
        operation.frozen = freeze
        session.commit()

    def update_operation(self, id_=None, uid=None, confirm=False, **kwargs):
        session = self.sessionmaker()
        if id_:
            op = session.query(Operation).filter(Operation.id == id_).one()
        else:
            op = session.query(Operation).filter(Operation.pseudo_uid == uid).filter(Operation.confirmed == False).one()
        op.link(session)
        if confirm:
            self.execute_operation(op, session)
            op.confirmed = True
            if op.linked_operation:
                if op.type_ in ["FastSell"]:
                    self.execute_operation(op.linked_operation, session)
                op.linked_operation.confirmed = True

        for attr_name in kwargs:
            value = kwargs[attr_name]
            setattr(op, attr_name, value)
        session.commit()
        return op.id

    def get_operation(self, id_=None, uid=None):
        session = self.sessionmaker()
        if id_:
            op = session.query(Operation).filter(Operation.id == id_).one()
        else:
            op = session.query(Operation).filter(Operation.pseudo_uid == uid).filter(Operation.confirmed == False).one()
        # session.close()
        op.link(session)
        return op

    def delete_operation(self, id_):
        session = self.sessionmaker()
        op = session.query(Operation).filter(Operation.id == id_).one()
        op.link(session)
        if op.linked_operation:
            session.delete(op.linked_operation)
        session.delete(op)
        session.commit()

    def test(self):
        session = self.sessionmaker()
        user = session.query(User).filter(User.username == "bobaK00").one()
        print(user)

    def execute_operation(self, operation, session):
        if operation.type_ in ["Deposit", "FastBuy"]:
            try:
                bal = session.query(Balance).filter(Balance.user_id == operation.user_id).filter(
                    Balance.currency == operation.currency).one()
            except exc.NoResultFound:
                bal = Balance(operation.user_id, operation.currency, operation.amount)
                session.add(bal)

        elif operation.type_ in ["Withdraw", "FastSell"]:
            bal = session.query(Balance).filter(Balance.user_id == operation.user_id).filter(
                Balance.currency == operation.currency).one()
            bal.amount = bal.amount - operation.amount

        elif operation.type_ in ["EscrowSell", "EscrowBuy"]:
            l_op = session.query(Operation).filter(Operation.id == operation.linked_operation_id).one()
            try:
                bal = session.query(Balance).filter(Balance.user_id == l_op.user_id).filter(
                    Balance.currency == operation.currency).one()
                bal.amount = bal.amount + operation.amount
            except exc.NoResultFound:
                bal = Balance(l_op.user_id, operation.currency, operation.amount)
                session.add(bal)
        session.commit()

    def create_order(self, sell_cur, buy_cur, user_id, sell_sum, buy_min):
        session = self.sessionmaker()
        order = Order(user_id, sell_cur, buy_cur, buy_min, sell_sum)
        session.add(order)
        session.commit()
        self.freeze_order(order.id)

    def freeze_order(self, order_id, freeze=True):
        session = self.sessionmaker()
        order = session.query(Order).filter(Order.id == order_id).one()
        bal = session.query(Balance).filter(Balance.user_id == order.user_id).filter(
            Balance.currency == order.sell_currency).one()
        if freeze:
            bal.amount = bal.amount - order.sell_amount
        else:
            bal.amount = bal.amount + order.sell_amount
        session.commit()

    def get_orders(self, sell_cur, buy_cur, user_id, self_=False):
        session = self.sessionmaker()
        if self_:
            orders = session.query(Order).filter(Order.user_id == user_id).all()
        else:
            orders = session.query(Order).filter(Order.sell_currency == sell_cur).filter(
                Order.buy_currency == buy_cur).filter(Order.user_id != user_id).all()
            orders += session.query(Order).filter(Order.sell_currency == buy_cur).filter(
                Order.buy_currency == sell_cur).filter(Order.user_id != user_id).all()
        return orders

    def get_order(self, order_id):
        session = self.sessionmaker()
        return session.query(Order).filter(Order.id == order_id).one()

    def delete_order(self, order_id):
        session = self.sessionmaker()
        session.delete(session.query(Order).filter(Order.id == order_id).one())
        session.commit()

    def count_system_balances(self):
        session = self.sessionmaker()
        bals = SYMBOLS
        for key in bals:
            bals[key] = 0
        for balance in session.query(Balance).all():
            bals[balance.currency] += balance.amount
        session.close()
        return bals

    def get_users(self):
        session = self.sessionmaker()
        return session.query(User).all()

    def get_escrows(self, user_id):
        session = self.sessionmaker()
        operations = session.query(Operation).filter(
            Operation.user_id == user_id).filter(Operation.type_ == "EscrowSell").filter(
            Operation.confirmed == 0).all()
        for operation in operations:
            operation.link(session)
        return operations


def get_uid(amount, currency):
    amount = f"{amount:.8f}"
    amount = amount[amount.find(".") + 1:]
    divider = UID_DIVIDER[currency]
    uid = int(amount[divider - 2:divider])
    return uid


if __name__ == '__main__':
    h = Handler()
    h.test()
