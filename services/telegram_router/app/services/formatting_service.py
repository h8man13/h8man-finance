from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from ..core.templates import euro, mdv2_blockquote, mdv2_expandable_blockquote


class FormattingService:
    """Formatting helpers shared across handlers while reusing core utilities."""

    def to_decimal(self, value: Any, default: Optional[Decimal] = None) -> Decimal:
        if default is None:
            default = Decimal("0")
        try:
            if value is None:
                return default
            if isinstance(value, Decimal):
                return value
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return default

    def decimal_str(self, value: Any) -> Optional[str]:
        try:
            if value is None:
                return None
            return str(Decimal(str(value)))
        except Exception:
            return None

    def format_quantity(self, value: Any) -> str:
        dec = self.to_decimal(value)
        if dec == 0:
            return "0"
        s = format(dec.normalize(), "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s or "0"

    def format_percent(self, value: Any, *, default: str = "n/a") -> str:
        if value is None:
            return default
        dec = self.to_decimal(value)
        try:
            return f"{int(dec)}%"
        except (ValueError, TypeError):
            return f"{dec}%"

    def format_signed_percent(
        self,
        value: Any,
        *,
        places: int = 1,
        default: str = "n/a",
    ) -> str:
        if value is None:
            return default
        try:
            num = float(value)
        except (TypeError, ValueError):
            return default
        return f"{num:+.{places}f}%"

    def format_eur(self, value: Any) -> str:
        dec = self.to_decimal(value)
        return euro(float(dec))

    def format_optional_eur(self, value: Any, *, default: str = "n/a") -> str:
        if value is None:
            return default
        try:
            return self.format_eur(value)
        except Exception:
            return default

    def format_error_note(self, message: str, *, default: str = "") -> str:
        if not message:
            return default
        try:
            return mdv2_blockquote([str(message)])
        except Exception:
            return default or str(message)

    def format_error_details(
        self,
        header: str,
        details: Iterable[str] | None,
        *,
        default: str = "",
    ) -> str:
        header_text = str(header) if header else ""
        items = [str(item) for item in (details or []) if str(item)]
        if header_text and items:
            try:
                return mdv2_expandable_blockquote([header_text], items)
            except Exception:
                pass
        if header_text:
            return self.format_error_note(header_text, default=default or header_text)
        return default

    def format_float(
        self,
        value: Any,
        *,
        precision: int = 4,
        strip_trailing: bool = True,
        default: str = "n/a",
    ) -> str:
        if value is None:
            return default
        try:
            num = float(value)
        except (TypeError, ValueError):
            return default
        formatted = f"{num:.{precision}f}"
        if strip_trailing:
            formatted = formatted.rstrip("0").rstrip(".")
        return formatted or "0"


