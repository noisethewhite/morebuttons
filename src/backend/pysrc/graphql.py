from typing import cast, TypeVar
import requests
import pydantic
import dataclasses
from .environment import Environment
from .strict_json import Json


@dataclasses.dataclass
class _DC_T(object):
    pass


_DC = TypeVar("_DC", bound=_DC_T)


class GraphQL:
    @staticmethod
    def send(
        shop_domain: str,
        access_token: str,
        query: str,
        variables: Json.Object = {}
    ) -> Json.Value:
        resp = requests.post(
            url=f"https://{shop_domain}/admin/api/{Environment.shopify_api_version}/graphql.json",
            headers={
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json"
            },
            json={
                "query": query,
                "variables": { k: v for k, v in variables.items() if v is not None }
            },
            timeout=20
        )
        resp.raise_for_status()
        return cast(Json.Value, resp.json())

    @staticmethod
    def dict2dc(data: Json.Object, dc: type[_DC]) -> _DC:
        allowed = [k.name for k in dataclasses.fields(dc)]
        slim = {k: data[k] for k in allowed if k in data}
        return pydantic.TypeAdapter(dc).validate_python(slim)
