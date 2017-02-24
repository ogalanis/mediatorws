#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Mediator server.

This file is part of the EIDA mediator/federator webservices.

"""

import tempfile

from flask import Flask
from flask_restful import Api


from mediator import settings

from mediator.server.routes.directquery import DQResource
from mediator.server.routes.misc import VersionResource


    
def main(
    debug=False, port=5001, routing=settings.DEFAULT_ROUTING_SERVICE,
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

    ## mediator endpoint
    
    # DQ query method (direct query)
    api.add_resource(
        DQResource, "%s%s" % (settings.EIDA_MEDIATOR_DQ_PATH, 
            settings.MEDIATOR_QUERY_METHOD_TOKEN))
    
    
    # version method
    api.add_resource(
        VersionResource, "%s%s" % (settings.EIDA_MEDIATOR_PATH, 
            settings.MEDIATOR_VERSION_METHOD_TOKEN))

        
    api.init_app(app)
    
    app.config.update(
        ROUTING=routing,
        PORT=port,
        TMPDIR=tmpdir
    )
    
    app.run(threaded=True, debug=debug, port=port)


if __name__ == '__main__':
    main()