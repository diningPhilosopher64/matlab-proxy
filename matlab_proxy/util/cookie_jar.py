import asyncio
from typing import Dict
from http.cookies import SimpleCookie, Morsel
from matlab_proxy.util import mwi

logger = mwi.logger.get()


class SimpleCookieJar:
    """
    A lightweight, in-memory cookie store.

    Its sole responsibility is to parse and store 'Set-Cookie' headers as Morsel objects.
    """

    def __init__(self):
        self._cookie_jar: Dict[str, Morsel] = {}
        logger.info("Cookie Jar Initialized")

    def _get_cookie_name(self, cookie: SimpleCookie) -> str:
        """
        Returns the name of the cookie.
        """
        return list(cookie.keys())[0]

    def update_from_response_headers(self, headers) -> None:
        """
        Parses 'Set-Cookie' headers from a response and stores the resulting
        cookie objects (Morsels).
        """
        for set_cookie_val in headers.getall("Set-Cookie", []):
            cookie = SimpleCookie()
            cookie.load(set_cookie_val)
            cookie_name = self._get_cookie_name(cookie)
            self._cookie_jar[cookie_name] = cookie[cookie_name]
            logger.debug(
                f"Stored cookie object for key '{cookie_name}'. Value: '{cookie[cookie_name]}'"
            )

    def get_cookies(self):
        """
        Returns a copy of the internal dictionary of stored cookie Morsels.
        """
        return list(self._cookie_jar.values())

    def get_dict(self) -> Dict[str, str]:
        """
        Returns the stored cookies as a simple dictionary of name-to-value strings,
        which is compatible with aiohttp's 'LooseCookies' type.
        """
        loose_cookies = {
            name: morsel.value for name, morsel in self._cookie_jar.items()
        }
        return loose_cookies

    def clear(self):
        """Clears all stored cookies."""
        logger.info("Cookie Jar Cleared")
        self._cookie_jar.clear()
