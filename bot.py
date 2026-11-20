import asyncio
import csv
import io
import os
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from dotenv import load_dotenv
from leads import router as leads_router, init_leads

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN', '')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))
DB_PATH = os.getenv('DB_PATH', 'magrok.db')
if not TOKEN or not OWNER_ID:
    raise RuntimeError('Fill BOT_TOKEN and OWNER_ID in .env')

dp = Dispatcher()
dp.include_router(leads_router)
legacy_router = Router()
dp.include_router(legacy_router)
MENU = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text='🎯 Лиды'), KeyboardButton(text='👥 Клиенты')],
    [KeyboardButton(text='🥩 Товары'), KeyboardButton(text='📦 Заказы')],
    [KeyboardButton(text='💳 Оплаты и долги')],
    [KeyboardButton(text='📊 Отчёт'), KeyboardButton(text='📤 Экспорт')],
    [KeyboardButton(text='❓ Помощь')],
], resize_keyboard=True, input_field_placeholder='Выбери раздел или введи команду')
SHORTCUTS = {
    '👥 Клиенты':'/clients', '🥩 Товары':'/products',
    '📦 Заказы':'/orders', '💳 Оплаты и долги':'/debts',
    '📊 Отчёт':'/report', '📤 Экспорт':'/export', '❓ Помощь':'/help',
}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT '', note TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, purchase_kop INTEGER NOT NULL CHECK(purchase_kop>=0), markup_pct TEXT NOT NULL DEFAULT '10');
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), product_id INTEGER NOT NULL REFERENCES products(id), qty_g INTEGER NOT NULL CHECK(qty_g>0), sale_kop_per_kg INTEGER NOT NULL CHECK(sale_kop_per_kg>=0), purchase_kop_per_kg INTEGER NOT NULL CHECK(purchase_kop_per_kg>=0), status TEXT NOT NULL DEFAULT 'new', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), amount_kop INTEGER NOT NULL CHECK(amount_kop>0), created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')

def money(s):
    try:
        d = Decimal(s.strip().replace(' ', '').replace(',', '.'))
        if not d.is_finite() or d < 0:
            raise ValueError
        return int((d * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        raise ValueError('Неверная сумма')

def qty_grams(s):
    try:
        d = Decimal(s.strip().replace(',', '.'))
        if not d.is_finite() or d <= 0:
            raise ValueError
        grams = d * 1000
        if grams != grams.to_integral_value():
            raise ValueError
        return int(grams)
    except (InvalidOperation, ValueError):
        raise ValueError('Вес укажите в кг, точность до 1 грамма')

def fmt(kop):
    return f'{Decimal(kop)/100:,.2f}'.replace(',', ' ').replace('.', ',')

def value(qty_g, kop_per_kg):
    return int((Decimal(qty_g) * Decimal(kop_per_kg) / 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

def sale_price(purchase_kop, markup):
    return int((Decimal(purchase_kop) * (Decimal('1') + Decimal(markup)/100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

@legacy_router.message()
async def handle(m: Message):
    if not m.from_user or m.from_user.id != OWNER_ID:
        await m.answer('Доступ закрыт.')
        return
    t = SHORTCUTS.get((m.text or '').strip(), (m.text or '').strip())
    if not t:
        await m.answer('Используй текстовые команды. /help')
        return
    cmd, _, args = t.partition(' ')
    cmd = cmd.lower().split('@')[0]
    try:
        if cmd in ('/start', '/help'):
            await m.answer('МАГРОК CRM — личный учёт\n\n'
                '/leads — лиды, источники и задачи (через кнопки)\n'
                '/client Название | Телефон | Примечание — добавить клиента\n'
                '/clients — список клиентов\n'
                '/product Название | Закупка с НДС за кг | Наценка % — товар\n'
                '/products — список товаров\n'
                '/order ID_клиента | ID_товара | Кг — новый заказ\n'
                '/orders — последние заказы\n'
                '/status ID_заказа | new/packed/shipped/done/cancelled — статус\n'
                '/pay ID_клиента | Сумма — отметить оплату\n'
                '/debts — долги клиентов\n'
                '/report — итоги\n'
                '/export — CSV-файлы для Excel\n\n'
                'Все суммы в грн; цены товаров и продаж вводятся с НДС. '
                'Заказы хранят зафиксированную цену на момент создания.', reply_markup=MENU)
        elif cmd == '/client':
            p = [x.strip() for x in args.split('|')]
            if not p[0]: raise ValueError('Пример: /client Магазин Весна | +380... | Днепр')
            with db() as c:
                cur = c.execute('INSERT INTO clients(name,phone,note) VALUES(?,?,?)', (p[0], p[1] if len(p)>1 else '', p[2] if len(p)>2 else ''))
                cid = cur.lastrowid
            await m.answer(f'Клиент #{cid}: {p[0]} добавлен.')
        elif cmd == '/clients':
            with db() as c: rows = c.execute('SELECT * FROM clients ORDER BY id DESC LIMIT 40').fetchall()
            await m.answer('\n'.join(f"#{r['id']} {r['name']} {r['phone']}" for r in rows) or 'Клиентов пока нет.')
        elif cmd == '/product':
            p = [x.strip() for x in args.split('|')]
            if len(p)!=3 or not p[0]: raise ValueError('Пример: /product Салямі | 200,00 | 10')
            purchase = money(p[1]); markup = Decimal(p[2].replace(',', '.'))
            if not markup.is_finite() or not 0 <= markup <= 1000: raise ValueError('Наценка от 0 до 1000%')
            with db() as c:
                c.execute('INSERT INTO products(name,purchase_kop,markup_pct) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET purchase_kop=excluded.purchase_kop, markup_pct=excluded.markup_pct', (p[0],purchase,str(markup)))
                r=c.execute('SELECT id FROM products WHERE name=?',(p[0],)).fetchone()
            await m.answer(f"Товар #{r['id']} {p[0]}: закупка {fmt(purchase)}, продажа {fmt(sale_price(purchase,markup))} грн/кг")
        elif cmd == '/products':
            with db() as c: rows=c.execute('SELECT * FROM products ORDER BY id LIMIT 60').fetchall()
            await m.answer('\n'.join(f"#{r['id']} {r['name']}: {fmt(sale_price(r['purchase_kop'],r['markup_pct']))} грн/кг" for r in rows) or 'Товаров пока нет.')
        elif cmd == '/order':
            p=[x.strip() for x in args.split('|')]
            if len(p)!=3: raise ValueError('Пример: /order 1 | 2 | 12,5')
            cid,pid=int(p[0]),int(p[1]); q=qty_grams(p[2])
            with db() as c:
                if not c.execute('SELECT 1 FROM clients WHERE id=?',(cid,)).fetchone(): raise ValueError('Клиент не найден')
                prod=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
                if not prod: raise ValueError('Товар не найден')
                price=sale_price(prod['purchase_kop'],prod['markup_pct'])
                cur=c.execute('INSERT INTO orders(client_id,product_id,qty_g,sale_kop_per_kg,purchase_kop_per_kg) VALUES(?,?,?,?,?)',(cid,pid,q,price,prod['purchase_kop']))
                oid=cur.lastrowid
            await m.answer(f'Заказ #{oid}: {prod["name"]}, {q/1000:g} кг, {fmt(value(q,price))} грн. Статус new.')
        elif cmd == '/orders':
            with db() as c: rows=c.execute('SELECT o.*,c.name client,p.name product FROM orders o JOIN clients c ON c.id=o.client_id JOIN products p ON p.id=o.product_id ORDER BY o.id DESC LIMIT 25').fetchall()
            await m.answer('\n'.join(f"#{r['id']} {r['client']} · {r['product']} · {r['qty_g']/1000:g} кг · {fmt(value(r['qty_g'],r['sale_kop_per_kg']))} грн · {r['status']}" for r in rows) or 'Заказов нет.')
        elif cmd == '/status':
            p=[x.strip() for x in args.split('|')]
            if len(p)!=2 or p[1] not in ('new','packed','shipped','done','cancelled'): raise ValueError('Пример: /status 1 | shipped')
            with db() as c: cur=c.execute('UPDATE orders SET status=? WHERE id=?',(p[1],int(p[0])))
            await m.answer('Статус изменён.' if cur.rowcount else 'Заказ не найден.')
        elif cmd == '/pay':
            p=[x.strip() for x in args.split('|')]
            if len(p)!=2: raise ValueError('Пример: /pay 1 | 1500')
            cid=int(p[0]); amount=money(p[1]);
            if amount<=0: raise ValueError('Оплата должна быть больше нуля')
            with db() as c:
                if not c.execute('SELECT 1 FROM clients WHERE id=?',(cid,)).fetchone(): raise ValueError('Клиент не найден')
                c.execute('INSERT INTO payments(client_id,amount_kop) VALUES(?,?)',(cid,amount))
            await m.answer(f'Оплата {fmt(amount)} грн учтена для клиента #{cid}.')
        elif cmd == '/debts':
            with db() as c:
                clients=c.execute('SELECT id,name FROM clients ORDER BY name').fetchall()
                result=[]
                for cl in clients:
                    orders=c.execute("SELECT qty_g,sale_kop_per_kg FROM orders WHERE client_id=? AND status IN ('shipped','done')",(cl['id'],)).fetchall()
                    paid=c.execute('SELECT COALESCE(SUM(amount_kop),0) FROM payments WHERE client_id=?',(cl['id'],)).fetchone()[0]
                    balance=sum(value(r['qty_g'],r['sale_kop_per_kg']) for r in orders)-paid
                    if balance: result.append(f"#{cl['id']} {cl['name']}: {fmt(balance)} грн" + (' (переплата)' if balance<0 else ''))
            await m.answer('\n'.join(result) or 'Долгов и переплат нет. В расчёте только отгруженные/завершённые заказы.')
        elif cmd == '/report':
            with db() as c:
                rows=c.execute("SELECT * FROM orders WHERE status IN ('shipped','done')").fetchall()
                paid=c.execute('SELECT COALESCE(SUM(amount_kop),0) FROM payments').fetchone()[0]
            revenue=sum(value(r['qty_g'],r['sale_kop_per_kg']) for r in rows)
            cost=sum(value(r['qty_g'],r['purchase_kop_per_kg']) for r in rows)
            await m.answer(f'Отгруженная выручка: {fmt(revenue)} грн\nЗакупочная стоимость: {fmt(cost)} грн\nВаловая прибыль: {fmt(revenue-cost)} грн\nПолучено оплат: {fmt(paid)} грн\nДебиторка минус авансы: {fmt(revenue-paid)} грн\n\nБез учёта налогов, доставки, упаковки и других расходов.')
        elif cmd == '/export':
            with db() as c:
                for name,query in [
                    ('clients','SELECT * FROM clients'),('leads','SELECT * FROM leads'),('lead_events','SELECT * FROM lead_events'),('products','SELECT * FROM products'),
                    ('orders','SELECT * FROM orders'),('payments','SELECT * FROM payments')]:
                    rows=c.execute(query).fetchall()
                    out=io.StringIO(); w=csv.writer(out,delimiter=';')
                    if rows:
                        w.writerow(rows[0].keys()); w.writerows(tuple(r) for r in rows)
                    await m.answer_document(BufferedInputFile(('\ufeff'+out.getvalue()).encode('utf-8'),filename=f'magrok_{name}.csv'))
        else:
            await m.answer('Неизвестная команда. /help')
    except (ValueError, InvalidOperation) as e:
        await m.answer(f'Ошибка: {e}')
    except sqlite3.IntegrityError:
        await m.answer('Ошибка данных: проверь ID и значения.')

async def main():
    init_db()
    init_leads()
    bot=Bot(TOKEN)
    await bot.set_my_commands([
        BotCommand(command='start', description='Главное меню'),
        BotCommand(command='help', description='Все команды и примеры'),
        BotCommand(command='client', description='Добавить клиента'),
        BotCommand(command='clients', description='Список клиентов'),
        BotCommand(command='leads', description='Лиды и контакты'),
        BotCommand(command='product', description='Добавить или обновить товар'),
        BotCommand(command='products', description='Прайс и товары'),
        BotCommand(command='order', description='Создать строку заказа'),
        BotCommand(command='orders', description='Последние заказы'),
        BotCommand(command='status', description='Изменить статус заказа'),
        BotCommand(command='pay', description='Записать оплату'),
        BotCommand(command='debts', description='Задолженность клиентов'),
        BotCommand(command='report', description='Выручка и валовая прибыль'),
        BotCommand(command='export', description='Выгрузить CSV для Excel'),
    ])
    await dp.start_polling(bot)

if __name__=='__main__':
    asyncio.run(main())
