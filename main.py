import base64
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request

load_dotenv()

from business_days import add_business_days, count_business_days
from database import get_order, init_db, mark_fulfilled, save_order
from klaviyo_client import track_event
from scheduler import start_scheduler

SHOPIFY_SECRET = os.getenv("SHOPIFY_WEBHOOK_SECRET", "")


# ── Инициализация ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = start_scheduler()
    print("✅ Бот запущен!")
    yield
    scheduler.shutdown()
    print("Bot остановлен")


app = FastAPI(title="Fulfillment Bot", lifespan=lifespan)


# ── Верификация подписи Shopify ────────────────────────────────────────────────

def verify_shopify_signature(body: bytes, hmac_header: str) -> bool:
    """Проверяет что вебхук реально от Shopify."""
    if not SHOPIFY_SECRET:
        # В режиме разработки без секрета — пропускаем
        return True
    digest = hmac.new(
        SHOPIFY_SECRET.encode("utf-8"), body, hashlib.sha256
    ).digest()
    computed = base64.b64encode(digest).decode()
    return hmac.compare_digest(computed, hmac_header)


def parse_dt(iso_str: str) -> datetime:
    """Парсит ISO дату Shopify (с таймзоной) → naive UTC datetime."""
    return datetime.fromisoformat(iso_str).astimezone(timezone.utc).replace(tzinfo=None)


# ── Вебхук: заказ создан ──────────────────────────────────────────────────────

@app.post("/webhook/order-created")
async def order_created(
    request: Request,
    x_shopify_hmac_sha256: str = Header(default=""),
):
    body = await request.body()

    if not verify_shopify_signature(body, x_shopify_hmac_sha256):
        raise HTTPException(status_code=401, detail="Неверная подпись Shopify")

    data = json.loads(body)

    order_id = str(data["id"])
    email = data.get("email") or ""
    customer = data.get("customer") or {}
    first = customer.get("first_name") or ""
    last = customer.get("last_name") or ""
    customer_name = f"{first} {last}".strip() or "Покупатель"

    created_at = parse_dt(data["created_at"])

    # Дедлайн — 3 рабочих дня
    deadline = add_business_days(created_at, 3)

    save_order(order_id, email, customer_name, created_at, deadline)

    print(f"[NEW ORDER] #{order_id} | {email} | дедлайн: {deadline.strftime('%d.%m %H:%M')}")
    return {"status": "ok", "order_id": order_id, "deadline": deadline.isoformat()}


# ── Вебхук: заказ выполнен ────────────────────────────────────────────────────

@app.post("/webhook/order-fulfilled")
async def order_fulfilled(
    request: Request,
    x_shopify_hmac_sha256: str = Header(default=""),
):
    body = await request.body()

    if not verify_shopify_signature(body, x_shopify_hmac_sha256):
        raise HTTPException(status_code=401, detail="Неверная подпись Shopify")

    data = json.loads(body)

    order_id = str(data["id"])
    order = get_order(order_id)

    if not order:
        # Заказ мог прийти до запуска бота — просто пропускаем
        print(f"[SKIP] Заказ {order_id} не найден в БД")
        return {"status": "not_tracked"}

    # Shopify присылает updated_at при fulfillment
    fulfilled_at = parse_dt(data.get("updated_at") or data["created_at"])
    mark_fulfilled(order_id, fulfilled_at)

    created_at = datetime.fromisoformat(order["created_at"])
    business_days_taken = count_business_days(created_at, fulfilled_at)

    print(f"[FULFILLED] #{order_id} | {business_days_taken} раб. дней | {order['email']}")

    # Выполнен за 2 рабочих дня или меньше → отправляем "ура!"
    if business_days_taken <= 2:
        try:
            track_event(
                event_name="Order Fulfilled Early",
                email=order["email"],
                properties={
                    "order_id": order_id,
                    "customer_name": order["customer_name"],
                    "business_days_taken": business_days_taken,
                    "fulfilled_at": fulfilled_at.isoformat(),
                },
            )
            print(f"[EARLY] 🎉 Уведомление отправлено → {order['email']}")
        except Exception as e:
            print(f"[ERROR] Не удалось отправить early-уведомление: {e}")

    return {
        "status": "ok",
        "order_id": order_id,
        "business_days_taken": business_days_taken,
    }


# ── Вебхук: заказ в продакшене ───────────────────────────────────────────────

@app.post("/webhook/order-inprogress")
async def order_inprogress(
    request: Request,
    x_shopify_hmac_sha256: str = Header(default=""),
):
    body = await request.body()

    if not verify_shopify_signature(body, x_shopify_hmac_sha256):
        raise HTTPException(status_code=401, detail="Неверная подпись Shopify")

    data = json.loads(body)

    # Логируем что реально приходит от Shopify
    status = data.get("fulfillment_status") or ""
    tags = data.get("tags") or ""
    order_id_log = str(data.get("id", "?"))
    note = data.get("note") or ""
    note_attrs = data.get("note_attributes") or []
    fulfillments = data.get("fulfillments") or []
    fulfillment_statuses = [f.get("status") for f in fulfillments]
    tracking_urls = [f.get("tracking_url") for f in fulfillments if f.get("tracking_url")]
    print(f"[IN PROGRESS CHECK] order={order_id_log} fulfillment_status={repr(status)} tags={repr(tags)} note={repr(note)} note_attrs={note_attrs} fulfillment_statuses={fulfillment_statuses} tracking_urls={tracking_urls}")

    # Проверяем статус отдельных fulfillment объектов (не order.fulfillment_status)
    is_in_progress = any(
        f.get("status") in ("in_progress", "open")
        for f in fulfillments
    )

    if not is_in_progress:
        return {"status": "skipped", "reason": f"no in_progress fulfillment, statuses={fulfillment_statuses}"}

    order_id = str(data["id"])
    email = data.get("email") or ""
    customer = data.get("customer") or {}
    first = customer.get("first_name") or ""
    last = customer.get("last_name") or ""
    customer_name = f"{first} {last}".strip() or "Покупатель"

    print(f"[IN PROGRESS] #{order_id} | {email}")

    try:
        track_event(
            event_name="Order In Progress",
            email=email,
            properties={
                "order_id": order_id,
                "customer_name": customer_name,
            },
        )
        print(f"[IN PROGRESS] ✅ Событие отправлено → {email}")
    except Exception as e:
        print(f"[ERROR] Не удалось отправить in-progress событие: {e}")

    return {"status": "ok", "order_id": order_id}


# ── Healthcheck ───────────────────────────────────────────────────────────────

@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "alive"}
