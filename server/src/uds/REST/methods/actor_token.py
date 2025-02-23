# -*- coding: utf-8 -*-

#
# Copyright (c) 2021 Virtual Cable S.L.U.
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
import typing

from django.utils.translation import gettext_lazy as _

from uds.core import types, consts
from uds.core.types import permissions
from uds.core.util.log import LogLevel
from uds.models import Server
from uds.REST.exceptions import NotFound, RequestError
from uds.REST.model import ModelHandler

if typing.TYPE_CHECKING:
    from django.db.models import Model

logger = logging.getLogger(__name__)

# Enclosed methods under /osm path


class ActorTokens(ModelHandler):
    model = Server
    model_filter = {'type': types.servers.ServerType.ACTOR}

    table_title = typing.cast(str, _('Actor tokens'))
    table_fields = [
        # {'token': {'title': _('Token')}},
        {'stamp': {'title': _('Date'), 'type': 'datetime'}},
        {'username': {'title': _('Issued by')}},
        {'host': {'title': _('Origin')}},
        {'hostname': {'title': _('Hostname')}},
        {'pre_command': {'title': _('Pre-connect')}},
        {'post_command': {'title': _('Post-Configure')}},
        {'runonce_command': {'title': _('Run Once')}},
        {'log_level': {'title': _('Log level')}},
    ]

    def item_as_dict(self, item_: 'Model') -> typing.Dict[str, typing.Any]:
        item = typing.cast(Server, item_)
        data = item.data or {}
        log_level_int = data.get('log_level', 2)
        if log_level_int < 10000:  # Old log level
            log_level = LogLevel.fromActorLevel(log_level_int).name
        else:
            log_level = LogLevel(log_level_int).name
        return {
            'id': item.token,
            'name': str(_('Token isued by {} from {}')).format(item.username, item.hostname or item.ip),
            'stamp': item.stamp,
            'username': item.username,
            'ip': item.ip,
            'host': f'{item.ip} - {data.get("mac")}',
            'hostname': item.hostname,
            'pre_command': data.get('pre_command', ''),
            'post_command': data.get('post_command', ''),
            'runonce_command': data.get('runonce_command', ''),
            'log_level': log_level,
        }

    def delete(self) -> str:
        """
        Processes a DELETE request
        """
        if len(self._args) != 1:
            raise RequestError('Delete need one and only one argument')

        self.ensureAccess(
            self.model(), permissions.PermissionType.ALL, root=True
        )  # Must have write permissions to delete

        try:
            self.model.objects.get(token=self._args[0]).delete()
        except self.model.DoesNotExist:
            raise NotFound('Element do not exists') from None

        return consts.OK
