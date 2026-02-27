import aiosqlite
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict


class Database:
    def __init__(self, path: str = "keyflow.db"):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_id       INTEGER UNIQUE NOT NULL,
                    username    TEXT DEFAULT '',
                    full_name   TEXT DEFAULT '',
                    ref_code    TEXT UNIQUE,
                    referred_by INTEGER DEFAULT NULL,
                    bonus_balance REAL DEFAULT 0,
                    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS services (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    emoji       TEXT DEFAULT '🔑',
                    description TEXT DEFAULT '',
                    category    TEXT DEFAULT 'other',
                    min_price   REAL DEFAULT 0,
                    is_active   INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS service_variants (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_id INTEGER NOT NULL,
                    duration   TEXT NOT NULL,
                    price      REAL NOT NULL,
                    FOREIGN KEY (service_id) REFERENCES services(id)
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id         INTEGER NOT NULL,
                    service_id      INTEGER NOT NULL,
                    variant_id      INTEGER NOT NULL,
                    amount          REAL NOT NULL,
                    status          TEXT DEFAULT 'pending',
                    payment_method  TEXT DEFAULT '',
                    invoice_id      TEXT DEFAULT '',
                    webapp_order_id TEXT DEFAULT '',
                    expires_at      TEXT DEFAULT NULL,
                    reminded        INTEGER DEFAULT 0,
                    created_at      TEXT DEFAULT (datetime('now', 'localtime')),
                    updated_at      TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS withdrawals (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id   INTEGER NOT NULL,
                    amount     REAL NOT NULL,
                    details    TEXT NOT NULL,
                    status     TEXT DEFAULT 'completed',
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS pending_deliveries (
                    admin_id  INTEGER PRIMARY KEY,
                    order_id  INTEGER NOT NULL
                );

                -- Seed services
                INSERT OR IGNORE INTO services (id,name,emoji,description,category,min_price) VALUES
                  (1,'Spotify Premium','🎵','Музыка без рекламы, скачивание','music',199),
                  (2,'ChatGPT Plus','🤖','GPT-4, DALL-E, анализ файлов','ai',1490),
                  (3,'Claude Pro','🤍','Claude Opus, длинный контекст','ai',1590),
                  (4,'Gemini Advanced','✨','Gemini Ultra, Google Workspace','ai',1390),
                  (5,'Sora','🎬','Генерация видео от OpenAI','ai',1690),
                  (6,'Steam пополнение','🎮','Пополнение кошелька Steam','games',0),
                  (7,'Discord Nitro','💜','Кастомный тег, стикеры, буст','games',299),
                  (8,'Roblox','⬛','Пополнение Robux','games',199),
                  (9,'Brawl Stars','💎','Гемы и Brawl Pass','games',149);

                INSERT OR IGNORE INTO service_variants (id,service_id,duration,price) VALUES
                  (1,1,'1 месяц',199),(2,1,'3 месяца',549),(3,1,'6 месяцев',999),(4,1,'1 год',1799),
                  (5,2,'1 месяц',1490),(6,2,'3 месяца',3990),
                  (7,3,'1 месяц',1590),(8,3,'3 месяца',4290),
                  (9,4,'1 месяц',1390),(10,4,'3 месяца',3690),
                  (11,5,'1 месяц',1690),(12,5,'3 месяца',4590),
                  (15,7,'1 месяц',299),(16,7,'3 месяца',799),(17,7,'1 год',2799),
                  (18,8,'400 Robux',199),(19,8,'800 Robux',369),(20,8,'1700 Robux',749),
                  (21,9,'30 гемов',149),(22,9,'80 гемов',369),(23,9,'Brawl Pass',299);
            """)
            await db.commit()

    # ── USERS ──────────────────────────────────────────────────────────────────

    async def upsert_user(self, tg_id, username, full_name, referred_by=None):
        import random, string
        ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO users (tg_id,username,full_name,ref_code,referred_by) VALUES (?,?,?,?,?) "
                "ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name",
                (tg_id, username, full_name, ref_code, referred_by)
            )
            await db.commit()

    async def get_user(self, tg_id) -> Optional[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)) as c:
                r = await c.fetchone()
                return dict(r) if r else None

    async def get_user_by_ref(self, ref_code) -> Optional[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE ref_code=?", (ref_code,)) as c:
                r = await c.fetchone()
                return dict(r) if r else None

    async def get_all_users(self) -> List[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users") as c:
                return [dict(r) for r in await c.fetchall()]

    async def get_recent_users(self, limit=10) -> List[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users ORDER BY id DESC LIMIT ?", (limit,)) as c:
                return [dict(r) for r in await c.fetchall()]

    async def add_bonus(self, tg_id, amount):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET bonus_balance = bonus_balance + ? WHERE tg_id=?",
                (amount, tg_id)
            )
            await db.commit()

    async def get_referral_count(self, tg_id) -> int:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (tg_id,)) as c:
                return (await c.fetchone())[0]

    # ── SERVICES ───────────────────────────────────────────────────────────────

    async def get_services(self) -> List[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM services ORDER BY id") as c:
                return [dict(r) for r in await c.fetchall()]

    async def get_service(self, svc_id) -> Optional[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM services WHERE id=?", (svc_id,)) as c:
                r = await c.fetchone()
                return dict(r) if r else None

    async def toggle_service(self, svc_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE services SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?",
                (svc_id,)
            )
            await db.commit()

    async def get_service_variants(self, svc_id) -> List[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM service_variants WHERE service_id=? ORDER BY price", (svc_id,)) as c:
                return [dict(r) for r in await c.fetchall()]

    async def get_variant(self, v_id) -> Optional[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM service_variants WHERE id=?", (v_id,)) as c:
                r = await c.fetchone()
                return dict(r) if r else None

    # ── ORDERS ─────────────────────────────────────────────────────────────────

    async def create_order(self, user_id, service_id, variant_id, amount,
                           payment_method='', webapp_order_id='') -> int:
        async with aiosqlite.connect(self.path) as db:
            c = await db.execute(
                "INSERT INTO orders (user_id,service_id,variant_id,amount,payment_method,webapp_order_id) "
                "VALUES (?,?,?,?,?,?)",
                (user_id, service_id, variant_id, amount, payment_method, str(webapp_order_id))
            )
            await db.commit()
            return c.lastrowid

    async def get_order(self, order_id) -> Optional[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM orders WHERE id=?", (order_id,)) as c:
                r = await c.fetchone()
                return dict(r) if r else None

    async def get_order_by_webapp_id(self, webapp_order_id) -> Optional[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM orders WHERE webapp_order_id=? ORDER BY id DESC LIMIT 1",
                (str(webapp_order_id),)
            ) as c:
                r = await c.fetchone()
                return dict(r) if r else None

    async def update_order_invoice(self, order_id, invoice_id, method):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE orders SET invoice_id=?, payment_method=?, updated_at=datetime('now','localtime') WHERE id=?",
                (invoice_id, method, order_id)
            )
            await db.commit()

    async def update_order_status(self, order_id, status):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE orders SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
                (status, order_id)
            )
            await db.commit()

    async def set_order_expiry(self, order_id, expires_at: str):
        """Установить дату окончания подписки"""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE orders SET expires_at=? WHERE id=?",
                (expires_at, order_id)
            )
            await db.commit()

    async def get_expiring_orders(self, days_ahead=3) -> List[Dict]:
        """Заказы, истекающие через N дней и ещё не получившие напоминание"""
        target = (date.today() + timedelta(days=days_ahead)).isoformat()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT o.*, s.name as service_name, v.duration
                FROM orders o
                LEFT JOIN services s ON o.service_id = s.id
                LEFT JOIN service_variants v ON o.variant_id = v.id
                WHERE o.status = 'completed'
                  AND o.expires_at IS NOT NULL
                  AND DATE(o.expires_at) = ?
                  AND o.reminded = 0
            """, (target,)) as c:
                return [dict(r) for r in await c.fetchall()]

    async def mark_reminded(self, order_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE orders SET reminded=1 WHERE id=?", (order_id,))
            await db.commit()

    async def get_user_orders(self, user_id) -> List[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT o.*, s.name as service_name, s.emoji, v.duration, v.price as variant_price
                FROM orders o
                LEFT JOIN services s ON o.service_id = s.id
                LEFT JOIN service_variants v ON o.variant_id = v.id
                WHERE o.user_id = ?
                ORDER BY o.id DESC LIMIT 20
            """, (user_id,)) as c:
                return [dict(r) for r in await c.fetchall()]

    async def get_active_orders(self, limit=20) -> List[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT o.*, s.name as service_name, v.duration, u.username
                FROM orders o
                LEFT JOIN services s ON o.service_id = s.id
                LEFT JOIN service_variants v ON o.variant_id = v.id
                LEFT JOIN users u ON o.user_id = u.tg_id
                WHERE o.status NOT IN ('completed','cancelled')
                ORDER BY o.id DESC LIMIT ?
            """, (limit,)) as c:
                return [dict(r) for r in await c.fetchall()]

    # ── STATS ──────────────────────────────────────────────────────────────────

    async def get_stats(self) -> Dict:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            today    = date.today().isoformat()
            week_ago = "datetime('now', '-7 days', 'localtime')"
            month    = datetime.now().strftime("%Y-%m")

            def q(sql, *args):
                return db.execute(sql, args)

            result = {}
            async with await q("SELECT COUNT(*) c FROM users") as c:
                result['total_users'] = (await c.fetchone())['c']
            async with await q("SELECT COUNT(*) c FROM orders") as c:
                result['total_orders'] = (await c.fetchone())['c']
            async with await q("SELECT COUNT(*) c FROM orders WHERE status='completed'") as c:
                result['completed_orders'] = (await c.fetchone())['c']
            async with await q("SELECT COUNT(*) c FROM orders WHERE status='cancelled'") as c:
                result['cancelled_orders'] = (await c.fetchone())['c']
            async with await q("SELECT COUNT(*) c FROM orders WHERE status NOT IN ('completed','cancelled')") as c:
                result['active_orders'] = (await c.fetchone())['c']
            async with await q("SELECT COUNT(*) c FROM orders WHERE DATE(created_at)=?", today) as c:
                result['today_orders'] = (await c.fetchone())['c']
            async with await q("SELECT COALESCE(SUM(amount),0) s FROM orders WHERE status='completed' AND DATE(created_at)=?", today) as c:
                result['today_revenue'] = round((await c.fetchone())['s'], 2)
            async with await q(f"SELECT COALESCE(SUM(amount),0) s FROM orders WHERE status='completed' AND created_at >= {week_ago}") as c:
                result['week_revenue'] = round((await c.fetchone())['s'], 2)
            async with await q("SELECT COALESCE(SUM(amount),0) s FROM orders WHERE status='completed' AND strftime('%Y-%m',created_at)=?", month) as c:
                result['month_revenue'] = round((await c.fetchone())['s'], 2)
            async with await q("SELECT COALESCE(SUM(amount),0) s FROM orders WHERE status='completed'") as c:
                result['total_revenue'] = round((await c.fetchone())['s'], 2)

            for method in ('sbp', 'crypto', 'card'):
                async with await q("SELECT COALESCE(SUM(amount),0) s FROM orders WHERE status='completed' AND payment_method=?", method) as c:
                    result[f'{method}_revenue'] = round((await c.fetchone())['s'], 2)

            return result

    # ── BALANCE ────────────────────────────────────────────────────────────────

    async def get_balance(self) -> Dict:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT COALESCE(SUM(amount),0) s FROM orders WHERE status='completed'") as c:
                total_earned = round((await c.fetchone())['s'], 2)
            async with db.execute("SELECT COALESCE(SUM(amount),0) s FROM orders WHERE status NOT IN ('completed','cancelled','pending')") as c:
                frozen = round((await c.fetchone())['s'], 2)
            async with db.execute("SELECT COALESCE(SUM(amount),0) s FROM withdrawals WHERE status='completed'") as c:
                withdrawn = round((await c.fetchone())['s'], 2)
            return {
                'total_earned': total_earned,
                'available':    round(total_earned - withdrawn, 2),
                'frozen':       frozen,
                'withdrawn':    withdrawn,
            }

    # ── WITHDRAWALS ────────────────────────────────────────────────────────────

    async def create_withdrawal(self, admin_id, amount, details) -> int:
        async with aiosqlite.connect(self.path) as db:
            c = await db.execute(
                "INSERT INTO withdrawals (admin_id,amount,details) VALUES (?,?,?)",
                (admin_id, amount, details)
            )
            await db.commit()
            return c.lastrowid

    async def complete_withdrawal(self, withdraw_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE withdrawals SET status='completed' WHERE id=?", (withdraw_id,))
            await db.commit()

    async def get_withdrawal(self, withdraw_id) -> Optional[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM withdrawals WHERE id=?", (withdraw_id,)) as c:
                r = await c.fetchone()
                return dict(r) if r else None

    async def get_withdrawals(self, limit=20) -> List[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM withdrawals ORDER BY id DESC LIMIT ?", (limit,)) as c:
                rows = [dict(r) for r in await c.fetchall()]
                for row in rows:
                    details = row.get('details', '')
                    row['details_short'] = details[:30] + '…' if len(details) > 30 else details
                    dt = row.get('created_at', '')
                    row['created_at'] = dt[:16] if dt else ''
                return rows

    # ── DELIVERY ───────────────────────────────────────────────────────────────

    async def set_pending_delivery(self, order_id, admin_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO pending_deliveries (admin_id,order_id) VALUES (?,?)",
                (admin_id, order_id)
            )
            await db.commit()

    async def get_pending_delivery(self, admin_id) -> Optional[int]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT order_id FROM pending_deliveries WHERE admin_id=?", (admin_id,)) as c:
                r = await c.fetchone()
                return r['order_id'] if r else None

    async def clear_pending_delivery(self, admin_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM pending_deliveries WHERE admin_id=?", (admin_id,))
            await db.commit()
