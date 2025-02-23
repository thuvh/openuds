# -*- coding: utf-8 -*-
#
# Copyright (c) 2023 Virtual Cable S.L.U.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification
# are permitted provided that the following conditions are met:
#
#    * Redistributions of source code must retain the above copyright notice
#      this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above copyright notice
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
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
Author: Adolfo Gómez, dkmaster at dkmon dot com
"""
import datetime
import logging
import secrets
import typing

import dns.resolver
import dns.reversename

from uds.core import types, consts
from uds.core.environment import Environment
from uds.core.util import validators

logger = logging.getLogger(__name__)


if typing.TYPE_CHECKING:
    import uds.models


def migrate(
    apps, model: typing.Literal['Provider', 'Service'], DataType: typing.Type, subtype: str, ipListAttr: str
) -> None:
    try:
        Table: typing.Type['uds.models.ManagedObjectModel'] = apps.get_model('uds', model)
        ServerGroup: 'typing.Type[uds.models.ServerGroup]' = apps.get_model(
            'uds', 'ServerGroup'
        )
        Server: 'typing.Type[uds.models.Server]' = apps.get_model('uds', 'Server')
        # For testing
        # from uds.models import Provider, Server, ServerGroup

        for record in Table.objects.filter(data_type=DataType.typeType):
            # Extract data
            obj = DataType(Environment(record.uuid), None)
            obj.deserialize(record.data)

            servers: typing.List[str] = getattr(obj, ipListAttr).value
            # Clean up servers, removing empty ones
            servers = [s.strip() for s in servers if s.strip()]
            # Try dns lookup if servers contains hostnames
            server_ip_hostname: typing.List[typing.Tuple[str, str]] = []
            for server in servers:
                try:
                    validators.validateIpv4OrIpv6(server)
                    # Is Pure IP, try to get hostname
                    try:
                        answers = dns.resolver.resolve(dns.reversename.from_address(server), 'PTR')
                        server_ip_hostname.append((server, str(answers[0]).rstrip('.')))
                    except Exception:
                        # No problem, no reverse dns, hostname is the same as IP
                        server_ip_hostname.append((server, server))
                except Exception:
                    # Not pure IP, try to resolve it and get first IP
                    try:
                        answers = dns.resolver.resolve(server, 'A')
                        server_ip_hostname.append((str(answers[0]), server))
                    except Exception:
                        # Try AAAA
                        try:
                            answers = dns.resolver.resolve(server, 'AAAA')
                            server_ip_hostname.append((str(answers[0]), server))
                        except Exception:
                            # Not found, continue, but do not add to servers and log it
                            logger.error('Server %s on %s not found on DNS', server, record.name)

            registeredServerGroup = ServerGroup.objects.create(
                name=f'RDS Server Group for {record.name}',
                comments='Migrated from {}'.format(record.name),
                type=types.servers.ServerType.UNMANAGED,
                subtype=subtype,
            )
            # Create Registered Servers for IP (individual) and add them to the group
            for svr in server_ip_hostname:
                registeredServerGroup.servers.create(
                    token=secrets.token_urlsafe(36),
                    username='migration',
                    ip_from=svr[0],
                    ip=svr[0],
                    os_type=types.os.KnownOS.WINDOWS.os_name(),
                    hostname=svr[1],
                    listen_port=0,
                    type=types.servers.ServerType.UNMANAGED,
                    subtype=subtype,
                    stamp=datetime.datetime.now(),
                )
            # Set server group on provider
            logger.info('Setting server group %s on provider %s', registeredServerGroup.name, record.name)
            obj.serverGroup.value = registeredServerGroup.uuid
            # Save record
            record.data = obj.serialize()
            record.save(update_fields=['data'])

    except Exception as e:
        print(e)
        logger.exception('Exception found while migrating HTML5RDP transports')

def rollback(apps, model: typing.Literal['Provider', 'Service'], DataType: typing.Type, subtype: str, ipListAttr: str) -> None:
    """
    "Un-Migrates" an new tunnel transport to an old one (without tunnelServer)
    """
    try:
        Table: typing.Type['uds.models.ManagedObjectModel'] = apps.get_model('uds', model)
        ServerGroup: 'typing.Type[uds.models.ServerGroup]' = apps.get_model(
            'uds', 'ServerGroup'
        )
        # For testing
        # from uds.models import Transport, ServerGroup

        for record in Table.objects.filter(data_type=DataType.typeType):
            # Extranct data
            obj = DataType(Environment(record.uuid), None)
            obj.deserialize(record.data)
            # Guacamole server is https://<host>:<port>
            # Other tunnels are <host>:<port>
            iplist = getattr(obj, ipListAttr)
            rsg = ServerGroup.objects.get(uuid=obj.serverGroup.value)
            iplist.value=[i.ip for i in rsg.servers.all()]
            # Remove registered servers
            for i in rsg.servers.all():
                i.delete()
            # Save obj
            record.data = obj.serialize()
            record.save(update_fields=['data'])
    except Exception as e:  # nosec: ignore this
        print(e)
        logger.error('Exception found while migrating HTML5RDP transports: %s', e)