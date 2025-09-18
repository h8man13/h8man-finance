"""Numeric utilities."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

QTY_PRECISION = Decimal("0.0001")
EUR_PRECISION = Decimal("0.01")


def q_qty(value: Decimal) -> Decimal:
    return value.quantize(QTY_PRECISION, rounding=ROUND_HALF_UP)


def q_eur(value: Decimal) -> Decimal:
    return value.quantize(EUR_PRECISION, rounding=ROUND_HALF_UP)


def ensure_positive(value: Decimal, message: str) -> Decimal:
    if value <= 0:
        raise ValueError(message)
    return value