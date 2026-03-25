from typing import Optional, Self
import os
import enum
from .namedstring import NamedString


class EnvEnum(enum.StrEnum):
    def __get__(self, instance: Optional[Self], owner: type[Self]) -> NamedString:
        value = NamedString(self.value, os.environ.get(self) or "")
        if not value:
            missing = [
                name.value for name in owner
                if not os.environ.get(name.value)
            ]
            raise RuntimeError(f"Some environment variables are missing: {' ,'.join(missing)}.")
        return value
