"""Translate the private OPA decision into a Traefik ForwardAuth response."""

import json
import logging
import re
from http import HTTPStatus
from urllib.request import Request, urlopen

BEARER = re.compile(r"Bearer ([a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)", re.IGNORECASE)
DECISION_URL = "http://opa:8181/v1/data/georest/access/decision"
RESPONSES = {
    "allow": HTTPStatus.NO_CONTENT,
    "forbidden": HTTPStatus.FORBIDDEN,
    "unauthenticated": HTTPStatus.UNAUTHORIZED,
    "unavailable": HTTPStatus.SERVICE_UNAVAILABLE,
}


def authorize(environ, action):
    authorization = environ.get("HTTP_AUTHORIZATION", "")
    credential = BEARER.fullmatch(authorization) if len(authorization) <= 8192 else None
    if not credential:
        return HTTPStatus.UNAUTHORIZED

    payload = {
        "token": credential[1],
        "action": action,
        "method": environ.get("HTTP_X_FORWARDED_METHOD", ""),
        "path": environ.get("HTTP_X_FORWARDED_URI", "").partition("?")[0],
    }
    request = Request(DECISION_URL, data=json.dumps({"input": payload}).encode(),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=3) as response:
            result = json.loads(response.read(4096))["result"]
        return RESPONSES[result]
    except (OSError, ValueError, TypeError, KeyError):
        logging.warning("GeoREST received no usable OPA authorization decision")
        return HTTPStatus.SERVICE_UNAVAILABLE


def application(environ, start_response):
    action = environ["PATH_INFO"].removeprefix("/")
    if action == "health":
        status = HTTPStatus.NO_CONTENT
    elif action in {"read", "write"}:
        status = authorize(environ, action)
    else:
        status = HTTPStatus.NOT_FOUND

    headers = [("Cache-Control", "no-store"), ("Content-Type", "text/plain; charset=utf-8")]
    if status == HTTPStatus.UNAUTHORIZED:
        headers.append(("WWW-Authenticate", 'Bearer realm="georest"'))
    start_response(f"{status.value} {status.phrase}", headers)
    return [b""] if status == HTTPStatus.NO_CONTENT else [f"{status.phrase}\n".encode()]
