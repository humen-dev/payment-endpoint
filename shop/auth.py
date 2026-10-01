"""Authentication stub: the caller says who they are in a header.

A real service would read the user from a verified session or token instead.
"""

import uuid

from flask import request

from shop.errors import Unauthorized
from shop.extensions import db
from shop.models import User

USER_ID_HEADER = "X-User-Id"


def current_user_id() -> uuid.UUID:
    try:
        user_id = uuid.UUID(request.headers.get(USER_ID_HEADER, ""))
    except ValueError:
        raise Unauthorized(
            "unauthorized", f"Send a valid user id in the {USER_ID_HEADER} header."
        )

    if db.session.get(User, user_id) is None:
        raise Unauthorized("unauthorized", "Unknown user.")
    return user_id
