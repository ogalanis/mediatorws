# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# This is <process.py>
# -----------------------------------------------------------------------------
#
# This file is part of EIDA NG webservices (eida-federator)
#
# eida-federator is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# eida-federator is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# ----
#
# Copyright (c) Daniel Armbruster (ETH), Fabian Euchner (ETH)
#
# REVISION AND CHANGES
# 2018/03/29        V0.1    Daniel Armbruster
# =============================================================================
"""
federator processing facilities
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from builtins import * # noqa

import collections
import datetime
import logging
import multiprocessing as mp
import os

from flask import current_app, stream_with_context, Response

from eidangservices import utils, settings
from eidangservices.federator.server.request import (
    binary_request, RoutingRequestHandler, GranularFdsnRequestHandler,
    NoContent, RequestsError)
from eidangservices.federator.server.task import (
    RawDownloadTask, StationTextDownloadTask, StationXMLNetworkCombinerTask)
from eidangservices.utils.error import ErrorWithTraceback
from eidangservices.utils.httperrors import NoDataError, InternalServerError
from eidangservices.utils.sncl import StreamEpoch


# TODO(damb): This is a note regarding the federator-registered mode.
# Processors using exclusively DownloadTask objects must perform a detailed
# logging to the log DB. Processors using Combiners delegate logging to the
# corresponding combiner tasks.

def demux_routes(routes):
    return [utils.Route(route.url, streams=[se]) for route in routes
            for se in route.streams]

# demux_routes ()

def group_routes_by(routes, key='network'):
    """
    Group routes by a certain :cls:`eidangservices.sncl.Stream` keyword.
    Combined keywords are also possible e.g. network.station. When combining
    keys the seperating character is `.`. Routes are demultiplexed.

    :param list routes: List of :cls:`eidangservices.utils.Route` objects
    :param str key: Key used for grouping.
    """
    SEP = '.'

    routes = demux_routes(routes)
    retval = collections.defaultdict(list)

    for route in routes:
        try:
            _key = getattr(route.streams[0].stream, key)
        except AttributeError as err:
            try:
                if SEP in key:
                    # combined key
                    _key = SEP.join(getattr(route.streams[0].stream, k)
                                    for k in key.split(SEP))
                else:
                    raise KeyError(
                        'Invalid separator. Must be {!r}.'.format(SEP))
            except (AttributeError, KeyError) as err:
                raise RequestProcessorError(err)

        retval[_key].append(route)

    return retval

# group_routes_by ()

def flatten_routes(grouped_routes):
    return [route for routes in grouped_routes.values() for route in routes]


class RequestProcessorError(ErrorWithTraceback):
    """Base RequestProcessor error ({})."""

class StreamingError(RequestProcessorError):
    """Error while streaming ({})."""

# -----------------------------------------------------------------------------
class RequestProcessor(object):
    """
    Abstract base class for request processors.
    """

    LOGGER = "flask.app.federator.request_processor"

    POOL_SIZE = 5
    DEFAULT_ENDTIME = datetime.datetime.utcnow()
    TIMEOUT_STREAMING = settings.EIDA_FEDERATOR_STREAMING_TIMEOUT

    def __init__(self, mimetype, query_params={}, stream_epochs=[], post=True,
                 **kwargs):
        self.mimetype = mimetype
        self.query_params = query_params
        self.stream_epochs = stream_epochs
        self.post = post

        self._routing_service = current_app.config['ROUTING_SERVICE']

        self.logger = logging.getLogger(
            self.LOGGER if kwargs.get('logger') is None
            else kwargs.get('logger'))

        self._pool = None
        self._results = []
        self._sizes = []

    # __init__ ()

    @staticmethod
    def create(service, *args, **kwargs):
        """Factory method for RequestProcessor object instances.

        :param str service: Service identifier.
        :param dict kwargs: A dictionary passed to the combiner constructors.
        :return: A concrete :cls:`RequestProcessor` implementation
        :rtype: :cls:`RequestProcessor`
        :raises KeyError: if an invalid format string was passed
        """
        if service == 'dataselect':
            return RawRequestProcessor(*args, **kwargs)
        elif service == 'station':
            return StationRequestProcessor.create(
                kwargs['query_params'].get('format', 'xml'), *args, **kwargs)
        elif service == 'wfcatalog':
            return WFCatalogRequestProcessor(*args, **kwargs)
        else:
            raise KeyError('Invalid RequestProcessor chosen.')

    # create ()

    def _route(self):
        """
        Create the routing table using the routing service provided.
        """
        routing_request = RoutingRequestHandler(
            self._routing_service, self.query_params,
            self.stream_epochs)

        req = (routing_request.post() if self.post else routing_request.get())
        self.logger.info("Fetching routes from %s" % routing_request.url)

        routing_table = []

        try:
            with binary_request(req) as fd:
                # parse the routing service's output stream; create a routing
                # table
                urlline = None
                stream_epochs = []

                while True:
                    line = fd.readline()

                    if not urlline:
                        urlline = line.strip()
                    elif not line.strip():
                        # set up the routing table
                        if stream_epochs:
                            routing_table.append(
                                utils.Route(url=urlline,
                                            streams=stream_epochs))
                        urlline = None
                        stream_epochs = []

                        if not line:
                            break
                    else:
                        stream_epochs.append(
                            StreamEpoch.from_snclline(
                                line, default_endtime=self.DEFAULT_ENDTIME))

        except NoContent as err:
            self.logger.warning(err)
            raise NoDataError()
        except RequestsError as err:
            self.logger.error(err)
            raise InternalServerError(service_id='federator')

        return routing_table

    # _route ()

    @property
    def streamed_response(self):
        """
        Return a streamed :cls:`flask.Response`.
        """
        self._request()

        # XXX(damb): Only return a streamed response as soon as valid data is
        # available. Use a timeout and process errors here.

        # TODO(damb): - Handle code 413.
        #             - merge implementation with __iter__

        result_with_data = False
        while True:
            _results = self._results
            for idx, result in enumerate(_results):
                if result.ready():
                    _result = result.get()
                    if _result.status_code == 200:
                        result_with_data = True
                    elif _result.status_code == 413:
                        try:
                            self._handle_413(_result)
                        except NotImplementedError as err:
                            self.logger.warning(
                                'HTTP status code 413 handling'
                                'is not implemented ({}).'.format(
                                    err))
                    else:
                        self._handle_error(_result)
                        self._sizes.append(0)
                        self._results.pop(idx)

            if result_with_data:
                break

            if (not self._results or datetime.datetime.utcnow() >
                self.DEFAULT_ENDTIME +
                    datetime.timedelta(seconds=self.TIMEOUT_STREAMING)):
                raise NoDataError()

        return Response(stream_with_context(self), mimetype=self.mimetype,
                        content_type=self.mimetype)

    # streamed_response ()

    def _handle_error(self, err):
        self.logger.error(str(err))

    def _handle_413(self, result):
        raise NotImplementedError

    def _request(self):
        """
        Template method.
        """
        raise NotImplementedError

    def __iter__(self):
        raise NotImplementedError

# class RequestProcessor


class RawRequestProcessor(RequestProcessor):
    """
    Federating request processor implementation controlling both the federated
    downloading process and the merging afterwards.
    """

    LOGGER = "flask.app.federator.request_processor_raw"

    POOL_SIZE = settings.EIDA_FEDERATOR_THREADS_DATASELECT
    CHUNK_SIZE = 1024

    def _request(self):
        """
        process a federated request
        """
        routes = self._route()
        self.logger.debug('Received routes: {}'.format(routes))
        routes = demux_routes(routes)

        pool_size = (len(routes) if
                     len(routes) < self.POOL_SIZE else self.POOL_SIZE)

        self.logger.debug('Init worker pool (size={}).'.format(pool_size))
        self._pool = mp.pool.ThreadPool(processes=pool_size)

        for route in routes:
            self.logger.debug(
                'Creating DownloadTask for {!r} ...'.format(
                    route))
            t = RawDownloadTask(
                GranularFdsnRequestHandler(
                    route.url,
                    route.streams[0],
                    query_params=self.query_params))
            result = self._pool.apply_async(t)
            self._results.append(result)

        self._pool.close()

    # _request ()

    def _handle_413(self, result):
        self.logger.info(
            'Handle endpoint HTTP status code 413 (url={}, '
            'stream_epochs={}).'.format(result.data.url,
                                        result.data.stream_epochs))
        # TODO(damb): To be implemented.
        raise NoDataError()

    def __iter__(self):
        """
        Make the processor *streamable*.
        """
        # TODO(damb): The processor has to write metadata to the log database.
        # Also in case of errors.

        def generate_chunks(fd, chunk_size=self.CHUNK_SIZE):
            while True:
                data = fd.read(chunk_size)
                if not data:
                    break
                yield data

        while True:
            r = self._results

            for idx, result in enumerate(r):
                if result.ready():
                    _result = result.get()
                    if _result.status_code != 200:
                        # TODO(damb): Implement stream_epoch splitting
                        self._handle_error(_result)
                        self._sizes.append(0)
                    elif _result.status_code == 413:
                        try:
                            self._handle_413(_result)
                        except NotImplementedError as err:
                            self.logger.warning(
                                'HTTP status code 413 handling'
                                'is not implemented ({}).'.format(
                                    err))
                    else:
                        self._sizes.append(_result.length)
                        self.logger.debug(
                            'Streaming from file {!r} (chunk_size={}).'.format(
                                _result.data, self.CHUNK_SIZE))
                        try:
                            with open(_result.data, 'rb') as fd:
                                for chunk in generate_chunks(fd):
                                    yield chunk
                        except Exception as err:
                            raise StreamingError(err)

                        self.logger.debug(
                            'Removing temporary file {!r} ...'.format(
                                _result.data))
                        try:
                            os.remove(_result.data)
                        except OSError as err:
                            RequestProcessorError(err)

                    self._results.pop(idx)

            if not self._results:
                break

        self._pool.close()
        self._pool.join()
        self.logger.debug('Result sizes: {}.'.format(self._sizes))
        self.logger.info(
            'Results successfully processed (Total bytes: {}).'.format(
                sum(self._sizes)))

    # __iter__ ()

# class RawRequestProcessor


class StationRequestProcessor(RequestProcessor):
    """
    Base class for federating fdsnws.station request processor. While routing
    this processor interprets the `level` query parameter in order to reduce
    the number of endpoint requests.

    This processor implementation implements federatation using a two-level
    approach.
    On the first level the processor maintains a worker pool (implemented by
    means of the python multiprocessing module). Special *CombiningTask* object
    instances are mapped to the pool managing the download for a certain
    network code. Before, we obtained the fully resolved stream epoch
    information (i.e. also the network code information) using the EIDA
    StationLite service.
    On a second level the RawCombinerTask implementations demultiplex the
    routing information, again. Multiple DownloadTask object instances
    (implemented using multiprocessing.pool.ThreadPool) are executed requesting
    granular stream epoch information (i.e. one task per fully resolved stream
    epoch).
    Combining tasks collect the information from their child downloading
    threads. As soon the information for an entire network code is fetched the
    resulting data is dumped to a pipe.
    """

    LOGGER = "flask.app.federator.request_processor_station"

    def __init__(self, mimetype, query_params={}, stream_epochs=[], post=True,
                 **kwargs):
        super().__init__(mimetype, query_params, stream_epochs, post, **kwargs)

        self._level = query_params.get('level')
        if self._level is None:
            raise RequestProcessorError("Missing parameter: 'level'.")

    # __init__ ()

    @staticmethod
    def create(response_format, *args, **kwargs):
        if response_format == 'xml':
            return StationXMLRequestProcessor(*args, **kwargs)
        elif response_format == 'text':
            return StationTextRequestProcessor(*args, **kwargs)
        else:
            raise KeyError('Invalid RequestProcessor chosen.')

    # create ()

    def _route(self):
        routes = super()._route()
        self.logger.debug('Received routes: {}'.format(routes))

        # reduce routes
        if self._level == 'network':
            # use only the first route for each network
            routes = dict((net, [_routes[0]])
                          for net, _routes in
                          group_routes_by(routes, key='network').items())
        elif self._level == 'station':
            # use only the first route for each station
            routes = [_routes[0] for _routes in
                      group_routes_by(routes, key='network.station').values()]
            # sort again by network
            routes = group_routes_by(routes, key='network')
        else:
            routes = group_routes_by(routes, key='network')

        self.logger.debug('Routes after level reduction: {!r}.'.format(routes))

        return routes

# class StationRequestProcessor


class StationXMLRequestProcessor(StationRequestProcessor):
    """
    This processor implementation implements fdsnws-station XML federatation
    using a two-level approach.

    On the first level the processor maintains a worker pool (implemented by
    means of the python multiprocessing module). Special *CombiningTask* object
    instances are mapped to the pool managing the download for a certain
    network code. Before, we obtained the fully resolved stream epoch
    information (i.e. also the network code information) using the EIDA
    StationLite service.
    On a second level the RawCombinerTask implementations demultiplex the
    routing information, again. Multiple DownloadTask object instances
    (implemented using multiprocessing.pool.ThreadPool) are executed requesting
    granular stream epoch information (i.e. one task per fully resolved stream
    epoch).
    Combining tasks collect the information from their child downloading
    threads. As soon the information for an entire network code is fetched the
    resulting data is dumped to a pipe.
    """
    CHUNK_SIZE = 1024
    MAX_TASKS_PER_CHILD = 2

    SOURCE = 'EIDA'
    HEADER = ('<?xml version="1.0" encoding="UTF-8"?>'
              '<FDSNStationXML xmlns="http://www.fdsn.org/xml/station/1" '
              'schemaVersion="1.0">'
              '<Source>{}</Source>'
              '<Created>{}</Created>')
    FOOTER = '</FDSNStationXML>'

    def _request(self):
        """
        Process a federated fdsnws-station XML request.
        """
        routes = self._route()

        pool_size = (len(routes) if
                     len(routes) < self.POOL_SIZE else self.POOL_SIZE)

        self.logger.debug('Init worker pool (size={}).'.format(pool_size))
        self._pool = mp.pool.Pool(processes=pool_size,
                                  maxtasksperchild=self.MAX_TASKS_PER_CHILD)

        for net, routes in routes.items():
            self.logger.debug(
                'Creating CombinerTask for {!r} ...'.format(net))
            t = StationXMLNetworkCombinerTask(
                routes, self.query_params, name=net)
            result = self._pool.apply_async(t)
            self._results.append(result)

    # _request ()

    def __iter__(self):
        """
        Make the processor *streamable*.
        """
        def generate_chunks(fd, chunk_size=self.CHUNK_SIZE):
            while True:
                data = fd.read(chunk_size)
                if not data:
                    break
                yield data

        while True:
            r = self._results
            for idx, result in enumerate(r):
                if result.ready():

                    _result = result.get()
                    if _result.status_code != 200:
                        self._handle_error(_result)
                        self._sizes.append(0)
                    elif _result.status_code == 413:
                        try:
                            self._handle_413(_result)
                        except NotImplementedError as err:
                            self.logger.warning(
                                'HTTP status code 413 handling'
                                'is not implemented ({}).'.format(
                                    err))
                    else:
                        if not sum(self._sizes):
                            yield self.HEADER.format(
                                self.SOURCE,
                                datetime.datetime.utcnow().isoformat())

                        self._sizes.append(_result.length)
                        self.logger.debug(
                            'Streaming from file {!r} (chunk_size={}).'.format(
                                _result.data, self.CHUNK_SIZE))
                        try:
                            with open(_result.data, 'r', encoding='utf-8') \
                                    as fd:
                                for chunk in generate_chunks(fd):
                                    yield chunk
                        except Exception as err:
                            raise StreamingError(err)

                        self.logger.debug(
                            'Removing temporary file {!r} ...'.format(
                                _result.data))
                        try:
                            os.remove(_result.data)
                        except OSError as err:
                            RequestProcessorError(err)

                    self._results.pop(idx)

            if not self._results:
                break

        yield self.FOOTER

        self._pool.close()
        self._pool.join()
        self.logger.debug('Result sizes: {}.'.format(self._sizes))
        self.logger.info(
            'Results successfully processed (Total bytes: {}).'.format(
                sum(self._sizes) + len(self.HEADER) - 4 + len(self.SOURCE) +
                len(datetime.datetime.utcnow().isoformat()) +
                len(self.FOOTER)))

    # __iter__ ()

# class StationXMLRequestProcessor


class StationTextRequestProcessor(StationRequestProcessor):
    """
    This processor implementation implements fdsnws-station text federatation.
    Data is fetched multithreaded from endpoints.
    """
    POOL_SIZE = settings.EIDA_FEDERATOR_THREADS_STATION_TEXT

    HEADER_NETWORK = '#Network|Description|StartTime|EndTime|TotalStations'
    HEADER_STATION = (
        '#Network|Station|Latitude|Longitude|'
        'Elevation|SiteName|StartTime|EndTime')
    HEADER_CHANNEL = (
        '#Network|Station|Location|Channel|Latitude|'
        'Longitude|Elevation|Depth|Azimuth|Dip|SensorDescription|Scale|'
        'ScaleFreq|ScaleUnits|SampleRate|StartTime|EndTime')

    def _request(self):
        """
        Process a federated fdsnws-station text request
        """
        routes = flatten_routes(self._route())

        pool_size = (len(routes) if
                     len(routes) < self.POOL_SIZE else self.POOL_SIZE)

        self.logger.debug('Init worker pool (size={}).'.format(pool_size))
        self._pool = mp.pool.ThreadPool(processes=pool_size)

        for route in routes:
            self.logger.debug(
                'Creating DownloadTask for {!r} ...'.format(
                    route))
            t = StationTextDownloadTask(
                GranularFdsnRequestHandler(
                    route.url,
                    route.streams[0],
                    query_params=self.query_params))
            result = self._pool.apply_async(t)
            self._results.append(result)

        self._pool.close()

    # _request ()

    def __iter__(self):
        """
        Make the processor *streamable*.
        """
        while True:
            r = self._results
            for idx, result in enumerate(r):
                if result.ready():

                    _result = result.get()
                    if _result.status_code != 200:
                        self._handle_error(_result)
                        self._sizes.append(0)
                    elif _result.status_code == 413:
                        try:
                            self._handle_413(_result)
                        except NotImplementedError as err:
                            self.logger.warning(
                                'HTTP status code 413 handling'
                                'is not implemented ({}).'.format(
                                    err))
                    else:

                        if not sum(self._sizes):
                            # add header
                            if self._level == 'network':
                                yield '{}\n'.format(self.HEADER_NETWORK)
                            elif self._level == 'station':
                                yield '{}\n'.format(self.HEADER_STATION)
                            elif self._level == 'channel':
                                yield '{}\n'.format(self.HEADER_CHANNEL)

                        self._sizes.append(_result.length)
                        self.logger.debug(
                            'Streaming from file {!r}.'.format(_result.data))
                        try:
                            with open(_result.data, 'r', encoding='utf-8') \
                                    as fd:
                                for line in fd:
                                    yield line
                        except Exception as err:
                            raise StreamingError(err)

                        self.logger.debug(
                            'Removing temporary file {!r} ...'.format(
                                _result.data))
                        try:
                            os.remove(_result.data)
                        except OSError as err:
                            RequestProcessorError(err)

                    self._results.pop(idx)

            if not self._results:
                break

        self._pool.close()
        self._pool.join()
        self.logger.debug('Result sizes: {}.'.format(self._sizes))
        self.logger.info(
            'Results successfully processed (Total bytes: {}).'.format(
                sum(self._sizes)))

    # __iter__ ()

# class StationTextRequestProcessor


class WFCatalogRequestProcessor(RequestProcessor):
    """
    Process a WFCatalog request.
    """
    LOGGER = "flask.app.federator.request_processor_wfcatalog"

    POOL_SIZE = settings.EIDA_FEDERATOR_THREADS_WFCATALOG
    CHUNK_SIZE = 1024

    JSON_LIST_START = '['
    JSON_LIST_END = ']'
    JSON_LIST_SEP = ','

    def _request(self):
        """
        process a federated fdsnws-station text request
        """
        routes = self._route()
        self.logger.debug('Received routes: {}'.format(routes))
        routes = demux_routes(routes)

        pool_size = (len(routes) if
                     len(routes) < self.POOL_SIZE else self.POOL_SIZE)

        self.logger.debug('Init worker pool (size={}).'.format(pool_size))
        self._pool = mp.pool.ThreadPool(processes=pool_size)

        for route in routes:
            self.logger.debug(
                'Creating DownloadTask for {!r} ...'.format(
                    route))
            t = RawDownloadTask(
                GranularFdsnRequestHandler(
                    route.url,
                    route.streams[0],
                    query_params=self.query_params))
            result = self._pool.apply_async(t)
            self._results.append(result)

        self._pool.close()

    # _request ()

    def _handle_413(self, result):
        self.logger.info(
            'Handle endpoint HTTP status code 413 (url={}, '
            'stream_epochs={}).'.format(result.data.url,
                                        result.data.stream_epochs))
        # TODO(damb): To be implemented.
        raise NoDataError()

    def __iter__(self):
        """
        Make the processor *streamable*.
        """
        def generate_chunks(fd, chunk_size=self.CHUNK_SIZE):
            _size = os.fstat(fd.fileno()).st_size
            # skip leading bracket (from JSON list)
            fd.seek(1)
            while True:
                buf = fd.read(chunk_size)
                if not buf:
                    break

                if fd.tell() == _size:
                    # skip trailing bracket (from JSON list)
                    buf = buf[:-1]

                yield buf

        while True:
            r = self._results
            for idx, result in enumerate(r):
                if result.ready():

                    _result = result.get()
                    # TODO(damb): Implement epoch splitting.
                    if _result.status_code != 200:
                        self._handle_error(_result)
                        self._sizes.append(0)
                    elif _result.status_code == 413:
                        try:
                            self._handle_413(_result)
                        except NotImplementedError as err:
                            self.logger.warning(
                                'HTTP status code 413 handling'
                                'is not implemented ({}).'.format(
                                    err))
                    else:

                        if not sum(self._sizes):
                            # add header
                            yield self.JSON_LIST_START

                        self.logger.debug(
                            'Streaming from file {!r} (chunk_size={}).'.format(
                                _result.data, self.CHUNK_SIZE))
                        try:
                            with open(_result.data, 'rb') as fd:
                                # skip leading bracket (from JSON list)
                                size = 0
                                for chunk in generate_chunks(fd,
                                                             self.CHUNK_SIZE):
                                    size += len(chunk)
                                    yield chunk

                            self._sizes.append(size)

                        except Exception as err:
                            raise StreamingError(err)

                        if len(self._results) > 1:
                            # append comma if not last stream epoch data
                            yield self.JSON_LIST_SEP

                        self.logger.debug(
                            'Removing temporary file {!r} ...'.format(
                                _result.data))
                        try:
                            os.remove(_result.data)
                        except OSError as err:
                            RequestProcessorError(err)

                    self._results.pop(idx)

            if not self._results:
                break

        yield self.JSON_LIST_END

        self._pool.close()
        self._pool.join()
        self.logger.debug('Result sizes: {}.'.format(self._sizes))
        self.logger.info(
            'Results successfully processed (Total bytes: {}).'.format(
                sum(self._sizes) + 2 + len(self._sizes)-1))

    # __iter__ ()

# class WFCatalogRequestProcessor


# ---- END OF <process.py> ----