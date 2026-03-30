from __future__ import annotations
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


class ComparisonSymbol:
    _SYMBOLS: dict[str, str] = {
        "LESS_THAN_OR_EQUAL_TO": "≤",
        "GREATER_THAN_OR_EQUAL_TO": "≥",
        "EQUAL_TO": "=",
        "LESS_THAN": "<",
        "GREATER_THAN": ">",
        "NOT_EQUAL_TO": "≠"
    }

    @classmethod
    def get(cls, symbol: str) -> str:
        return cls._SYMBOLS.get(symbol.upper(), symbol)


class CurrencySymbol(StrEnum):
    USD = "$"
    EUR = "€"
    GBP = "£"
    JPY = "¥"
    CAD = "C$"
    AUD = "A$"
    NZD = "NZ$"
    CHF = "CHF"
    SEK = "kr"
    NOK = "kr"
    DKK = "kr"
    PLN = "zł"
    CZK = "Kč"
    HUF = "Ft"
    RON = "lei"
    BGN = "лв"
    BRL = "R$"
    INR = "₹"
    KRW = "₩"
    CNY = "¥"
    ZAR = "R"
    AED = "د.إ"
    SAR = "﷼"
    ILS = "₪"
    TRY = "₺"


class Currency:
    _ZERO_DECIMAL_CURRENCIES: frozenset[str] = frozenset(
        "BIF CLP DJF GNF HUF ISK JPY KMF KRW PYG RWF VND VUV XAF XOF XPF".split()
    )
    _CURRENCY_PREFIX: frozenset[str] = frozenset(
        {"USD", "CAD", "AUD", "MXN", "SGD", "HKD", "NZD", "TWD", "PHP", "MYR", "THB"}
    )

    @staticmethod
    def _currency_symbol(code: str) -> str:
        if code in CurrencySymbol:
            return CurrencySymbol(code).value
        return code

    @classmethod
    def format_amount(cls, amount: str, currency_code: str) -> str:
        d = Decimal(amount)
        code = currency_code.upper().strip()
        if code in cls._ZERO_DECIMAL_CURRENCIES:
            q = d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            fmt = str(int(q))
        else:
            q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            fmt = f"{q:.2f}"
        sym = cls._currency_symbol(code)
        if code in cls._CURRENCY_PREFIX:
            return f"{sym}{fmt}"
        return f"{fmt} {sym}"

    @classmethod
    def format_range(cls, lo_amt: str, hi_amt: str, currency_code: str) -> str:
        code = currency_code.upper().strip()
        d = Decimal(lo_amt)
        d2 = Decimal(hi_amt)
        if code in cls._ZERO_DECIMAL_CURRENCIES:
            lo_s = str(int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
            hi_s = str(int(d2.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
        else:
            lo_s = f"{d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
            hi_s = f"{d2.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
        sym = cls._currency_symbol(code)
        if code in cls._CURRENCY_PREFIX:
            return f"{sym}{lo_s}–{sym}{hi_s}"
        return f"{lo_s}–{hi_s} {sym}"
