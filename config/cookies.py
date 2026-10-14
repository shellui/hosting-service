"""Names for Django's session and CSRF cookies.

``__Host-`` cookies are host-only. Browsers reject them when a Domain attribute
is present. The prefix also requires Secure, so plain HTTP keeps the historical
names and Django admin on http://localhost still receives a cookie.
"""


def cookie_name(base: str, *, secure: bool) -> str:
    if secure:
        return f'__Host-{base}'
    return base
