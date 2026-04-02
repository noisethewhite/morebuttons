import os
from functools import lru_cache


class FileLoader(object):
    _GRAPHQL_DIR: str = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "graphql")
    )

    @staticmethod
    @lru_cache(maxsize=None)
    def load(fname: str) -> str:
        path = os.path.join(FileLoader._GRAPHQL_DIR, fname)
        with open(path, encoding="utf-8") as f:
            return f.read()
