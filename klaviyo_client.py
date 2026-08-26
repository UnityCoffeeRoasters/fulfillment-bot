import os
from datetime import datetime, timezone

import httpx

KLAVIYO_API_KEY = os.getenv("KLAVIYO_API_KEY", "")
BASE_URL = "https://a.klaviyo.com/api"

HEADERS = {
    "Authorization": f"Klaviyo-API-Key {KLAVIYO_API_KEY}",
    "revision": "2024-02-15",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def track_event(event_name: str, email: str, properties: dict) -> None:
    """
    Отправляет кастомное событие в Klaviyo.

    В Klaviyo нужно создать Flow с триггером на это событие:
    - "Order Fulfillment Late"  → письмо с купоном
    - "Order Fulfilled Early"   → письмо "ура, успели!"
    """
    payload = {
        "data": {
            "type": "event",
            "attributes": {
                "metric": {
                    "data": {
                        "type": "metric",
                        "attributes": {"name": event_name},
                    }
                },
                "profile": {
                    "data": {
                        "type": "profile",
                        "attributes": {"email": email},
                    }
                },
                "properties": properties,
                "time": datetime.now(timezone.utc).isoformat(),
            },
        }
    }

    # Обновляем заголовок — API ключ мог измениться после загрузки env
    headers = {**HEADERS, "Authorization": f"Klaviyo-API-Key {os.getenv('KLAVIYO_API_KEY', '')}"}

    with httpx.Client(timeout=10) as client:
        response = client.post(f"{BASE_URL}/events/", json=payload, headers=headers)

    if response.status_code == 202:
        print(f"[KLAVIYO] Событие '{event_name}' отправлено → {email}")
    else:
        print(f"[KLAVIYO ERROR] {response.status_code}: {response.text}")
        response.raise_for_status()
