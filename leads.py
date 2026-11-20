"""Lead management extension for MAGROK CRM (aiogram 3)."""
import os
import sqlite3
from datetime import date, datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

router = Router()
SOURCES = ['OLX', 'Instagram', 'Facebook', 'Сайт', 'Рекомендация', 'Звонок', 'Холодный контакт', 'Другое']
STAGES = [('new','Новый'),('contacted','Связались'),('price_sent','Прайс отправлен'),('negotiating','Переговоры'),('waiting','Ожидаем решение'),('first_order','Первый заказ'),('converted','Клиент'),('lost','Не заинтересован')]
STAGE_NAMES = dict(STAGES)

class LeadForm(StatesGroup):
    name = State()
    phone = State()
    source = State()
    interest = State()
    detail = State()
    edit = State()

def connect():
    path = os.getenv('DB_PATH', 'magrok.db')
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def init_leads():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS leads (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT 'Другое', interest TEXT NOT NULL DEFAULT '',
          stage TEXT NOT NULL DEFAULT 'new', city TEXT NOT NULL DEFAULT '',
          contact_name TEXT NOT NULL DEFAULT '', business_type TEXT NOT NULL DEFAULT '',
          estimated_volume TEXT NOT NULL DEFAULT '', terms TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '', next_contact TEXT NOT NULL DEFAULT '',
          client_id INTEGER REFERENCES clients(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS lead_events (
          id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id),
          event TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS ix_leads_stage ON leads(stage);
        CREATE INDEX IF NOT EXISTS ix_leads_followup ON leads(next_contact);
        ''')

def keys(rows, prefix, cols=2):
    buttons = [InlineKeyboardButton(text=label, callback_data=f'{prefix}{key}') for key,label in rows]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i+cols] for i in range(0,len(buttons),cols)])

def lead_menu():
    return keys([('new','➕ Новый лид'),('list','📋 Все лиды'),('tasks','📅 Контакты на сегодня')], 'leadmenu:', 1)

def lead_actions(lid):
    return keys([('stage','🔄 Этап'),('edit','✏️ Дополнить'),('follow','📅 Следующий контакт'),('note','📝 Заметка'),('convert','👤 Сделать клиентом'),('history','📜 История')], f'leadaction:{lid}:', 2)

async def owner_message(m):
    if not m.from_user or m.from_user.id != int(os.getenv('OWNER_ID','0')):
        await m.answer('Доступ закрыт.')
        return False
    return True

async def owner_callback(q):
    if not q.from_user or q.from_user.id != int(os.getenv('OWNER_ID','0')):
        await q.answer('Доступ закрыт.', show_alert=True)
        return False
    return True

def event(c, lid, description):
    c.execute('INSERT INTO lead_events(lead_id,event) VALUES(?,?)', (lid,description))

def display(row):
    return (f"Лид #{row['id']} — {row['name']}\n"
            f"Этап: {STAGE_NAMES.get(row['stage'],row['stage'])}\n"
            f"Телефон: {row['phone'] or '—'}\nИсточник: {row['source']}\n"
            f"Интерес: {row['interest'] or '—'}\nГород: {row['city'] or '—'}\n"
            f"Контактное лицо: {row['contact_name'] or '—'}\nТип бизнеса: {row['business_type'] or '—'}\n"
            f"Объём: {row['estimated_volume'] or '—'}\nУсловия: {row['terms'] or '—'}\n"
            f"Следующий контакт: {row['next_contact'] or '—'}\nЗаметки: {row['notes'] or '—'}")

@router.message(Command('leads'))
@router.message(F.text == '🎯 Лиды')
async def leads_home(m: Message, state: FSMContext):
    if not await owner_message(m): return
    await state.clear()
    with connect() as c:
        total = c.execute('SELECT COUNT(*) FROM leads').fetchone()[0]
        active = c.execute("SELECT COUNT(*) FROM leads WHERE stage NOT IN ('lost','converted')").fetchone()[0]
    await m.answer(f'🎯 Лиды МАГРОК\nВсего: {total} · В работе: {active}', reply_markup=lead_menu())

@router.callback_query(F.data.startswith('leadmenu:'))
async def menu_cb(q: CallbackQuery, state: FSMContext):
    if not await owner_callback(q): return
    await q.answer()
    action=q.data.split(':')[1]
    if action=='new':
        await state.clear(); await state.set_state(LeadForm.name)
        await q.message.answer('➕ Новый лид. Введи название магазина, компании или имя человека.\n/cancel — отмена')
    elif action=='list':
        with connect() as c:
            rows=c.execute('SELECT id,name,source,stage FROM leads ORDER BY id DESC LIMIT 30').fetchall()
        if not rows: await q.message.answer('Лидов пока нет.'); return
        for r in rows:
            await q.message.answer(f"#{r['id']} {r['name']} · {r['source']} · {STAGE_NAMES.get(r['stage'],r['stage'])}", reply_markup=keys([('open','Открыть карточку')],f"leadopen:{r['id']}:",1))
    elif action=='tasks':
        today=date.today().isoformat()
        with connect() as c:
            rows=c.execute("SELECT id,name,next_contact,phone FROM leads WHERE next_contact!='' AND next_contact<=? AND stage NOT IN ('lost','converted') ORDER BY next_contact,id LIMIT 40",(today,)).fetchall()
        await q.message.answer('\n'.join(f"#{r['id']} {r['next_contact']} · {r['name']} · {r['phone']}" for r in rows) or 'Просроченных контактов и задач на сегодня нет.')

@router.message(Command('cancel'))
async def cancel(m:Message,state:FSMContext):
    if not await owner_message(m):return
    await state.clear(); await m.answer('Действие отменено.',reply_markup=lead_menu())

@router.message(LeadForm.name)
async def name_step(m:Message,state:FSMContext):
    if not await owner_message(m):return
    name=(m.text or '').strip()
    if not name or len(name)>150: await m.answer('Введи название текстом (до 150 символов).');return
    await state.update_data(name=name); await state.set_state(LeadForm.phone)
    await m.answer('Телефон? Напиши номер или «-», если пока неизвестен.')

@router.message(LeadForm.phone)
async def phone_step(m:Message,state:FSMContext):
    if not await owner_message(m):return
    phone=(m.text or '').strip()
    if len(phone)>80: await m.answer('Слишком длинный номер.');return
    await state.update_data(phone='' if phone=='-' else phone)
    await state.set_state(LeadForm.source)
    await m.answer('Откуда пришёл лид?',reply_markup=keys([(str(i),s) for i,s in enumerate(SOURCES)],'leadsource:'))

@router.callback_query(F.data.startswith('leadsource:'),LeadForm.source)
async def source_step(q:CallbackQuery,state:FSMContext):
    if not await owner_callback(q):return
    try: src=SOURCES[int(q.data.split(':')[1])]
    except (ValueError,IndexError): await q.answer('Неверный источник');return
    await q.answer();await state.update_data(source=src);await state.set_state(LeadForm.interest)
    await q.message.answer('Какая продукция интересует? Напиши кратко или «-».')

@router.message(LeadForm.interest)
async def interest_step(m:Message,state:FSMContext):
    if not await owner_message(m):return
    interest=(m.text or '').strip()
    if len(interest)>500: await m.answer('Сократи до 500 символов.');return
    data=await state.get_data()
    with connect() as c:
        cur=c.execute('INSERT INTO leads(name,phone,source,interest) VALUES(?,?,?,?)',(data['name'],data['phone'],data['source'],'' if interest=='-' else interest))
        lid=cur.lastrowid;event(c,lid,'Лид создан')
    await state.clear()
    await m.answer(f'✅ Лид #{lid} сохранён. Дополнить можно в любой момент.',reply_markup=lead_actions(lid))

@router.callback_query(F.data.startswith('leadopen:'))
async def open_lead(q:CallbackQuery):
    if not await owner_callback(q):return
    await q.answer()
    try: lid=int(q.data.split(':')[1])
    except (ValueError,IndexError):return
    with connect() as c: r=c.execute('SELECT * FROM leads WHERE id=?',(lid,)).fetchone()
    if not r:await q.message.answer('Лид не найден.');return
    await q.message.answer(display(r),reply_markup=lead_actions(lid))

@router.callback_query(F.data.startswith('leadaction:'))
async def action_cb(q:CallbackQuery,state:FSMContext):
    if not await owner_callback(q):return
    await q.answer()
    try: _,lid,action=q.data.split(':');lid=int(lid)
    except (ValueError,IndexError):return
    with connect() as c: r=c.execute('SELECT * FROM leads WHERE id=?',(lid,)).fetchone()
    if not r:await q.message.answer('Лид не найден.');return
    if action=='stage':
        await q.message.answer('Выбери этап:',reply_markup=keys(STAGES,f'leadstage:{lid}:'))
    elif action=='edit':
        fields=[('city','Город'),('contact_name','Контактное лицо'),('business_type','Тип бизнеса'),('estimated_volume','Планируемый объём'),('terms','Цена и условия'),('phone','Телефон'),('interest','Интересующая продукция'),('source','Источник')]
        await q.message.answer('Что заполнить?',reply_markup=keys(fields,f'leadfield:{lid}:'))
    elif action in ('follow','note'):
        await state.set_state(LeadForm.edit);await state.update_data(lid=lid,field='next_contact' if action=='follow' else 'notes',append=action=='note')
        await q.message.answer('Введи дату ГГГГ-ММ-ДД (или «-» для очистки).' if action=='follow' else 'Введи заметку (добавится к истории заметок).')
    elif action=='history':
        with connect() as c: events=c.execute('SELECT * FROM lead_events WHERE lead_id=? ORDER BY id DESC LIMIT 25',(lid,)).fetchall()
        await q.message.answer('\n'.join(f"{r['created_at']}: {r['event']}" for r in events) or 'История пуста.')
    elif action=='convert':
        await q.message.answer('Подтверди создание клиента из этого лида:',reply_markup=keys([('yes','✅ Подтвердить'),('no','Отмена')],f'leadconvert:{lid}:'))

@router.callback_query(F.data.startswith('leadstage:'))
async def stage_cb(q:CallbackQuery):
    if not await owner_callback(q):return
    await q.answer()
    try: _,lid,stage=q.data.split(':');lid=int(lid)
    except (ValueError,IndexError):return
    if stage not in STAGE_NAMES:return
    if stage=='converted':
        await q.message.answer('Чтобы перевести в клиентов, нажми «Сделать клиентом» в карточке лида.');return
    with connect() as c:
        cur=c.execute('UPDATE leads SET stage=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND stage!=?',(stage,lid,'converted'))
        if cur.rowcount:event(c,lid,f'Этап: {STAGE_NAMES[stage]}')
    await q.message.answer('Этап обновлён.' if cur.rowcount else 'Лид не найден или уже клиент.',reply_markup=lead_actions(lid) if cur.rowcount else None)

@router.callback_query(F.data.startswith('leadfield:'))
async def field_cb(q:CallbackQuery,state:FSMContext):
    if not await owner_callback(q):return
    await q.answer()
    try: _,lid,field=q.data.split(':');lid=int(lid)
    except (ValueError,IndexError):return
    allowed={'city','contact_name','business_type','estimated_volume','terms','phone','interest','source'}
    if field not in allowed:return
    await state.set_state(LeadForm.edit);await state.update_data(lid=lid,field=field,append=False)
    await q.message.answer('Введи новое значение (или «-», чтобы очистить).')

@router.message(LeadForm.edit)
async def edit_step(m:Message,state:FSMContext):
    if not await owner_message(m):return
    data=await state.get_data();field=data.get('field');lid=data.get('lid')
    allowed={'city','contact_name','business_type','estimated_volume','terms','phone','interest','source','next_contact','notes'}
    if field not in allowed or not isinstance(lid,int):await state.clear();return
    text=(m.text or '').strip()
    if len(text)>1500:await m.answer('Слишком длинный текст (максимум 1500 символов).');return
    if field=='next_contact' and text!='-':
        try:
            parsed=date.fromisoformat(text)
            if parsed.isoformat()!=text:raise ValueError
        except ValueError:await m.answer('Дата нужна в формате ГГГГ-ММ-ДД, например 2026-11-25.');return
    new='' if text=='-' else text
    with connect() as c:
        r=c.execute('SELECT notes FROM leads WHERE id=?',(lid,)).fetchone()
        if not r:await m.answer('Лид не найден.');await state.clear();return
        if data.get('append') and new:new=(r['notes']+'\n' if r['notes'] else '')+f'{date.today().isoformat()}: {new}'
        c.execute(f'UPDATE leads SET {field}=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(new,lid))
        event(c,lid,f'Изменено поле {field}: {text[:160]}')
    await state.clear();await m.answer('✅ Сохранено.',reply_markup=lead_actions(lid))

@router.callback_query(F.data.startswith('leadconvert:'))
async def convert_cb(q:CallbackQuery):
    if not await owner_callback(q):return
    await q.answer()
    try: _,lid,choice=q.data.split(':');lid=int(lid)
    except (ValueError,IndexError):return
    if choice!='yes':await q.message.answer('Отменено.');return
    with connect() as c:
        r=c.execute('SELECT * FROM leads WHERE id=?',(lid,)).fetchone()
        if not r:await q.message.answer('Лид не найден.');return
        if r['client_id']:await q.message.answer(f"Уже клиент #{r['client_id']}.");return
        cur=c.execute('INSERT INTO clients(name,phone,note) VALUES(?,?,?)',(r['name'],r['phone'],f"Из лида #{lid}. {r['notes']}"))
        cid=cur.lastrowid
        c.execute("UPDATE leads SET client_id=?,stage='converted',updated_at=CURRENT_TIMESTAMP WHERE id=?",(cid,lid))
        event(c,lid,f'Переведён в клиента #{cid}')
    await q.message.answer(f'✅ Клиент #{cid} создан. Теперь можно оформлять заказы.',reply_markup=lead_actions(lid))
