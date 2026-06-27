"""AI usage ledger endpoints — powers the super-user usage screen.

Reads the `ai_usage` table written by services/usage.py:
  GET    /usage          recent rows (filterable)
  GET    /usage/summary  totals + breakdowns for the dashboard cards & charts
  GET    /usage/pivot    generic 2-dimension pivot (row × col × metric)
  DELETE /usage          clear the ledger
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AIUsage

router = APIRouter()


# Dimensions the pivot/summary may group by → SQL expression factory.
def _dim_expr(name: str):
    if name == "usage_type":
        return AIUsage.usage_type
    if name == "provider_type":
        return AIUsage.provider_type
    if name == "provider_name":
        return func.coalesce(AIUsage.provider_name, AIUsage.provider_type)
    if name == "model":
        return func.coalesce(AIUsage.model, "—")
    if name == "status":
        return AIUsage.status
    if name == "day":
        return func.strftime("%Y-%m-%d", AIUsage.created_at)
    if name == "month":
        return func.strftime("%Y-%m", AIUsage.created_at)
    raise HTTPException(400, f"Unknown dimension: {name}")


def _metric_expr(name: str):
    if name == "count":
        return func.count(AIUsage.id)
    if name == "cost":
        return func.coalesce(func.sum(AIUsage.cost_usd), 0.0)
    if name == "tokens_in":
        return func.coalesce(func.sum(AIUsage.tokens_in), 0)
    if name == "tokens_out":
        return func.coalesce(func.sum(AIUsage.tokens_out), 0)
    if name == "tokens":
        return func.coalesce(func.sum(AIUsage.tokens_in + AIUsage.tokens_out), 0)
    raise HTTPException(400, f"Unknown metric: {name}")


def _apply_range(q, since: Optional[str], until: Optional[str]):
    if since:
        q = q.filter(AIUsage.created_at >= since)
    if until:
        q = q.filter(AIUsage.created_at <= until)
    return q


# ── Raw rows ──────────────────────────────────────────────────────────────────

@router.get("/usage")
def list_usage(
    usage_type: Optional[str] = None,
    provider_type: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    q = db.query(AIUsage)
    if usage_type:
        q = q.filter(AIUsage.usage_type == usage_type)
    if provider_type:
        q = q.filter(AIUsage.provider_type == provider_type)
    q = _apply_range(q, since, until)
    rows = q.order_by(AIUsage.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "usage_type": r.usage_type,
            "provider_type": r.provider_type,
            "provider_name": r.provider_name,
            "model": r.model,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "cost_usd": r.cost_usd,
            "document_id": r.document_id,
            "status": r.status,
            "detail": r.detail,
        }
        for r in rows
    ]


# ── Dashboard summary ──────────────────────────────────────────────────────────

@router.get("/usage/summary")
def usage_summary(
    since: Optional[str] = None,
    until: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Totals + breakdowns by usage_type, provider, model and day."""
    base = _apply_range(db.query(AIUsage), since, until)

    totals = base.with_entities(
        func.count(AIUsage.id),
        func.coalesce(func.sum(AIUsage.cost_usd), 0.0),
        func.coalesce(func.sum(AIUsage.tokens_in), 0),
        func.coalesce(func.sum(AIUsage.tokens_out), 0),
    ).one()

    def breakdown(dim: str):
        expr = _dim_expr(dim)
        rows = (
            _apply_range(db.query(
                expr.label("key"),
                func.count(AIUsage.id),
                func.coalesce(func.sum(AIUsage.cost_usd), 0.0),
                func.coalesce(func.sum(AIUsage.tokens_in + AIUsage.tokens_out), 0),
            ), since, until)
            .group_by(expr)
            .all()
        )
        return [
            {"key": r[0], "count": r[1], "cost": float(r[2] or 0), "tokens": int(r[3] or 0)}
            for r in rows
        ]

    return {
        "total_calls": totals[0],
        "total_cost": float(totals[1] or 0),
        "total_tokens_in": int(totals[2] or 0),
        "total_tokens_out": int(totals[3] or 0),
        "by_type": sorted(breakdown("usage_type"), key=lambda x: -x["count"]),
        "by_provider": sorted(breakdown("provider_name"), key=lambda x: -x["cost"]),
        "by_model": sorted(breakdown("model"), key=lambda x: -x["cost"]),
        "by_day": sorted(breakdown("day"), key=lambda x: (x["key"] or "")),
    }


# ── Generic pivot ──────────────────────────────────────────────────────────────

@router.get("/usage/pivot")
def usage_pivot(
    row: str = Query("usage_type"),
    col: str = Query("provider_name"),
    metric: str = Query("count"),
    since: Optional[str] = None,
    until: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """2-D pivot: group by row × col, aggregate `metric`. Returns a dense matrix."""
    row_e, col_e, metric_e = _dim_expr(row), _dim_expr(col), _metric_expr(metric)

    rows = (
        _apply_range(db.query(row_e, col_e, metric_e), since, until)
        .group_by(row_e, col_e)
        .all()
    )

    row_keys: list = []
    col_keys: list = []
    cells: dict = {}
    for rk, ck, val in rows:
        rk = rk if rk is not None else "—"
        ck = ck if ck is not None else "—"
        if rk not in cells:
            cells[rk] = {}
            row_keys.append(rk)
        if ck not in col_keys:
            col_keys.append(ck)
        cells[rk][ck] = float(val or 0)

    row_keys.sort()
    col_keys.sort()
    matrix = [[cells.get(rk, {}).get(ck, 0.0) for ck in col_keys] for rk in row_keys]
    row_totals = [sum(r) for r in matrix]
    col_totals = [sum(matrix[i][j] for i in range(len(row_keys))) for j in range(len(col_keys))]

    return {
        "row": row, "col": col, "metric": metric,
        "row_keys": row_keys, "col_keys": col_keys,
        "matrix": matrix,
        "row_totals": row_totals,
        "col_totals": col_totals,
        "grand_total": sum(row_totals),
    }


@router.delete("/usage")
def clear_usage(db: Session = Depends(get_db)):
    n = db.query(AIUsage).delete()
    db.commit()
    return {"deleted": n}
