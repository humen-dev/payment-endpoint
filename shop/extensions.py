from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# `expire_on_commit=False` keeps loaded objects usable after a commit without a new
# query. The payment flow relies on it: it commits, then calls the provider outside
# of any transaction.
db = SQLAlchemy(model_class=Base, session_options={"expire_on_commit": False})
