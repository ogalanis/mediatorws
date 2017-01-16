#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Federator server.

This file is part of the EIDA mediator/federator webservices.

"""

import tempfile

from flask import Flask
from flask_restful import Api


from federator import settings

from federator.server.routes.dataselect import DataselectResource
from federator.server.routes.station import StationResource
from federator.server.routes.version import DataselectVersionResource
from federator.server.routes.version import StationVersionResource


    
def main(
    debug=False, port=5000, routing=settings.DEFAULT_ROUTING_SERVICE,
    tmpdir=''):
    """Run Flask app."""

    errors = {
        'NODATA': {
            'message': "Empty dataset.",
            'status': 204,
        },
    }
    
    if tmpdir:
        tempfile.tempdir = tmpdir
    
    app = Flask(__name__)
    
    api = Api(errors=errors)

    ## station service endpoint
    
    # query method
    api.add_resource(
        StationResource, "%s%s" % (settings.FDSN_STATION_PATH, 
            settings.FDSN_QUERY_METHOD_TOKEN))
        
    # version method
    api.add_resource(
        StationVersionResource, "%s%s" % (settings.FDSN_STATION_PATH, 
            settings.FDSN_VERSION_METHOD_TOKEN))
        
    # application.wadl method

    ## dataselect service endpoint
    
    # query method
    api.add_resource(
        DataselectResource, "%s%s" % (settings.FDSN_DATASELECT_PATH, 
            settings.FDSN_QUERY_METHOD_TOKEN))
        
    # queryauth method
    
    # version method
    api.add_resource(
        DataselectVersionResource, "%s%s" % (settings.FDSN_DATASELECT_PATH, 
            settings.FDSN_VERSION_METHOD_TOKEN))
    
    # application.wadl method

    api.init_app(app)
    
    app.config.update(
        ROUTING=routing,
        PORT=port,
        TMPDIR=tmpdir
    )
    
    app.run(threaded=True, debug=debug, port=port)


if __name__ == '__main__':
    main()
