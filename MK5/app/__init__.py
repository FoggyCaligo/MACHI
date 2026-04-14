from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flask import Flask


def create_app() -> Any:
    from flask import Flask
    from app.api import register_routes

    app = Flask(__name__, static_folder='static', static_url_path='/static')
    register_routes(app)
    return app
