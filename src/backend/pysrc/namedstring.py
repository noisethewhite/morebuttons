import typing as t


class NamedString(str):
    _name: str

    def __new__(cls, name: str, value: str) -> t.Self:
        obj = super().__new__(cls, value)
        obj._name = name
        return obj

    @property
    def name(self) -> str:
        return self._name

    @property
    def value(self) -> str:
        return self
