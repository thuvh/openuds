# -*- coding: utf-8 -*-
#
# Copyright (c) 2012-2022 Virtual Cable S.L.U.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
#    * Redistributions of source code must retain the above copyright notice,
#      this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above copyright notice,
#      this list of conditions and the following disclaimer in the documentation
#      and/or other materials provided with the distribution.
#    * Neither the name of Virtual Cable S.L.U. nor the names of its contributors
#      may be used to endorse or promote products derived from this software
#      without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
@author: Adolfo Gómez, dkmaster at dkmon dot com
"""
import logging
import sys
import typing
import traceback

from django import http
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.base import View

from uds.core import consts
from uds.core.util import modfinder

from . import processors, log
from .exceptions import (
    AccessDenied,
    HandlerError,
    NotFound,
    NotSupportedError,
    RequestError,
    ResponseError,
)
from .handlers import Handler
from .model import DetailHandler

# Not imported at runtime, just for type checking
if typing.TYPE_CHECKING:
    from uds.core.types.request import ExtendedHttpRequestWithUser

logger = logging.getLogger(__name__)

__all__ = ['Handler', 'Dispatcher']

AUTH_TOKEN_HEADER = 'X-Auth-Token'  # nosec: this is not a password, but a header name


class HandlerNode(typing.NamedTuple):
    """
    Represents a node on the handler tree
    """

    name: str
    handler: typing.Optional[typing.Type[Handler]]
    children: typing.MutableMapping[str, 'HandlerNode']
    
    def __str__(self) -> str:
        return f'HandlerNode({self.name}, {self.handler}, {self.children})'
    
    def __repr__(self) -> str:
        return str(self)
    
    def tree(self, level: int = 0) -> str:
        """
        Returns a string representation of the tree
        """
        ret = f'{"  " * level}{self.name} ({self.handler.__name__ if self.handler else "None"})\n'
        for child in self.children.values():
            ret += child.tree(level + 1)
        return ret


class Dispatcher(View):
    """
    This class is responsible of dispatching REST requests
    """

    # This attribute will contain all paths--> handler relations, filled at Initialized method
    services: typing.ClassVar[HandlerNode] = HandlerNode('', None, {})  # type: ignore

    @method_decorator(csrf_exempt)
    def dispatch(self, request: 'http.request.HttpRequest', *args, **kwargs):
        """
        Processes the REST request and routes it wherever it needs to be routed
        """
        request = typing.cast('ExtendedHttpRequestWithUser', request)  # Reconverting to typed request
        # Remove session from request, so response middleware do nothing with this
        del request.session

        # Now we extract method and possible variables from path
        path: typing.List[str] = kwargs['arguments'].split('/')
        del kwargs['arguments']

        # Transverse service nodes, so we can locate class processing this path
        service = Dispatcher.services
        full_path_lst: typing.List[str] = []
        # Guess content type from content type header (post) or ".xxx" to method
        content_type: str = request.META.get('CONTENT_TYPE', 'application/json').split(';')[0]

        while path:
            clean_path = path[0]
            # Skip empty path elements, so /x/y == /x////y for example (due to some bugs detected on some clients)
            if not clean_path:
                path = path[1:]
                continue

            if clean_path in service.children:  # if we have a node for this path, walk down
                service = service.children[clean_path]
                full_path_lst.append(path[0])  # Add this path to full path
                path = path[1:]  # Remove first part of path
            else:
                break  # If we don't have a node for this path, we are done

        full_path = '/'.join(full_path_lst)
        logger.debug("REST request: %s (%s)", full_path, content_type)

        # Now, service points to the class that will process the request
        # We get the '' node, that is the "current" node, and get the class from it
        cls: typing.Optional[typing.Type[Handler]] = service.handler
        if not cls:
            return http.HttpResponseNotFound('Method not found', content_type="text/plain")

        processor = processors.available_processors_mime_dict.get(content_type, processors.default_processor)(
            request
        )

        # Obtain method to be invoked
        http_method: str = request.method.lower() if request.method else ''

        # Path here has "remaining" path, that is, method part has been removed
        args = tuple(path)

        handler: typing.Optional[Handler] = None

        try:
            handler = cls(
                request,
                full_path,
                http_method,
                processor.processParameters(),
                *args,
                **kwargs,
            )
            operation: typing.Callable[[], typing.Any] = getattr(handler, http_method)
        except processors.ParametersException as e:
            logger.debug('Path: %s', full_path)
            logger.debug('Error: %s', e)

            log.logOperation(handler, 400, log.LogLevel.ERROR)
            return http.HttpResponseBadRequest(
                f'Invalid parameters invoking {full_path}: {e}',
                content_type="text/plain",
            )
        except AttributeError:
            allowedMethods = []
            for n in ['get', 'post', 'put', 'delete']:
                if hasattr(handler, n):
                    allowedMethods.append(n)
            log.logOperation(handler, 405, log.LogLevel.ERROR)
            return http.HttpResponseNotAllowed(allowedMethods, content_type="text/plain")
        except AccessDenied:
            log.logOperation(handler, 403, log.LogLevel.ERROR)
            return http.HttpResponseForbidden('access denied', content_type="text/plain")
        except Exception:
            log.logOperation(handler, 500, log.LogLevel.ERROR)
            logger.exception('error accessing attribute')
            logger.debug('Getting attribute %s for %s', http_method, full_path)
            return http.HttpResponseServerError('Unexcepected error', content_type="text/plain")

        # Invokes the handler's operation, add headers to response and returns
        try:
            response = operation()

            if not handler.raw:  # Raw handlers will return an HttpResponse Object
                response = processor.getResponse(response)
            # Set response headers
            response['UDS-Version'] = f'{consts.system.VERSION};{consts.system.VERSION_STAMP}'
            for k, val in handler.headers().items():
                response[k] = val

            # Log de operation on the audit log for admin
            # Exceptiol will also be logged, but with ERROR level
            log.logOperation(handler, response.status_code, log.LogLevel.INFO)
            return response
        except RequestError as e:
            log.logOperation(handler, 400, log.LogLevel.ERROR)
            return http.HttpResponseBadRequest(str(e), content_type="text/plain")
        except ResponseError as e:
            log.logOperation(handler, 500, log.LogLevel.ERROR)
            return http.HttpResponseServerError(str(e), content_type="text/plain")
        except NotSupportedError as e:
            log.logOperation(handler, 501, log.LogLevel.ERROR)
            return http.HttpResponseBadRequest(str(e), content_type="text/plain")
        except AccessDenied as e:
            log.logOperation(handler, 403, log.LogLevel.ERROR)
            return http.HttpResponseForbidden(str(e), content_type="text/plain")
        except NotFound as e:
            log.logOperation(handler, 404, log.LogLevel.ERROR)
            return http.HttpResponseNotFound(str(e), content_type="text/plain")
        except HandlerError as e:
            log.logOperation(handler, 500, log.LogLevel.ERROR)
            return http.HttpResponseBadRequest(str(e), content_type="text/plain")
        except Exception as e:
            log.logOperation(handler, 500, log.LogLevel.ERROR)
            # Get ecxeption backtrace
            trace_back = traceback.format_exc()
            logger.error('Exception processing request: %s', full_path)
            for i in trace_back.splitlines():
                logger.error('* %s', i)

            return http.HttpResponseServerError(str(e), content_type="text/plain")

    @staticmethod
    def registerClass(type_: typing.Type[Handler]) -> None:
        """
        Method to register a class as a REST service
        param type_: Class to be registered
        """
        if not type_.name:
            name = sys.intern(type_.__name__.lower())
        else:
            name = type_.name

        # Fill the service_node tree with the class
        service_node = Dispatcher.services  # Root path
        # If path, ensure that the path exists on the tree
        if type_.path:
            logger.info('Path: /%s/%s', type_.path, name)
            for k in type_.path.split('/'):
                intern_k = sys.intern(k)
                if intern_k not in service_node.children:
                    service_node.children[intern_k] = HandlerNode(k, None, {})
                service_node = service_node.children[intern_k]
        else:
            logger.info('Path: /%s', name)

        if name not in service_node.children:
            service_node.children[name] = HandlerNode(name, None, {})

        service_node.children[name] = service_node.children[name]._replace(handler=type_)

    # Initializes the dispatchers
    @staticmethod
    def initialize():
        """
        This imports all packages that are descendant of this package, and, after that,
        it register all subclases of Handler. (In fact, it looks for packages inside "methods" package, child of this)
        """
        logger.info('Initializing REST Handlers')
        # Our parent module "REST", because we are in "dispatcher"
        modName = __name__[: __name__.rfind('.')]

        def checker(x: typing.Type[Handler]) -> bool:
            # only register if final class, no inherited classes
            logger.info(
                'Checking %s - %s - %s', x.__name__, issubclass(x, DetailHandler), x.__subclasses__() == []
            )
            return not issubclass(x, DetailHandler) and not x.__subclasses__()

        # Register all subclasses of Handler
        modfinder.dynamicLoadAndRegisterPackages(
            Dispatcher.registerClass,
            Handler,
            modName=modName,
            checker=checker,
            packageName='methods',
        )       

Dispatcher.initialize()
