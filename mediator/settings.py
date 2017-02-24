# -*- coding: utf-8 -*-
"""

EIDA Mediator settings.

This file is part of the EIDA mediator/federator webservices.

"""

import os


EIDA_NODES = {
    'gfz': {
        'name': '',
        'services': {
            'fdsn': {
                'server': 'http://geofon.gfz-potsdam.de',
                'station': True,
                'dataselect': True,
                'event': False}, 
            'eida': {
                'routing': {
                    'service': True,
                    'server': 'http://geofon.gfz-potsdam.de',
                    'static_file': ''
                    }
                }
            }
        },
    'odc': {
        'name': '',
        'services': {
            'fdsn': {
                'server': 'http://www.orfeus-eu.org',
                'station': True,
                'dataselect': True,
                'event': False}, 
            'eida': {
                'routing': {
                    'service': True,
                    'server': 'http://www.orfeus-eu.org',
                    'static_file': ''
                    }
                }
            }
        },
    'eth': {
        'name': '',
        'services': {
            'fdsn': {
                'server': 'http://eida.ethz.ch',
                'station': True,
                'dataselect': True,
                'event': True}, 
            'eida': {
                'routing': {
                    'service': True,
                    'server': 'http://eida.ethz.ch',
                    'static_file': ''
                    }
                }
            }
        },
    'resif': {
        'name': '',
        'services': {
            'fdsn': {
                'server': 'http://ws.resif.fr',
                'station': True,
                'dataselect': True,
                'event': False}, 
            'eida': {
                'routing': {
                    'service': False,
                    'static_file': 'http://ws.resif.fr/eida_routing.xml'
                    }
                }
            }
        },
    'ingv': {
        'name': '',
        'services': {
            'fdsn': {
                'server': 'http://webservices.rm.ingv.it',
                'station': True,
                'dataselect': True,
                'event': True}, 
            'eida': {
                'routing': {
                    'service': True,
                    'server': ' http://eida.ingv.it',
                    'static_file': ''
                    }
                }
            }
        },
    'bgr': {
        'name': '',
        'services': {
            'fdsn': {
                'server': 'http://eida.bgr.de',
                'station': True,
                'dataselect': True,
                'event': False}, 
            'eida': {
                'routing': {
                    'service': True,
                    'server': 'http://eida.bgr.de',
                    'static_file': ''
                    }
                }
            }
        },
    'lmu': {
        'name': '',
        'services': {
            'fdsn': {
                'server': 'http://erde.geophysik.uni-muenchen.de',
                'station': True,
                'dataselect': True,
                'event': False}, 
            'eida': {
                'routing': {
                    'service': True,
                    'server': 'http://erde.geophysik.uni-muenchen.de',
                    'static_file': ''
                    }
                }
            }
        },
    'ipgp': {
        'name': '',
        'services': {
            'fdsn': {
                'server': 'http://eida.ipgp.fr',
                'station': True,
                'dataselect': True,
                'event': False}, 
            'eida': {
                'routing': {
                    'service': True,
                    'server': 'http://eidaws.ipgp.fr',
                    'static_file': ''
                    }
                }
            }
        },
    'niep': {
        'name': '',
        'services': {
            'fdsn': {
                'server': 'http://eida-sc3.infp.ro',
                'station': True,
                'dataselect': True,
                'event': True}, 
            'eida': {
                'routing': {
                    'service': False,
                    'static_file': 'http://eida-routing.infp.ro/eidaws/routing/1/routing.xml'
                    }
                }
            }
        },
    'koeri': {
        'name': '',
        'services': {
            'fdsn': {
                'server': 'http://eida-service.koeri.boun.edu.tr',
                'station': True,
                'dataselect': True,
                'event': False}, 
            'eida': {
                'routing': {
                    'service': True,
                    'server': 'http://eida.koeri.boun.edu.tr',
                    'static_file': ''
                    }
                }
            }
        },
    'noa': {
        'name': '',
        'services': {
            'fdsn': {
                'server': 'http://eida.gein.noa.gr',
                'station': True,
                'dataselect': True,
                'event': False}, 
            'eida': {
                'routing': {
                    'service': True,
                    'server': 'http://eida.gein.noa.gr',
                    'static_file': ''
                    }
                }
            }
        },
    }

DEFAULT_ROUTING_SERVICE = 'gfz'

SERVER_NAME = 'EIDA Mediator (alpha)'
VERSION = '0.9.1'
SHARE_DIR = 'share'


FDSN_STATION_PATH = '/fdsnws/station/1/'
FDSN_DATASELECT_PATH = '/fdsnws/dataselect/1/'
FDSN_EVENT_PATH = '/fdsnws/event/1/'

EIDA_ROUTING_PATH = '/eidaws/routing/1/'

EIDA_MEDIATOR_PATH = '/eidaws/mediator/'

EIDA_MEDIATOR_DQ_PATH = '/eidaws/mediator/dq/'
EIDA_MEDIATOR_RQ_PATH = '/eidaws/mediator/rq/'
EIDA_MEDIATOR_AQ_PATH = '/eidaws/mediator/aq/'

MEDIATOR_QUERY_METHOD_TOKEN = 'query'
MEDIATOR_VERSION_METHOD_TOKEN = 'version'

# -----------


FDSN_QUERY_METHOD_TOKEN = 'query'
FDSN_VERSION_METHOD_TOKEN = 'version'
FDSN_WADL_METHOD_TOKEN = 'application.wadl'
FDSN_DATASELECT_QUERYAUTH_METHOD_TOKEN = 'queryauth'

FDSN_DATASELECT_VERSION = '1.1.0'
FDSN_STATION_VERSION = '1.1.0'

FDSN_WADL_DIR = SHARE_DIR
FDSN_DATASELECT_WADL_FILENAME = 'dataselect.wadl'
FDSN_STATION_WADL_FILENAME = 'station.wadl'

DATASELECT_MIMETYPE = 'application/vnd.fdsn.mseed'
STATION_MIMETYPE_XML = 'application/xml'
STATION_MIMETYPE_TEXT = 'text/plain'
VERSION_MIMETYPE = 'text/plain'
WADL_MIMETYPE = 'application/xml'


FDSN_DEFAULT_NO_CONTENT_ERROR_CODE = 204

FDSN_SERVICE_DOCUMENTATION_URI = 'http://www.fdsn.org/webservices/'


APP_ROOT = os.path.dirname(os.path.abspath(__file__))
APP_SHARE = os.path.join(APP_ROOT, SHARE_DIR)