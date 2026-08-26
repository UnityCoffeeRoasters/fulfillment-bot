from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from database import get_overdue_orders, mark_late_notified
from klaviyo_client import track_event


def check_overdue_orders():
    """
    Каждый час проверяет: есть ли заказы у которых прошёл 3-дневный дедлайн
    и они так и не были выполнены. Если есть — стреляет событие в Klaviyo.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    overdue = get_overdue_orders(now)

    if not overdue:
        print(f"[SCHEDULER] {now.strftime('%H:%M')} — просроченных заказов нет")
        return

    print(f"[SCHEDULER] Найдено просроченных заказов: {len(overdue)}")

    for order in overdue:
        print(f"[OVERDUE] Заказ {order['order_id']} | {order['email']}")
        try:
            track_event(
                event_name="Order Fulfillment Late",
                email=order["email"],
                properties={
                    "order_id": order["order_id"],
                    "customer_name": order["customer_name"] or "Покупатель",
                    "ordered_at": order["created_at"],
                    "deadline": order["deadline"],
                    # Это свойство подтянется в Klaviyo для генерации купона
                    "coupon_reason": "late_fulfillment",
                },
            )
            mark_late_notified(order["order_id"])
        except Exception as e:
            print(f"[ERROR] Не удалось уведомить {order['email']}: {e}")


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    # Проверка каждый час
    scheduler.add_job(check_overdue_orders, "interval", hours=1, id="overdue_check")
    scheduler.start()
    print("[SCHEDULER] Запущен — проверка каждый час")
    return scheduler
