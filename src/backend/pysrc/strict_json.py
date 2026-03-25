from typing import TypeAlias, Union


class Json(object):
    String: TypeAlias = str
    Number: TypeAlias = Union[int, float]
    Boolean: TypeAlias = bool
    Null: TypeAlias = None
    Array: TypeAlias = list["Json.Value"]
    Object: TypeAlias = dict[String, "Json.Value"]
    Value: TypeAlias = Union[
        String, Number, Boolean, Null, Array, Object
    ]
