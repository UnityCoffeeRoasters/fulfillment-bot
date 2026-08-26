from datetime import datetime, timedelta


def add_business_days(start: datetime, days: int) -> datetime:
    """
    Добавляет N рабочих дней (пн-пт) к дате.
    Возвращает datetime в конце того дня.
    """
    current = start.date()
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0=пн, 4=пт
            added += 1
    # Возвращаем конец дня (23:59:59), чтобы дать весь день на выполнение
    return datetime(current.year, current.month, current.day, 23, 59, 59)


def count_business_days(start: datetime, end: datetime) -> int:
    """
    Считает рабочие дни между двумя датами (пн-пт).
    """
    start_date = start.date()
    end_date = end.date()
    days = 0
    current = start_date
    while current < end_date:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days += 1
    return days
