"""Bypass shared tile caching for requests carrying client credentials."""

from flask import has_request_context, request
from pygeoapi.provider.mvt_proxy import MVTProxyProvider


class CacheAwareMVTProxy(MVTProxyProvider):
    def __init__(self, provider_def):
        if has_request_context() and any(name in request.headers for name in ("Authorization", "Cookie")):
            data = provider_def["data"].replace("http://varnish", "http://martin:3000", 1)
            provider_def = {**provider_def, "data": data}
        super().__init__(provider_def)
