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

    def __init__(self, user_id, type_, currency, amount, pseudo_uid=None, address=None):
        self.user_id = user_id
        self.type_ = type_
        self.currency = currency
        self.amount = amount
        self.pseudo_uid = pseudo_uid
        self.confirmed = False
        self.date = datetime.datetime.now()
        self.address = address

    def link(self, session):
        if self.linked_operation_id:
            self.linked_operation = session.query(Operation).filter(Operation.id == self.linked_operation_id).one()

    def __repr__(self):
        r = f"{self.type_} #{self.id} от @{self.user.username} на {self.amount:.{SYMBOLS[self.currency]}f} {self.currency}\n"
        if self.linked_operation:
            r += f"за {self.linked_operation.amount:.{SYMBOLS[self.linked_operation.currency]}f} {self.linked_operation.currency}"
        if self.address:
            r += f"Реквезиты: {self.address}"
        if (self.currency in CRYPTO_CURRENCIES and self.type_ == "Deposit") \
                or self.type_ == "FastSell" and self.currency in CRYPTO_CURRENCIES and self.linked_operation.currency in CRYPTO_CURRENCIES:
            r += "Эта операция будет совершена автоматически"  # TODO

        return r

    def format(self, user=None, short=False, lang_=None, status=True):
        if not user:
            user = self.user
        lang = user.lang
        if lang_:
            lang = lang_
        if self.type_ in ["Deposit", "Withdraw"]:
            return f"{self.amount:.{SYMBOLS[self.currency]}f} {self.currency}  {MSGS[lang][self.type_]} #{self.id}"
        else:
            if self.type_ == "FastSell":
                badge_type = "FastExchange"
            elif self.type_ == "EscrowSell":
                badge_type = "EscrowExchange"

            else:
                badge_type = self.type_
            if short:
                msg = f"{MSGS[lang]['Buy']} {self.linked_operation.amount:.{SYMBOLS[self.linked_operation.currency]}f} {self.linked_operation.currency} |" \
                      f"{MSGS[lang]['Sell']} {self.amount:.{SYMBOLS[self.currency]}f} {self.currency}"
                if self.user.exchanges:
                    msg += f"\n{MSGS[lang]['UserRate'].format(self.user.username, self.user.exchanges, self.user.get_average_rate())}"
                else:
                    msg += f"\n{MSGS[lang]['FirstExchange']}"
            else:
                msg = f"{MSGS[lang]['Buy']} {self.linked_operation.amount:.{SYMBOLS[self.linked_operation.currency]}f} {self.linked_operation.currency} |" \
                      f"{MSGS[lang]['Sell']} {self.amount:.{SYMBOLS[self.currency]}f} {self.currency}  {MSGS[lang][badge_type]} #{self.id}"
                if self.type_ == "EscrowSell" and status:
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

    def format(self, lang, status=True):
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
            ops = session.query(Operation).filter(Operation.pseudo_uid != None).filter(
                Operation.confirmed == False).all()
            uids = [op.pseudo_uid for op in ops]
            for uid in range(99, 0, -1):
                if 100 - uid not in uids:
                    break
            uid = 100 - uid
            sub_uid = Decimal(uid) / Decimal(UID_DIVIDER[currency])

            amount = Decimal(pre_amount) + sub_uid
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
            session.commit()
            return op_sell

    def freeze_operation(self, operation_id, freeze=True):
        session = self.sessionmaker()
        operation = session.query(Operation).filter(Operation.id == operation_id).one()
        if operation.type_ == "EscrowSell":
            bal = session.query(Balance).filter(Balance.user_id == operation.user_id).filter(
                Balance.currency == operation.currency).one()
            if freeze:
                bal.amount = bal.amount - operation.amount
            else:
                bal.amount = bal.amount + operation.amount
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

        elif operation.type_ in ["EscrowSell"]:
            l_op = operation.linked_operation
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

    def get_orders(self, sell_cur, buy_cur, user_id, self_ = False):
        session = self.sessionmaker()
        if self_:
            orders = session.query(Order).filter(Order.user_id == user_id).all()
        else:
            orders = session.query(Order).filter(Order.sell_currency == sell_cur).filter(
                Order.buy_currency == buy_cur).filter(Order.user_id != user_id).all()
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

if __name__ == '__main__':
    h = Handler()
    h.test()
