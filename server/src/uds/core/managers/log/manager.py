# -*- coding: utf-8 -*-
#
# Copyright (c) 2012-2023 Virtual Cable S.L.U.
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
# import traceback
import typing
import logging

from uds.core.util import singleton
from uds.core.util.model import getSqlDatetime
from uds.models.log import Log
# from uds.core.workers.log

from .objects import MODEL_TO_TYPE, LogObjectType

# Not imported at runtime, just for type checking
if typing.TYPE_CHECKING:
    from django.db.models import Model
    from uds import models

logger = logging.getLogger(__name__)

class LogManager(metaclass=singleton.Singleton):
    """
    Manager for logging (at database) events
    """

    def __init__(self):
        pass

    @staticmethod
    def manager() -> 'LogManager':
        return LogManager()  # Singleton pattern will return always the same instance

    def _log(
        self,
        owner_type: LogObjectType,
        owner_id: int,
        level: int,
        message: str,
        source: str,
        logName: str
    ):
        """
        Logs a message associated to owner
        """
        # Ensure message fits on space
        message = str(message)[:4096]

        qs = Log.objects.filter(owner_id=owner_id, owner_type=owner_type.value)

        # now, we add new log
        try:
            Log.objects.create(
                owner_type=owner_type.value,
                owner_id=owner_id,
                created=getSqlDatetime(),
                source=source,
                level=level,
                data=message,
                name=logName,
            )
        except Exception:  # nosec
            # Some objects will not get logged, such as System administrator objects, but this is fine
            pass

    def _getLogs(
        self, owner_type: LogObjectType, owner_id: int, limit: int
    ) -> typing.List[typing.Dict]:
        """
        Get all logs associated with an user service, ordered by date
        """
        qs = Log.objects.filter(owner_id=owner_id, owner_type=owner_type.value)
        return [
            {'date': x.created, 'level': x.level, 'source': x.source, 'message': x.data}
            for x in reversed(qs.order_by('-created', '-id')[:limit])  # type: ignore  # Slicing is not supported by pylance right now
        ]

    def _clearLogs(self, owner_type: LogObjectType, owner_id: int):
        """
        Clears ALL logs related to user service
        """
        Log.objects.filter(owner_id=owner_id, owner_type=owner_type).delete()

    def doLog(
        self,
        whichObject: typing.Optional['Model'],
        level: int,
        message: str,
        source: str,
        logName: typing.Optional[str] = None,
    ):
        """
        Do the logging for the requested object.

        If the object provided do not accepts associated loggin, it simply ignores the request
        """
        owner_type = (
            MODEL_TO_TYPE.get(type(whichObject), None)
            if whichObject
            else LogObjectType.SYSLOG
        )
        objectId = getattr(whichObject, 'id', -1)
        logName = logName or ''

        if owner_type is not None:
            try:
                self._log(
                    owner_type, objectId, level, message, source, logName
                )
            except Exception as e:
                logger.error('Error logging %s.%s-%s %s: %s (%s)', whichObject.__class__, objectId, source, level, message, e)

    def getLogs(
        self, wichObject: typing.Optional['Model'], limit: int = -1
    ) -> typing.List[typing.Dict]:
        """
        Get the logs associated with "wichObject", limiting to "limit" (default is GlobalConfig.MAX_LOGS_PER_ELEMENT)
        """

        owner_type = (
            MODEL_TO_TYPE.get(type(wichObject), None)
            if wichObject
            else LogObjectType.SYSLOG
        )

        if owner_type is not None:  # 0 is valid owner type, so we must check for None
            return self._getLogs(
                owner_type,
                getattr(wichObject, 'id', -1),
                limit if limit != -1 else owner_type.get_max_elements(),
            )

        return []

    def clearLogs(self, wichObject: typing.Optional['Model']):
        """
        Clears all logs related to wichObject

        Used mainly at object database removal (parent object)
        """

        owner_type = (
            MODEL_TO_TYPE.get(type(wichObject), None)
            if wichObject
            else LogObjectType.SYSLOG
        )
        if owner_type:
            self._clearLogs(owner_type, getattr(wichObject, 'id', -1))
        #else:
            # logger.debug(
            #    'Requested clearLogs for a type of object not covered: %s: %s',
            #    type(wichObject),
            #    wichObject,
            #)
            #for line in traceback.format_stack(limit=5):
            #    logger.debug('>> %s', line)
