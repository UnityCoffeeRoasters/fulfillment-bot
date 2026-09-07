import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = "orders.db"


def init_db():
    """Создаёт таблицу заказов если её нет."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id             TEXT PRIMARY KEY,
                email                TEXT NOT NULL,
                customer_name        TEXT,
                created_at           TEXT NOT NULL,
                deadline             TEXT NOT NULL,
                fulfilled_at         TEXT,
                late_notified        INTEGER DEFAULT 0,
                inprogress_notified  INTEGER DEFAULT 0
            )
        """)
        # Миграция для существующих БД без колонки
        try:
            conn.execute("ALTER TABLE orders ADD COLUMN inprogress_notified INTEGER DEFAULT 0")
        except Exception:
            pass  # Колонка уже есть
    print("[DB] Таблица orders готова")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_order(
    order_id: str,
    email: str,
    customer_name: str,
    created_at: datetime,
    deadline: datetime,
):
    """Сохраняет новый заказ."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO orders
                (order_id, email, customer_name, created_at, deadline, late_notified)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                order_id,
                email,
                customer_name,
                created_at.isoformat(),
                deadline.isoformat(),
            ),
        )


def mark_fulfilled(order_id: str, fulfilled_at: datetime):
    """Помечает заказ как выполненный."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET fulfilled_at = ? WHERE order_id = ?",
            (fulfilled_at.isoformat(), order_id),
        )


def get_order(order_id: str) -> dict | None:
    """Возвращает заказ по ID или None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        return dict(row) if row else None


def get_overdue_orders(now: datetime) -> list[dict]:
    """
    Возвращает заказы у которых:
    - прошёл дедлайн
    - они ещё не выполнены
    - уведомление ещё не отправлялось
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM orders
            WHERE fulfilled_at IS NULL
              AND late_notified = 0
              AND deadline <= ?
            """,
            (now.isoformat(),),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_late_notified(order_id: str):
    """Помечает что уведомление о просрочке отправлено."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET late_notified = 1 WHERE order_id = ?",
            (order_id,),
        )


def get_inprogress_pending_orders(now: datetime) -> list[dict]:
    """
    Заказы которым 24+ часа, ещё не выполнены и не получили уведомление In Progress.
    """
    from datetime import timedelta
    cutoff = (now - timedelta(hours=24)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM orders
            WHERE fulfilled_at IS NULL
              AND inprogress_notified = 0
              AND created_at <= ?
            """,
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_inprogress_notified(order_id: str):
    """Помечает что уведомление In Progress отправлено."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET inprogress_notified = 1 WHERE order_id = ?",
            (order_id,),
        )
