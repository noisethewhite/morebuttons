import flask
import heresy
from werkzeug.middleware.proxy_fix import ProxyFix

from .environment import Environment


@heresy.singleton
class Server(object):
    _app: flask.Flask

    def __init__(self) -> None:
        self._app = flask.Flask(
            __name__,
            template_folder="../../frontend/templates",
            static_folder="../../../dist"
        )
        self._app.secret_key = Environment.flask_secret_key
        # Heroku / reverse proxies: trust X-Forwarded-Proto so request.url_root is https://
        self._app.wsgi_app = ProxyFix(
            self._app.wsgi_app,
            x_for=1,
            x_proto=1,
            x_host=1,
            x_port=1,
            x_prefix=1,
        )

    @heresy.singletonproperty
    def app(self) -> flask.Flask:
        return self._app

    @heresy.singletonproperty
    def session_token(self) -> str: # type: ignore
        if isinstance(flask.g.session_token, str):
            return flask.g.session_token
        return ""

    @session_token.setter
    def session_token(self, token: str) -> None:
        flask.g.session_token = token

    @heresy.singletonproperty
    def shop_domain(self) -> str: # type: ignore
        if isinstance(flask.g.shop_domain, str):
            return flask.g.shop_domain
        return ""

    @shop_domain.setter
    def shop_domain(self, token: str) -> None:
        flask.g.shop_domain = token
