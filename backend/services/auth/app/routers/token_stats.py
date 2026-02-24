from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from backend.shared.token_tracker import get_token_tracker

from ..database import SessionLocal
from ..dependencies import get_current_user

router = APIRouter(prefix="/token-stats", tags=["token-stats"])


@router.get("/current")
async def get_current_token_usage(
    current_user_id: int = Depends(get_current_user),
    period: Optional[str] = Query(None, description="Период в формате YYYY-MM"),
):
    """
    Возвращает текущее использование токенов за указанный период из Redis.
    Если период не указан, используется текущий месяц.
    """
    token_tracker = get_token_tracker()

    usage_data = await token_tracker.get_current_usage(
        user_id=current_user_id, period=period
    )

    return {
        "user_id": current_user_id,
        "period": period or datetime.now(timezone.utc).strftime("%Y-%m"),
        "usage": usage_data,
    }


@router.get("/history")
def get_token_usage_history(
    current_user_id: int = Depends(get_current_user),
    limit: int = Query(
        12, ge=1, le=100, description="Количество периодов для возврата"
    ),
    offset: int = Query(0, ge=0, description="Смещение"),
):
    """
    Возвращает историю использования токенов из PostgreSQL.
    """
    db = SessionLocal()
    try:
        # Получаем историю использования токенов
        query = text("""
            SELECT 
                period,
                deepgram_seconds,
                deepl_characters,
                total_requests,
                last_updated,
                synced_at
            FROM token_usage
            WHERE user_id = :user_id
            ORDER BY period DESC
            LIMIT :limit OFFSET :offset
        """)

        result = db.execute(
            query, {"user_id": current_user_id, "limit": limit, "offset": offset}
        )

        rows = result.fetchall()

        history = []
        for row in rows:
            history.append(
                {
                    "period": row.period,
                    "deepgram_seconds": float(row.deepgram_seconds),
                    "deepl_characters": int(row.deepl_characters),
                    "total_requests": int(row.total_requests),
                    "last_updated": row.last_updated.isoformat()
                    if row.last_updated
                    else None,
                    "synced_at": row.synced_at.isoformat() if row.synced_at else None,
                }
            )

        # Получаем общее количество периодов
        count_query = text("""
            SELECT COUNT(*) as total
            FROM token_usage
            WHERE user_id = :user_id
        """)

        count_result = db.execute(count_query, {"user_id": current_user_id})
        total = count_result.scalar() or 0

        return {
            "user_id": current_user_id,
            "total_periods": total,
            "history": history,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "has_more": (offset + len(history)) < total,
            },
        }
    finally:
        db.close()


@router.get("/summary")
def get_token_usage_summary(
    current_user_id: int = Depends(get_current_user),
    year: Optional[int] = Query(None, description="Год для агрегации"),
):
    """
    Возвращает суммарную статистику использования токенов.
    Если год не указан, используется текущий год.
    """
    if year is None:
        year = datetime.now(timezone.utc).year

    db = SessionLocal()
    try:
        # Суммарная статистика за год
        query = text("""
            SELECT 
                SUM(deepgram_seconds) as total_deepgram_seconds,
                SUM(deepl_characters) as total_deepl_characters,
                SUM(total_requests) as total_requests,
                COUNT(DISTINCT period) as periods_count
            FROM token_usage
            WHERE user_id = :user_id
            AND period LIKE :year_pattern
        """)

        result = db.execute(
            query, {"user_id": current_user_id, "year_pattern": f"{year}-%"}
        )

        row = result.fetchone()

        if not row or row.total_deepgram_seconds is None:
            return {
                "user_id": current_user_id,
                "year": year,
                "summary": {
                    "total_deepgram_seconds": 0.0,
                    "total_deepl_characters": 0,
                    "total_requests": 0,
                    "periods_count": 0,
                },
            }

        return {
            "user_id": current_user_id,
            "year": year,
            "summary": {
                "total_deepgram_seconds": float(row.total_deepgram_seconds),
                "total_deepl_characters": int(row.total_deepl_characters),
                "total_requests": int(row.total_requests),
                "periods_count": int(row.periods_count),
            },
        }
    finally:
        db.close()


@router.get("/periods")
async def get_available_periods(
    current_user_id: int = Depends(get_current_user),
):
    """
    Возвращает список периодов, за которые есть данные в Redis.
    """
    token_tracker = get_token_tracker()

    periods = await token_tracker.get_periods_for_user(current_user_id)

    return {
        "user_id": current_user_id,
        "periods": periods,
        "current_period": datetime.now(timezone.utc).strftime("%Y-%m"),
    }


@router.get("/events")
def get_token_events(
    current_user_id: int = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=500, description="Количество событий"),
    offset: int = Query(0, ge=0, description="Смещение"),
    service_type: Optional[str] = Query(
        None, description="Тип сервиса (deepgram, deepl)"
    ),
):
    """
    Возвращает сырые события использования токенов.
    """
    db = SessionLocal()
    try:
        # Базовый запрос
        base_query = """
            SELECT 
                event_id,
                service_type,
                amount,
                event_metadata,
                created_at
            FROM token_events
            WHERE user_id = :user_id
        """

        params = {"user_id": current_user_id}

        if service_type:
            base_query += " AND service_type = :service_type"
            params["service_type"] = service_type

        # Запрос для данных
        data_query = text(
            base_query
            + """
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """
        )

        params.update({"limit": limit, "offset": offset})

        result = db.execute(data_query, params)
        rows = result.fetchall()

        events = []
        for row in rows:
            events.append(
                {
                    "event_id": str(row.event_id),
                    "service_type": row.service_type,
                    "amount": float(row.amount),
                    "metadata": row.event_metadata if row.event_metadata else {},
                    "created_at": row.created_at.isoformat()
                    if row.created_at
                    else None,
                }
            )

        # Запрос для общего количества
        count_query = text("""
            SELECT COUNT(*) as total
            FROM token_events
            WHERE user_id = :user_id
        """)

        count_params = {"user_id": current_user_id}
        if service_type:
            count_query = text("""
                SELECT COUNT(*) as total
                FROM token_events
                WHERE user_id = :user_id AND service_type = :service_type
            """)
            count_params["service_type"] = service_type

        count_result = db.execute(count_query, count_params)
        total = count_result.scalar() or 0

        return {
            "user_id": current_user_id,
            "events": events,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total,
                "has_more": (offset + len(events)) < total,
            },
        }
    finally:
        db.close()
