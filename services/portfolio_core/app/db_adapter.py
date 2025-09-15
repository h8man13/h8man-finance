"""SQLite adapter with Decimal support."""
import sqlite3
from decimal import Decimal


def adapt_decimal(value):
    """Convert Decimal to string for SQLite storage."""
    return str(value)


def convert_decimal(value):
    """Convert SQLite string back to Decimal."""
    return Decimal(value.decode())


# Register adapters
sqlite3.register_adapter(Decimal, adapt_decimal)  # Convert Decimal to SQLite
sqlite3.register_converter("DECIMAL", convert_decimal)  # Convert SQLite to Decimal