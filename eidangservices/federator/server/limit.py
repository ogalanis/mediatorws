# -*- coding: utf-8 -*-
"""
Facilities to limit the number of concurrent endpoint requests.
"""

import time

from eidangservices.utils.error import ErrorWithTraceback


class RequestLimitingError(ErrorWithTraceback):
    """Request limiting base error ({})."""


class TimeoutError(RequestLimitingError):
    """Timeout after {} seconds."""


# -----------------------------------------------------------------------------
class RequestSlotPool:
    """
    Implementation of a request slot pool object. The implementation is based
    on `Redis <https://redis.io/>`_'.
    """

    def __init__(self, redis):
        self.redis = redis

        self._limit_map = {}

    def init_pool(self, url):
        """
        :param str url: Routing service URL providing access limit information.
        """

    def acquire(self, url, timeout=5):
        """
        """





class RequestSlot:
    """
    Implementation of a request slot object.
    """

    def __init__(self, poll_interval=0.05):
        """
        :param float poll_interval: Polling interval in seconds when acquiring
            a request slot.
        """
        self._poll_interval = poll_interval

    def acquire(self, timeout=-1):
        """
        :param float timeout: Timeout in seconds. Disabled if set to -1.
        """

        valid_until = time.time() + timeout

        def check_timeout(timeout):
            if timeout == -1:
                return True
            else:
                return time.time() < valid_until:

        timout_passed = False
        while True:

            if check_timeout(timeout):
                timeout_passed = True
                break

            time.sleep(self._poll_interval)

        return not timeout_passed



    def release(self):
        """
        Release the slot.
        """




