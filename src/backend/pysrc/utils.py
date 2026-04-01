from __future__ import annotations

import dataclasses
from typing import TypeVar, Protocol, ClassVar
from pydantic import TypeAdapter, ValidationError
from decimal import Decimal, ROUND_HALF_UP
from .web_types import Json


class DataclassProtocol(Protocol):
    __dataclass_fields__: ClassVar[dict[str, dataclasses.Field[object]]]


_DC = TypeVar("_DC", bound=DataclassProtocol)
_T = TypeVar("_T")


class Utils(object):
    """Small helpers shared across backend modules."""


    WEIGHT_UNIT_LABEL: dict[str, str] = {
        "KILOGRAMS": "kg",
        "GRAMS": "g",
        "POUNDS": "lb",
        "OUNCES": "oz",
    }

    @staticmethod
    def dict2dc(data: Json.Object, dc: type[_DC]) -> _DC | None:
        """
        Map JSON object keys onto ``dc`` (a ``pydantic.dataclasses.dataclass``), then
        validate. Unknown top-level keys are dropped; nested dicts are still passed
        through for validation, where nested models should use ``extra='ignore'``.
        """
        try:
            allowed = [f.name for f in dataclasses.fields(dc)]
            slim = {k: data[k] for k in allowed if k in data}
            return TypeAdapter(dc).validate_python(slim)
        except (ValidationError, TypeError, ValueError):
            return None

    @staticmethod
    def to_float(val: object) -> float | None:
        if isinstance(val, (int, float, str)):
            try:
                return float(val)
            except:
                pass
        return None

    @staticmethod
    def chunks(items: list[_T], size: int) -> list[list[_T]]:
        return [items[i : i + size] for i in range(0, len(items), size)]

    @staticmethod
    def scale_money(amount: str, factor: Decimal) -> str:
        d = Decimal(amount)
        return str((d * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    @staticmethod
    def offset_money(amount: str, delta: Decimal) -> str:
        d = Decimal(amount) + delta
        if d < 0:
            d = Decimal(0)
        return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    @staticmethod
    def weight_unit_label(unit: str) -> str:
        return Utils.WEIGHT_UNIT_LABEL.get(unit, unit.lower())

    @staticmethod
    def fmt_weight_num(v: float) -> str:
        if abs(v - round(v)) < 1e-9:
            return str(int(round(v)))
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s
