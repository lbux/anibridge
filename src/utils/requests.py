"""Selective SSL Verification for Requests Module."""

import warnings
from urllib.parse import urlparse

import requests
from urllib3.exceptions import InsecureRequestWarning

from src import log

__all__ = ["SelectiveVerifySession"]


class SelectiveVerifySession(requests.Session):
    """Session that selectively disables SSL verification for whitelisted domains."""

    def __init__(self, whitelist=None) -> None:
        """Initialize the session with a whitelist of domains."""
        super().__init__()
        self.whitelist = set(whitelist or [])
        if self.whitelist:
            formatted = ", ".join([f"$$'{d}'$$" for d in sorted(self.whitelist)])
            log.debug("SSL verify disabled for domains: %s", formatted)

    def request(self, method, url, *_, **kwargs):
        """Override the request method to selectively disable SSL verification."""
        domain = urlparse(url).hostname
        # Disable SSL verification for whitelisted domains
        if domain in self.whitelist:
            kwargs["verify"] = False
            # Suppress SSL warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", InsecureRequestWarning)
                try:
                    return super().request(method, url, **kwargs)
                except Exception as e:
                    log.exception(
                        "Error during request to $$'%s'$$: %s",
                        domain,
                        e,
                    )
                    raise
        return super().request(method, url, *_, **kwargs)
