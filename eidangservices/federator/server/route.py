# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# This is <route.py>
# -----------------------------------------------------------------------------
#
# REVISION AND CHANGES
# 2017/10/19        V0.1    Daniel Armbruster; most of the code is based on
#                           https://github.com/GEOFON/fdsnws_scripts/blob/ \
#                               master/fdsnws_fetch.py
# =============================================================================
"""
Federator routing facility
"""

import datetime
import json
import logging
import socket
import struct
import sys
import threading
import time

from multiprocessing.pool import ThreadPool

from eidangservices import settings
from eidangservices.federator.server.combine import Combiner

try:
    # Python 2.x
    import urllib2
    import urlparse
    import urllib
except ImportError:
    # Python 3.x
    import urllib.request as urllib2
    import urllib.parse as urlparse
    import urllib.parse as urllib

try:
    # Python 3.2 and earlier
    from xml.etree import cElementTree as ET  # NOQA
except ImportError:
    from xml.etree import ElementTree as ET  # NOQA


# -----------------------------------------------------------------------------
# TODO(damb): Provide a generic error class.
class Error(Exception):
    pass

class AuthNotSupported(Exception):
    pass


class TargetURL(object):
    def __init__(self, url, qp):
        self.__scheme = url.scheme
        self.__netloc = url.netloc
        self.__path = url.path.rstrip('query').rstrip('/')
        self.__qp = dict(qp)

    def wadl(self):
        path = self.__path + '/application.wadl'
        return urlparse.urlunparse((self.__scheme,
                                    self.__netloc,
                                    path,
                                    '',
                                    '',
                                    ''))

    def auth(self):
        path = self.__path + '/auth'
        return urlparse.urlunparse(('https',
                                    self.__netloc,
                                    path,
                                    '',
                                    '',
                                    ''))

    def post(self):
        path = self.__path + '/query'
        return urlparse.urlunparse((self.__scheme,
                                    self.__netloc,
                                    path,
                                    '',
                                    '',
                                    ''))

    def post_qa(self):
        path = self.__path + '/queryauth'
        return urlparse.urlunparse((self.__scheme,
                                    self.__netloc,
                                    path,
                                    '',
                                    '',
                                    ''))

    def post_params(self):
        return self.__qp.items()

    def __str__(self):
        return '<TargetURL: scheme=%s, netloc=%s, path=%s, qp=%s>' % \
            (self.__scheme, self.__netloc, self.__path, self.__qp)

# class TargetURL


class RoutingURL(object):

    GET_PARAMS = set((
        'network',
        'station',
        'location',
        'channel',
        'starttime',
        'endtime',
        'service',
        'alternative'))

    POST_PARAMS = set(('service', 'alternative'))

    def __init__(self, url, qp):
        self.__scheme = url.scheme
        self.__netloc = url.netloc
        self.__path = url.path.rstrip('query').rstrip('/')
        self.__qp = dict(qp)

    def get(self):
        path = self.__path + '/query'
        qp = [(p, v) for (p, v) in self.__qp.items() if p in self.GET_PARAMS]
        qp.append(('format', 'post'))
        query = urllib.urlencode(qp)
        return urlparse.urlunparse((self.__scheme,
                                    self.__netloc,
                                    path,
                                    '',
                                    query,
                                    ''))

    def post(self):
        path = self.__path + '/query'
        return urlparse.urlunparse((self.__scheme,
                                    self.__netloc,
                                    path,
                                    '',
                                    '',
                                    ''))

    def post_params(self):
        qp = [(p, v) for (p, v) in self.__qp.items() if p in self.POST_PARAMS]
        qp.append(('format', 'post'))
        return qp

    def target_params(self):
        return [(p, v) for (p, v) in self.__qp.items() 
                if p not in self.GET_PARAMS]

    def __str__(self):
        return '<RoutingURL: scheme=%s, netloc=%s, path=%s, qp=%s>' % \
            (self.__scheme, self.__netloc, self.__path, self.__qp)

# class RoutingURL

# -----------------------------------------------------------------------------
def connect(urlopen, url, data, timeout, count, wait):
    """connect/open a URL and retry in case the URL is not reachable"""
    # TODO(damb): Provide a global lock (.e. a lockfile) when retrying

    logger = logging.getLogger('federator.connect')
    n = 0

    while True:
        if n >= count:
            return urlopen(url, data, timeout)

        try:
            n += 1

            fd = urlopen(url, data, timeout)

            if fd.getcode() == 200 or fd.getcode() == 204:
                return fd

            logger.info(
                "retrying %s (%d) after %d seconds due to HTTP status code %d"
                % (url, n, wait, fd.getcode()))

            fd.close()
            time.sleep(wait)

        except urllib2.HTTPError as e:
            if e.code >= 400 and e.code < 500:
                raise

            logger.warn("retrying %s (%d) after %d seconds due to %s"
                % (url, n, wait, str(e)))

            time.sleep(wait)

        except (urllib2.URLError, socket.error) as e:
            logger.warn("retrying %s (%d) after %d seconds due to %s"
                % (url, n, wait, str(e)))

            time.sleep(wait)

# connect ()

# -----------------------------------------------------------------------------
def start_thread():
    # TODO(damb): use a logger @ module level
    logger = logging.getLogger('federator.route')
    logger.debug('Starting %s ...' % threading.current_thread().name)

# start_thread ()

# -----------------------------------------------------------------------------
class TaskBase(object):

    def __init__(self, logger):
        self.logger = logging.getLogger(logger)

    def __getstate__(self):
        # prevent pickling errors for loggers
        d = dict(self.__dict__)
        if 'logger' in d.keys():
            d['logger'] = d['logger'].name
        return d

    # __getstate__ ()

    def __setstate__(self, d):
        if 'logger' in d.keys():
            d['logger'] = logging.getLogger(d['logger'])
            self.__dict__.update(d)

    # __setstate__ ()
    
    def __call__(self):
        raise NotImplementedError

# class TaskBase


class DownloadTask(TaskBase):

    LOGGER = 'federator.download'

    def __init__(self, url, sncls=[], **kwargs):
        super(DownloadTask, self).__init__(self.LOGGER)

        self.url = url
        self.sncls = sncls

        self._cred = kwargs.get('cred')
        self._authdata = kwargs.get('authdata')
        self._combiner = kwargs.get('combiner')
        self._timeout = kwargs.get('timeout')
        self._num_retries = kwargs.get('num_retries')
        self._retry_wait = kwargs.get('retry_wait')

    # __init__ () 

    def __call__(self):
        url_handlers = []

        if self._cred and self.url.post_qa() in self._cred:  
            # use static credentials
            query_url = self.url.post_qa()
            (user, passwd) = self._cred[query_url]
            mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
            mgr.add_password(None, query_url, user, passwd)
            h = urllib2.HTTPDigestAuthHandler(mgr)
            url_handlers.append(h)

        elif self._authdata:  # use the pgp-based auth method if supported
            wadl_url = self.url.wadl()
            auth_url = self.url.auth()
            query_url = self.url.post_qa()

            try:
                fd = connect(urllib2.urlopen, wadl_url, None, self._timeout,
                           self._num_retries, self._retry_wait)

                try:
                    root = ET.parse(fd).getroot()
                    ns = "{http://wadl.dev.java.net/2009/02}"
                    el = "resource[@path='auth']"

                    if root.find(".//" + ns + el) is None:
                        raise AuthNotSupported

                finally:
                    fd.close()

                self.logger("authenticating at %s" % auth_url)

                if not isinstance(self._authdata, bytes):
                    self._authdata = self._authdata.encode('utf-8')

                try:
                    fd = connect(urllib2.urlopen, auth_url, self._authdata,
                            self._timeout, self._num_retries, self._retry_wait)

                    try:
                        if fd.getcode() == 200:
                            up = fd.read()

                            if isinstance(up, bytes):
                                up = up.decode('utf-8')

                            try:
                                (user, passwd) = up.split(':')
                                mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
                                mgr.add_password(None, query_url, user, passwd)
                                h = urllib2.HTTPDigestAuthHandler(mgr)
                                url_handlers.append(h)

                            except ValueError:
                                self.logger.warn("invalid auth response: %s" %
                                        up)
                                # TODO(damb): raise a proper exception
                                return

                            self.logger.info(
                                    "authentication at %s successful"
                                    % auth_url)

                        else:
                            self.logger.warn(
                            "authentication at %s failed with HTTP "
                            "status code %d" % (auth_url, fd.getcode()))

                    finally:
                        fd.close()

                except (urllib2.URLError, socket.error) as e:
                    self.logger.warn("authentication at %s failed: %s" %
                            (auth_url, str(e)))
                    query_url = self.url.post()

            except (urllib2.URLError, socket.error, ET.ParseError) as e:
                self.logger.warn("reading %s failed: %s" % (wadl_url, str(e)))
                query_url = self.url.post()

            except AuthNotSupported:
                self.logger.info("authentication at %s is not supported"
                    % auth_url)

                query_url = self.url.post()

        else:  # fetch data anonymously
            query_url = self.url.post()

        opener = urllib2.build_opener(*url_handlers)

        i = 0
        n = len(self.sncls)

        while i < len(self.sncls):
            if n == len(self.sncls):
                self.logger.info("getting data from %s" % query_url)

            else:
                self.logger.debug("getting data from %s (%d%%..%d%%)"
                    % (query_url,
                       100*i/len(self.sncls),
                       min(100, 100*(i+n)/len(self.sncls))))

            #print('URL post_params: %s' % self.url.post_params())
            postdata = (''.join((p + '=' + str(v) + '\n')
                                for (p, v) in self.url.post_params()) +
                        ''.join(self.sncls[i:i+n]))

            #print(url)
            #print(postdata)

            self.logger.debug("postdata:\n%s" % postdata)
            
            if not isinstance(postdata, bytes):
                postdata = postdata.encode('utf-8')

            try:
                fd = connect(opener.open, query_url, postdata, self._timeout,
                           self._num_retries, self._retry_wait)

                try:
                    if fd.getcode() == 204:
                        self.logger.info("received no data from %s" %
                                query_url)

                    elif fd.getcode() != 200:
                        self.logger.warn(
                                "getting data from %s failed with HTTP status "
                                "code %d" % (query_url, fd.getcode()))

                        break

                    else:
                        size = 0

                        content_type = fd.info().get('Content-Type')
                        content_type = content_type.split(';')[0]

                        if (self._combiner and 
                                content_type == self._combiner.mimetype):

                            self._combiner.combine(fd)
                            size = self._combiner.buffer_size

                        else:
                            self.logger.warn(
                            "getting data from %s failed: unsupported "
                            "content type '%s'" % (query_url, content_type))

                            break

                        self.logger.info("got %d bytes (%s) from %s"
                            % (size, content_type, query_url))

                    i += n

                finally:
                    fd.close()

            except urllib2.HTTPError as e:
                if e.code == 413 and n > 1:
                    self.logger.warn("request too large for %s, splitting"
                        % query_url)

                    n = -(n//-2)

                else:
                    self.logger.warn("getting data from %s failed: %s"
                        % (query_url, str(e)))

                    break

            except (urllib2.URLError, socket.error, ET.ParseError) as e:
                self.logger.warn("getting data from %s failed: %s"
                    % (query_url, str(e)))

                break

    # __call__()

# class DownloadTask


class WebserviceRouter:
    """
    Implementation of the federator routing facility providing routing by means
    of a routing webservice.

    ----
    References:
    https://www.orfeus-eu.org/data/eida/webservices/routing/
    """

    LOGGER = 'federator.webservice_router'

    def __init__(self, url, query_params={}, postdata=None, dest=None, 
            timeout=settings.DEFAULT_ROUTING_TIMEOUT,
            num_retries=settings.DEFAULT_ROUTING_RETRIES,
            retry_wait=settings.DEFAULT_ROUTING_RETRY_WAIT,
            max_threads=settings.DEFAULT_ROUTING_NUM_DOWNLOAD_THREADS):

        self.logger = logging.getLogger(self.LOGGER)
        
        # TODO(damb): to be refactored
        self.url = url
        self.query_params = query_params
        self.postdata = postdata
        self.dest = dest
        self._cred = None
        self._authdata = None
        self.timeout = timeout
        self.num_retries = num_retries
        self.retry_wait = retry_wait


        self.threads = []
        query_format = query_params.get('format')
        if not query_format:
            # TODO(damb): raise a proper exception
            raise
        self._combiner = Combiner.create(query_format, qp=query_params)

        self._lock = threading.Lock()
        self.__routing_table = []
        self.__thread_pool = ThreadPool(processes=max_threads,
                initializer=start_thread)

    # __init__ ()

    @property
    def cred(self):
        return self._cred

    @cred.setter
    def cred(self, user, password):
        self._cred = (user, password)

    @property
    def authdata(self):
        return self._authdata

    def _route(self):
        """creates the routing table"""

        if self.postdata:
            # NOTE(damb): Uses the post_params method of a RoutingURL.
            query_url = self.url.post()
            self.postdata = (''.join((p + '=' + v + '\n')
                                for (p, v) in self.url.post_params()) +
                        self.postdata)

            if not isinstance(self.postdata, bytes):
                self.postdata = self.postdata.encode('utf-8')

        else:
            query_url = self.url.get()

        self.logger.info("getting routes from %s" % query_url)

        try:
            fd = connect(urllib2.urlopen, query_url, self.postdata,
                    self.timeout, self.num_retries, self.retry_wait)

            try:
                if fd.getcode() == 204:
                    # TODO(damb): Implement a proper error handling - raising a
                    # simple error is not useful at all.
                    raise Error("received no routes from %s" % query_url)

                elif fd.getcode() != 200:
                    raise Error("getting routes from %s failed with HTTP status "
                                "code %d" % (query_url, fd.getcode()))

                else:
                    # parse routing service results and set up the routing
                    # table
                    urlline = None
                    sncls = []

                    while True:
                        line = fd.readline()

                        if isinstance(line, bytes):
                            line = line.decode('utf-8')

                        if not urlline:
                            urlline = line.strip()

                        elif not line.strip():
                            # set up the routing table
                            if sncls:
                                self.__routing_table.append((urlline, sncls))
                            urlline = None
                            sncls = []

                            if not line:
                                break

                        else:
                            sncls.append(line)

            finally:
                fd.close()

        except (urllib2.URLError, socket.error) as e:
            raise Error("getting routes from %s failed: %s" % (query_url,
                str(e)))
    
    # _route ()

    def _fetch(self):
        """fetches the results"""
        # NOTE(damb): This _fetch method is used in a different way than Andres
        # fetch method. The original _fetch function functionality is posponed
        # to DownloadTask objects.
        task_kwargs = {
                'cred': self.cred,
                'authdata': self.authdata,
                'combiner': self._combiner,
                'timeout': self.timeout,
                'num_retries': self.num_retries,
                'retry_wait': self.retry_wait
                }
        # create from the routing table content tasks
        for url, sncls in self.__routing_table:
            self.logger.debug(
                    'Setting up DownloadTask for <url=%s, sncls=%s> ...'
                    % (url, sncls))
            # create a TargetURL
            target_url = TargetURL(
                    urlparse.urlparse(url), 
                    self.url.target_params())
            # apply tasks to the thread pool
            self.__thread_pool.apply_async(DownloadTask(
                target_url,
                sncls,
                **task_kwargs))
        
        self.__thread_pool.close()
        self.__thread_pool.join()

    # _fetch ()

    def __call__(self):
        # route
        self._route()
        # fetch
        self._fetch()
        # dump
        self._combiner.dump(self.dest)

    # __call__ ()

# class WebserviceRouter 

# ---- END OF <route.py> ----