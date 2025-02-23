# -*- coding: utf-8 -*-

#
# Copyright (c) 2012-2022 Virtual Cable S.L.U.
# All rights reservem.
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
import typing

from django.utils.translation import gettext_noop as _

from uds.core import exceptions, types

from .remote_viewer_file import RemoteViewerFile
from .spice_base import BaseSpiceTransport

# Not imported at runtime, just for type checking
if typing.TYPE_CHECKING:
    from uds import models
    from uds.core import transports
    from uds.core.types.request import ExtendedHttpRequestWithUser

logger = logging.getLogger(__name__)


class SPICETransport(BaseSpiceTransport):
    """
    Provides access via SPICE to service.
    This transport can use an domain. If username processed by authenticator contains '@', it will split it and left-@-part will be username, and right password
    """
    isBase = False

    typeName = _('SPICE')
    typeType = 'SPICETransport'
    typeDescription = _('SPICE Protocol. Direct connection.')

    # useEmptyCreds = BaseSpiceTransport.useEmptyCreds
    # fixedName = BaseSpiceTransport.fixedName
    # fixedPassword = BaseSpiceTransport.fixedPassword
    serverCertificate = BaseSpiceTransport.serverCertificate
    fullScreen = BaseSpiceTransport.fullScreen
    usbShare = BaseSpiceTransport.usbShare
    autoNewUsbShare = BaseSpiceTransport.autoNewUsbShare
    smartCardRedirect = BaseSpiceTransport.smartCardRedirect
    sslConnection = BaseSpiceTransport.SSLConnection
    overridedProxy = BaseSpiceTransport.overridedProxy

    def getUDSTransportScript(
        self,
        userService: 'models.UserService',
        transport: 'models.Transport',
        ip: str,
        os: 'types.os.DetectedOsInfo',
        user: 'models.User',
        password: str,
        request: 'ExtendedHttpRequestWithUser',
    ) -> 'transports.TransportScript':
        try:
            userServiceInstance = userService.getInstance()
            con: typing.Optional[typing.MutableMapping[str, typing.Any]] = userServiceInstance.getConsoleConnection()
        except Exception:
            logger.exception('Error getting console connection data')
            raise
        
        logger.debug('Connection data: %s', con)
        if not con:
            raise exceptions.service.TransportError('No console connection data')

        port: str = con['port'] or '-1'
        secure_port: str = con['secure_port'] or '-1'

        r = RemoteViewerFile(
            con['address'],
            port,
            secure_port,
            con['ticket']['value'],
            con.get('ca', self.serverCertificate.value.strip()),
            con['cert_subject'],
            fullscreen=self.fullScreen.isTrue(),
        )
        r.proxy = self.overridedProxy.value.strip() or con.get('proxy', None)

        r.usb_auto_share = self.usbShare.isTrue()
        r.new_usb_auto_share = self.autoNewUsbShare.isTrue()
        r.smartcard = self.smartCardRedirect.isTrue()
        r.ssl_connection = self.sslConnection.isTrue()

        # if sso:  # If SSO requested, and when supported by platform
        #     userServiceInstance.desktopLogin(user, password, '')

        sp = {
            'as_file': r.as_file,
        }

        try:
            return self.getScript(os.os.os_name(), 'direct', sp)
        except Exception:
            return super().getUDSTransportScript(
                userService, transport, ip, os, user, password, request
            )

