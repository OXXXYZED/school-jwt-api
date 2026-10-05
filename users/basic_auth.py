"""HTTP Basic credentials (RFC 7617): `Authorization: Basic base64(username:password)`.

Base64 is an encoding, not encryption: the login endpoint must be served over HTTPS.
"""

import base64

BASIC_AUTH_CHALLENGE = 'Basic realm="api", charset="UTF-8"'


class InvalidBasicCredentials(ValueError):
    pass


def decode_basic_credentials(encoded: str) -> tuple[str, str]:
    """Decode `base64(username:password)` into `(username, password)`.

    Decoding is strict (unlike `base64.b64decode` defaults, which silently drop
    characters outside the alphabet) and uses UTF-8, so non-ASCII passwords work.
    The password may contain ':' — only the first one separates the parts.
    """
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except ValueError as exc:  # binascii.Error, UnicodeDecodeError, non-ASCII input
        raise InvalidBasicCredentials("Credentials are not valid Base64-encoded UTF-8.") from exc

    username, separator, password = decoded.partition(":")
    if not separator or not username:
        raise InvalidBasicCredentials("Decoded credentials must have the form 'username:password'.")
    return username, password


def parse_basic_authorization(header: str) -> tuple[str, str] | None:
    """Return `(username, password)` from an Authorization header value.

    Returns None when the header is missing or uses another scheme (e.g. Bearer);
    raises InvalidBasicCredentials when it is a malformed Basic header.
    """
    scheme, _, encoded = header.strip().partition(" ")
    if scheme.lower() != "basic":
        return None
    return decode_basic_credentials(encoded.strip())
