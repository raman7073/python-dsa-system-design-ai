from datetime import datetime, date
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select, func
from database import get_session
from models import Order, OrderStatus

router = APIRouter(prefix="/stats", tags=["Stats"])


@router.get("/daily")
def daily_summary(
    summary_date: date | None = Query(
        default=None, description="Date for which to get the summary (YYYY-MM-DD)"),
    session: Session = Depends(get_session)
):
    if summary_date is None:
        summary_date = date.today()

    start = datetime.combine(summary_date, datetime.min.time())
    end = datetime.combine(summary_date, datetime.max.time())

    total_orders = session.exec(
        select(func.count()).where(Order.created_at.between(start, end))
    ).one()

    status_counts = session.exec(
        select(Order.status, func.count())
        .where(Order.created_at.between(start, end))
        .group_by(Order.status)
    ).all()

    status_summary = {status.value: count for status, count in status_counts}

    return {
        "date": summary_date,
        "total_orders": total_orders,
        "status_summary": status_summary
    }
