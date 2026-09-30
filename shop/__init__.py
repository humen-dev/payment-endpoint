from flask import Flask

from shop.config import Config
from shop.errors import register_error_handlers
from shop.extensions import db
from shop.payments.routes import payments_blueprint


def create_app(config: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)

    db.init_app(app)
    app.register_blueprint(payments_blueprint)
    register_error_handlers(app)
    return app
