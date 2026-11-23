"""Create the initial Level 4 realm import in a private host directory."""

import argparse
import json
import os
from getpass import getpass
from pathlib import Path
from urllib.parse import urlsplit

AUDIENCE = "georest-api"
BROWSER_CLIENT = "georest-browser"
SCRIPT_CLIENT = "georest-script"


def audience_mapper():
    return {
        "name": "GeoREST API audience",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "config": {"included.custom.audience": AUDIENCE, "access.token.claim": "true", "id.token.claim": "false"},
    }


def realm_config(redirect_uris, secret):
    origins = set()
    for callback in redirect_uris:
        origin = urlsplit(callback)
        loopback = origin.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            origin.scheme != "https" and not (origin.scheme == "http" and loopback)
            or not origin.hostname or origin.username is not None or origin.fragment or "*" in callback
        ):
            raise ValueError("redirect URIs must be exact HTTPS URLs or local HTTP loopback URLs")
        origins.add(f"{origin.scheme}://{origin.netloc}")
    return {
        "realm": "georest", "enabled": True, "sslRequired": "all", "registrationAllowed": False,
        "roles": {"realm": [{"name": role} for role in ("viewer", "editor")]},
        "clients": [
            {
                "clientId": BROWSER_CLIENT, "protocol": "openid-connect", "publicClient": True,
                "standardFlowEnabled": True, "directAccessGrantsEnabled": False,
                "redirectUris": redirect_uris, "webOrigins": sorted(origins),
                "attributes": {"pkce.code.challenge.method": "S256"}, "protocolMappers": [audience_mapper()],
            },
            {
                "clientId": SCRIPT_CLIENT, "protocol": "openid-connect", "publicClient": False, "secret": secret,
                "standardFlowEnabled": False, "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": True, "protocolMappers": [audience_mapper()],
            },
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redirect-uri", required=True, action="append", help="Exact browser callback, repeatable")
    parser.add_argument("--output", type=Path, default=Path("config/local/keycloak/realm.json"))
    args = parser.parse_args()
    secret = os.environ.get("KEYCLOAK_CLIENT_SECRET") or getpass("Confidential client secret: ")
    if len(secret) < 24:
        parser.error("set a confidential client secret of at least 24 characters")
    try:
        realm = realm_config(args.redirect_uri, secret)
        args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt" and args.output.parent.stat().st_mode & 0o077:
            raise ValueError("use a private output directory with mode 0700 on POSIX")
        with args.output.open("x", encoding="utf-8") as destination:
            json.dump(realm, destination, indent=2)
            destination.write("\n")
        if os.name != "nt":
            args.output.chmod(0o644)  # The bind-mounted file must be readable by the Keycloak UID.
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
