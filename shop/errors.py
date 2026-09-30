from http import HTTPStatus

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    """An expected error that is returned to the client as a JSON response."""

    status = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class BadRequest(ApiError):
    status = HTTPStatus.BAD_REQUEST


class Unauthorized(ApiError):
    status = HTTPStatus.UNAUTHORIZED


class NotFound(ApiError):
    status = HTTPStatus.NOT_FOUND


class Conflict(ApiError):
    status = HTTPStatus.CONFLICT


class Unprocessable(ApiError):
    status = HTTPStatus.UNPROCESSABLE_ENTITY


class BadGateway(ApiError):
    status = HTTPStatus.BAD_GATEWAY


def _error_response(code: str, message: str, status: int):
    return jsonify(error=code, message=message), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return _error_response(error.code, error.message, error.status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        code = (error.name or "error").lower().replace(" ", "_")
        return _error_response(code, error.description, error.code)
