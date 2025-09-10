from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


_EU_DECIMAL = re.compile(r"^(?P<sign>[+-]?)(?P<int>\d+)([,.](?P<frac>\d+))?$")
_PERCENT = re.compile(r"^(?P<sign>[+-]?)(?P<num>\d+(?:[,.]\d+)?)%?$")


def parse_number(token: str) -> Optional[float]:
    if token is None:
        return None
    token = token.strip().replace(" ", "")
    m = _EU_DECIMAL.match(token)
    if not m:
        return None
    sign = -1.0 if m.group("sign") == "-" else 1.0
    intp = m.group("int")
    frac = m.group("frac") or ""
    s = f"{intp}.{frac}" if frac != "" else intp
    try:
        return sign * float(s)
    except ValueError:
        return None


def parse_percent(token: str) -> Optional[float]:
    if token is None:
        return None
    token = token.strip().replace(" ", "")
    m = _PERCENT.match(token)
    if not m:
        return None
    sign = -1.0 if m.group("sign") == "-" else 1.0
    num = m.group("num").replace(",", ".")
    try:
        return sign * float(num)
    except ValueError:
        return None


def coerce_value(field: Dict[str, Any], token: str) -> Tuple[Optional[Any], Optional[str]]:
    t = field.get("type", "string")
    name = field.get("name", "arg")
    if t in ("number", "integer"):
        n = parse_number(token)
        if n is None:
            return None, f"{name}: not a number"
        if t == "integer":
            n = int(n)
        if "min" in field and n < field["min"]:
            return None, f"{name}: below min {field['min']}"
        if "max" in field and n > field["max"]:
            return None, f"{name}: above max {field['max']}"
        return n, None
    if t == "percent":
        p = parse_percent(token)
        if p is None:
            return None, f"{name}: not a percent"
        if "min" in field and p < field["min"]:
            return None, f"{name}: below min {field['min']}%"
        if "max" in field and p > field["max"]:
            return None, f"{name}: above max {field['max']}%"
        return p, None
    if t == "enum":
        allowed = field.get("values", [])
        if token not in allowed:
            return None, f"{name}: must be one of {allowed}"
        return token, None
    # string default
    return token, None


def validate_args(schema: List[Dict[str, Any]], tokens: List[str], got: Optional[Dict[str, Any]] = None, cmd_name: str = "") -> Tuple[Dict[str, Any], List[str], Optional[str]]:
    """
    Returns: (validated_args, missing_fields, error_text)
    Accepts partial tokens merged with existing 'got'.
    Special case: uppercase symbol for /buy /sell.
    """
    got = dict(got or {})
    values: Dict[str, Any] = dict(got)
    missing: List[str] = []
    errors: List[str] = []

    # Fill from tokens for missing-only fields in order
    token_idx = 0
    for field in schema:
        fname = field["name"]
        required = bool(field.get("required", False))
        if fname in values and values[fname] is not None:
            continue
        # many-list support
        if field.get("many"):
            min_items = int(field.get("min_items", 1))
            max_items = int(field.get("max_items", 100))
            items: List[Any] = []
            errs: List[str] = []
            while token_idx < len(tokens):
                tok = tokens[token_idx]
                token_idx += 1
                v, err = coerce_value(field, tok)
                if err:
                    errs.append(err)
                else:
                    items.append(v)
            if not items and required:
                missing.append(fname)
            if items and len(items) > max_items:
                errors.append(f"{fname}: too many (max {max_items})")
            if items and len(items) < min_items:
                errors.append(f"{fname}: too few (min {min_items})")
            if not errs and items:
                values[fname] = items
            elif errs:
                errors.extend(errs)
            continue

        tok = None
        if token_idx < len(tokens):
            tok = tokens[token_idx]
            token_idx += 1
        if tok is None:
            # default
            if not required and "default" in field and fname not in values:
                values[fname] = field.get("default")
                continue
            if required:
                missing.append(fname)
            continue
        v, err = coerce_value(field, tok)
        if err:
            errors.append(err)
        else:
            values[fname] = v

    # Post-process
    if cmd_name in ("/buy", "/sell", "/add", "/remove") and values.get("symbol"):
        sym = str(values["symbol"]).strip()
        values["symbol"] = sym.upper()

    if errors:
        return values, missing, "; ".join(errors)
    return values, missing, None
