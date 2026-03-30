from typing import TypeAlias


class Json(object):
    String: TypeAlias = str
    Number: TypeAlias = int | float
    Boolean: TypeAlias = bool
    Null: TypeAlias = None
    Array: TypeAlias = list["Json.Value"]
    Object: TypeAlias = dict[String, "Json.Value"]
    Value: TypeAlias = String | Number | Boolean | Null \
    | Array | Object | list[Object]
