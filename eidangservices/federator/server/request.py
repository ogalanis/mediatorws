# -*- coding: utf-8 -*-
"""
EIDA federator request handling facilities
"""

import functools

from copy import deepcopy
from urllib.parse import urlparse, urlunparse

import requests

from eidangservices import settings, utils
from eidangservices.utils.schema import StreamEpochSchema
from eidangservices.federator import __version__


class RequestHandlerBase:
    """
    RequestHandler base class implementation. Provides bulk request handling
    facilities.
    """

    HEADERS = {"user-agent": "EIDA-Federator/" + __version__,
               # force no encoding, because eida-federator currently cannot
               # handle this
               "Accept-Encoding": ""}

    def __init__(self, url, query_params={}, stream_epochs=[]):
        """
        :param url: URL
        :type url: str or bytes
        :param dict query_params: Dictionary of query parameters
        :param list stream_epochs: List of
            :py:class:`eidangservices.utils.sncl.StreamEpoch` objects
        """

        if isinstance(url, bytes):
            url = url.decode('utf-8')
        url = urlparse(url)
        self._scheme = url.scheme
        self._netloc = url.netloc
        self._path = url.path.rstrip(
            settings.FDSN_QUERY_METHOD_TOKEN).rstrip('/')

        self._query_params = query_params
        self._stream_epochs = stream_epochs

    @property
    def url(self):
        return urlunparse(
            (self._scheme,
             self._netloc,
             '{}/{}'.format(self._path, settings.FDSN_QUERY_METHOD_TOKEN),
             '',
             '',
             ''))

    @property
    def stream_epochs(self):
        return self._stream_epochs

    @property
    def payload_get(self):
        raise NotImplementedError

    @property
    def payload_post(self):
        data = '\n'.join('{}={}'.format(p, v)
                         for p, v in self._query_params.items())

        return '{}\n{}'.format(
            data, '\n'.join(str(se) for se in self._stream_epochs))

    def get(self):
        raise NotImplementedError

    def post(self):
        return functools.partial(requests.post, self.url,
                                 data=self.payload_post, headers=self.HEADERS)

    def __str__(self):
        return ', '.join(["scheme={}".format(self._scheme),
                          "netloc={}".format(self._netloc),
                          "path={}.".format(self._path),
                          "qp={}".format(self._query_params),
                          "streams={}".format(
                              ', '.join(str(se)
                                        for se in self._stream_epochs))])

    def __repr__(self):
        return '<{}: {}>'.format(type(self).__name__, self)


class RoutingRequestHandler(RequestHandlerBase):
    """
    Representation of a `eidaws-routing` request handler.

    .. note::

        Since both `eidaws-routing` and `eida-stationlite` implement the same
        interface :py:class:`RoutingRequestHandler` may be used for both
        webservices.
    """

    QUERY_PARAMS = set(('service',
                        'level',
                        'minlatitude', 'minlat',
                        'maxlatitude', 'maxlat',
                        'minlongitude', 'minlon',
                        'maxlongitude', 'maxlon'))

    class GET:
        """
        Utility class emulating a GET request.
        """
        method = 'GET'

    def __init__(self, url, query_params={}, stream_epochs=[]):
        super().__init__(url, query_params, stream_epochs)

        self._query_params = dict(
            (p, v) for p, v in self._query_params.items()
            if p in self.QUERY_PARAMS)

        self._query_params['format'] = 'post'

    @property
    def payload_get(self):
        se_schema = StreamEpochSchema(many=True, context={'request': self.GET})

        qp = deepcopy(self._query_params)
        qp.update(utils.convert_sncl_dicts_to_query_params(
                  se_schema.dump(self._stream_epochs)))
        return qp

    def get(self):
        return functools.partial(requests.get, self.url,
                                 params=self.payload_get, headers=self.HEADERS)


class FdsnRequestHandler(RequestHandlerBase):
    """
    Representation of a FDSN webservice request handler.
    """

    QUERY_PARAMS = set(('service',
                        'nodata',
                        'minlatitude', 'minlat',
                        'maxlatitude', 'maxlat',
                        'minlongitude', 'minlon',
                        'maxlongitude', 'maxlon'))

    def __init__(self, url, query_params={}, stream_epochs=[]):
        super().__init__(url, query_params=query_params,
                         stream_epochs=stream_epochs)
        self._query_params = dict((p, v)
                                  for p, v in self._query_params.items()
                                  if p not in self.QUERY_PARAMS)


class GranularFdsnRequestHandler(FdsnRequestHandler):
    """
    Representation of a FDSN webservice request handler for granular
    single stream requests.
    """

    def __init__(self, url, stream_epoch, query_params={}):
        super().__init__(url, query_params, [stream_epoch])

    @property
    def payload_post(self):
        data = '\n'.join('{}={}'.format(p, v)
                         for p, v in self._query_params.items())
        return '{}\n{}'.format(data, self.stream_epochs[0])


BulkFdsnRequestHandler = FdsnRequestHandler
