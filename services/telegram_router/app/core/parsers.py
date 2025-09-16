"""
Argument parsing layer for portfolio commands.
Provides typed parsing with normalization and validation.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from typing import Optional, List, Tuple, Union
from .validator import parse_number


@dataclass
class PortfolioArgs:
    """Base class for portfolio command arguments."""
    pass


@dataclass
class AddArgs(PortfolioArgs):
    qty: Optional[Decimal] = None
    symbol: Optional[str] = None
    asset_class: Optional[str] = None


@dataclass
class RemoveArgs(PortfolioArgs):
    symbol: Optional[str] = None


@dataclass
class CashArgs(PortfolioArgs):
    amount: Optional[Decimal] = None


@dataclass
class BuyArgs(PortfolioArgs):
    qty: Optional[Decimal] = None
    symbol: Optional[str] = None
    price_ccy: Optional[Decimal] = None


@dataclass
class SellArgs(PortfolioArgs):
    qty: Optional[Decimal] = None
    symbol: Optional[str] = None
    price_ccy: Optional[Decimal] = None


@dataclass
class AllocationArgs(PortfolioArgs):
    etf_pct: Optional[int] = None
    stock_pct: Optional[int] = None
    crypto_pct: Optional[int] = None


@dataclass
class RenameArgs(PortfolioArgs):
    symbol: Optional[str] = None
    nickname: Optional[str] = None


@dataclass
class TxArgs(PortfolioArgs):
    limit: Optional[int] = None


# Asset class normalization mapping
ASSET_CLASS_MAPPING = {
    'stock': 'stock',
    'stocks': 'stock',
    'share': 'stock',
    'shares': 'stock',
    'equity': 'stock',
    'equities': 'stock',
    'etf': 'etf',
    'etfs': 'etf',
    'fund': 'etf',
    'funds': 'etf',
    'crypto': 'crypto',
    'cryptocurrency': 'crypto',
    'coin': 'crypto',
    'coins': 'crypto',
    'bitcoin': 'crypto',
    'btc': 'crypto'
}


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol to uppercase and clean format."""
    return symbol.strip().upper()


def normalize_asset_class(asset_class: str) -> Optional[str]:
    """Normalize asset class using synonym mapping."""
    return ASSET_CLASS_MAPPING.get(asset_class.lower().strip())


def parse_decimal(value: str) -> Optional[Decimal]:
    """Parse decimal with EU format support (comma or dot)."""
    if not value:
        return None

    try:
        # Use existing parse_number and convert to Decimal
        float_val = parse_number(value)
        if float_val is None:
            return None
        return Decimal(str(float_val))
    except (InvalidOperation, ValueError):
        return None


def parse_add_command(text: str) -> AddArgs:
    """Parse /add command: qty symbol asset_class"""
    tokens = text.strip().split()

    args = AddArgs()

    if len(tokens) >= 1:
        args.qty = parse_decimal(tokens[0])

    if len(tokens) >= 2:
        args.symbol = normalize_symbol(tokens[1])

    if len(tokens) >= 3:
        args.asset_class = normalize_asset_class(tokens[2])

    return args


def parse_remove_command(text: str) -> RemoveArgs:
    """Parse /remove command: symbol"""
    tokens = text.strip().split()

    args = RemoveArgs()

    if len(tokens) >= 1:
        args.symbol = normalize_symbol(tokens[0])

    return args


def parse_cash_command(text: str) -> CashArgs:
    """Parse /cash_add or /cash_remove command: amount"""
    tokens = text.strip().split()

    args = CashArgs()

    if len(tokens) >= 1:
        args.amount = parse_decimal(tokens[0])

    return args


def parse_buy_command(text: str) -> BuyArgs:
    """Parse /buy command: qty symbol [price_ccy]"""
    tokens = text.strip().split()

    args = BuyArgs()

    if len(tokens) >= 1:
        args.qty = parse_decimal(tokens[0])

    if len(tokens) >= 2:
        args.symbol = normalize_symbol(tokens[1])

    if len(tokens) >= 3:
        args.price_ccy = parse_decimal(tokens[2])

    return args


def parse_sell_command(text: str) -> SellArgs:
    """Parse /sell command: qty symbol [price_ccy]"""
    tokens = text.strip().split()

    args = SellArgs()

    if len(tokens) >= 1:
        args.qty = parse_decimal(tokens[0])

    if len(tokens) >= 2:
        args.symbol = normalize_symbol(tokens[1])

    if len(tokens) >= 3:
        args.price_ccy = parse_decimal(tokens[2])

    return args


def parse_allocation_command(text: str) -> AllocationArgs:
    """Parse /allocation_edit command: stock_pct etf_pct crypto_pct"""
    tokens = text.strip().split()

    args = AllocationArgs()

    if len(tokens) >= 1:
        val = parse_decimal(tokens[0])
        args.stock_pct = int(val) if val is not None else None

    if len(tokens) >= 2:
        val = parse_decimal(tokens[1])
        args.etf_pct = int(val) if val is not None else None

    if len(tokens) >= 3:
        val = parse_decimal(tokens[2])
        args.crypto_pct = int(val) if val is not None else None

    return args


def parse_rename_command(text: str) -> RenameArgs:
    """Parse /rename command: symbol nickname"""
    # Handle quoted nicknames
    parts = text.strip().split(maxsplit=1)

    args = RenameArgs()

    if len(parts) >= 1:
        args.symbol = normalize_symbol(parts[0])

    if len(parts) >= 2:
        # Remove surrounding quotes if present
        nickname = parts[1].strip()
        if nickname.startswith('"') and nickname.endswith('"'):
            nickname = nickname[1:-1]
        elif nickname.startswith("'") and nickname.endswith("'"):
            nickname = nickname[1:-1]
        args.nickname = nickname

    return args


def parse_tx_command(text: str) -> TxArgs:
    """Parse /tx command: [limit]"""
    tokens = text.strip().split()

    args = TxArgs()

    if len(tokens) >= 1:
        try:
            args.limit = int(tokens[0])
        except ValueError:
            pass  # Invalid number, leave as None

    return args


# Command parser mapping
COMMAND_PARSERS = {
    '/add': parse_add_command,
    '/remove': parse_remove_command,
    '/cash_add': parse_cash_command,
    '/cash_remove': parse_cash_command,
    '/buy': parse_buy_command,
    '/sell': parse_sell_command,
    '/allocation_edit': parse_allocation_command,
    '/rename': parse_rename_command,
    '/tx': parse_tx_command,
}


def parse_command_args(command: str, text: str) -> PortfolioArgs:
    """Parse command arguments using appropriate parser."""
    parser = COMMAND_PARSERS.get(command)
    if parser:
        return parser(text)

    # Fallback for unknown commands
    return PortfolioArgs()