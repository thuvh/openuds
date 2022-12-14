# -*- coding: utf-8 -*-
#
# Copyright (c) 2022 Virtual Cable S.L.U.
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
#    * Neither the name of Virtual Cable S.L. nor the names of its contributors
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
'''
Author: Adolfo Gómez, dkmaster at dkmon dot com
'''
import asyncio
import typing
import logging

import aiohttp

from . import consts
from . import config
from . import stats

logger = logging.getLogger(__name__)

if typing.TYPE_CHECKING:
    from . import proxy


# Protocol
class TunnelProtocol(asyncio.Protocol):
    # future to mark eof
    finished: asyncio.Future
    # Transport and other side of tunnel
    transport: 'asyncio.transports.Transport'
    other_side: 'TunnelProtocol'
    # Current state
    runner: typing.Any  # In fact, typing.Callable[[bytes], None], but mypy complains on checking variables that are callables on classes
    # Command buffer
    cmd: bytes
    # Ticket
    notify_ticket: bytes
    # owner Proxy class
    owner: 'proxy.Proxy'
    # source of connection
    source: typing.Tuple[str, int]
    destination: typing.Tuple[str, int]
    # Counters & stats related
    stats_manager: stats.Stats
    # counter
    counter: stats.StatsSingleCounter

    def __init__(
        self, owner: 'proxy.Proxy', other_side: typing.Optional['TunnelProtocol'] = None
    ) -> None:
        # If no other side is given, we are the server part
        super().__init__()
        if other_side:
            self.other_side = other_side
            self.stats_manager = other_side.stats_manager
            self.counter = self.stats_manager.as_recv_counter()
            self.runner = self.do_proxy
        else:
            self.other_side = self
            self.stats_manager = stats.Stats(owner.args)
            self.counter = self.stats_manager.as_sent_counter()
            self.runner = self.do_command

        # transport is undefined until connection_made is called
        self.finished = asyncio.Future()
        self.cmd = b''
        self.notify_ticket = b''
        self.owner = owner
        self.source = ('', 0)
        self.destination = ('', 0)

    def process_open(self) -> None:
        # Open Command has the ticket behind it

        if len(self.cmd) < consts.TICKET_LENGTH + consts.COMMAND_LENGTH:
            return  # Wait for more data to complete OPEN command

        # Ticket received, now process it with UDS
        ticket = self.cmd[consts.COMMAND_LENGTH :]

        # Stop reading from this side until open is done
        self.transport.pause_reading()

        # clean up the command
        self.cmd = b''

        loop = asyncio.get_event_loop()

        async def open_other_side() -> None:
            try:
                result = await TunnelProtocol.getTicketFromUDS(
                    self.owner.cfg, ticket, self.source
                )
            except Exception as e:
                logger.error('ERROR %s', e.args[0] if e.args else e)
                self.transport.write(b'ERROR_TICKET')
                self.transport.close()  # And force close
                return

            # store for future use
            self.destination = (result['host'], int(result['port']))
            self.notify_ticket = result['notify'].encode()

            logger.info(
                'OPEN TUNNEL FROM %s to %s',
                self.pretty_source(),
                self.pretty_destination(),
            )

            try:
                (_, protocol) = await loop.create_connection(
                    lambda: TunnelProtocol(self.owner, self),
                    self.destination[0],
                    self.destination[1],
                )
                self.other_side = typing.cast('TunnelProtocol', protocol)

                # Resume reading
                self.transport.resume_reading()
                # send OK to client
                self.transport.write(b'OK')
            except Exception as e:
                logger.error('Error opening connection: %s', e)
                self.close_connection()

        loop.create_task(open_other_side())
        # From now, proxy connection
        self.runner = self.do_proxy

    def process_stats(self, full: bool) -> None:
        # if pasword is not already received, wait for it
        if len(self.cmd) < consts.PASSWORD_LENGTH + consts.COMMAND_LENGTH:
            return

        try:
            logger.info('COMMAND: %s', self.cmd[: consts.COMMAND_LENGTH].decode())

            # Check valid source ip
            if self.transport.get_extra_info('peername')[0] not in self.owner.cfg.allow:
                # Invalid source
                self.transport.write(b'FORBIDDEN')
                return

            # Check password
            passwd = self.cmd[consts.COMMAND_LENGTH :]

            # Clean up the command, only keep base part
            self.cmd = self.cmd[:4]

            if passwd.decode(errors='ignore') != self.owner.cfg.secret:
                # Invalid password
                self.transport.write(b'FORBIDDEN')
                return

            data = stats.GlobalStats.get_stats(self.owner.args)

            for v in data:
                logger.debug('SENDING %s', v)
                self.transport.write(v.encode() + b'\n')

            logger.info('TERMINATED %s', self.pretty_source())
        finally:
            self.close_connection()

    def do_command(self, data: bytes) -> None:
        self.cmd += data
        if len(self.cmd) >= consts.COMMAND_LENGTH:
            logger.info('CONNECT FROM %s', self.pretty_source())

            command = self.cmd[: consts.COMMAND_LENGTH]
            try:
                if command == consts.COMMAND_OPEN:
                    self.process_open()
                elif command == consts.COMMAND_TEST:
                    logger.info('COMMAND: TEST')
                    self.transport.write(b'OK')
                    self.close_connection()
                    return
                elif command in (consts.COMMAND_STAT, consts.COMMAND_INFO):
                    # This is an stats requests
                    self.process_stats(full=command == consts.COMMAND_STAT)
                    return
                else:
                    raise Exception('Invalid command')
            except Exception:
                logger.error('ERROR from %s', self.pretty_source())
                self.transport.write(b'ERROR_COMMAND')
                self.close_connection()
                return

        # if not enough data to process command, wait for more

    def do_proxy(self, data: bytes) -> None:
        self.counter.add(len(data))
        logger.debug('Processing proxy: %s', len(data))
        self.other_side.transport.write(data)

    # inherited from asyncio.Protocol

    def connection_made(self, transport: 'asyncio.transports.BaseTransport') -> None:
        logger.debug('Connection made: %s', transport.get_extra_info('peername'))

        # We know for sure that the transport is a Transport.
        self.transport = typing.cast('asyncio.transports.Transport', transport)
        self.cmd = b''
        self.source = self.transport.get_extra_info('peername')

    def data_received(self, data: bytes):
        logger.debug('Data received: %s', len(data))
        self.runner(data)  # send data to current runner (command or proxy)

    def notifyEnd(self):
        if self.notify_ticket:
            asyncio.get_event_loop().create_task(
                TunnelProtocol.notifyEndToUds(
                    self.owner.cfg, self.notify_ticket, self.stats_manager
                )
            )
            self.notify_ticket = b''  # Clean up so no more notifications

    def connection_lost(self, exc: typing.Optional[Exception]) -> None:
        logger.debug('Connection closed : %s', exc)
        self.finished.set_result(True)
        if self.other_side is not self:
            self.other_side.transport.close()
        else:
            self.stats_manager.close()
        self.notifyEnd()

    # helpers
    # source address, pretty format
    def pretty_source(self) -> str:
        return self.source[0] + ':' + str(self.source[1])

    def pretty_destination(self) -> str:
        return self.destination[0] + ':' + str(self.destination[1])

    def close_connection(self):
        self.transport.close()
        # If destination is not set, it's a command processing (i.e. TEST or STAT)
        if self.destination[0] != '':
            logger.info(
                'TERMINATED %s to %s, s:%s, r:%s, t:%s',
                self.pretty_source(),
                self.pretty_destination(),
                self.stats_manager.sent,
                self.stats_manager.recv,
                int(self.stats_manager.end - self.stats_manager.start),
            )
            # Notify end to uds
            self.notifyEnd()
        else:
            logger.info('TERMINATED %s', self.pretty_source())

    @staticmethod
    async def _readFromUDS(
        cfg: config.ConfigurationType,
        ticket: bytes,
        msg: str,
        queryParams: typing.Optional[typing.Mapping[str, str]] = None,
    ) -> typing.MutableMapping[str, typing.Any]:
        try:
            url = (
                cfg.uds_server + '/' + ticket.decode() + '/' + msg + '/' + cfg.uds_token
            )
            if queryParams:
                url += '?' + '&'.join(
                    [f'{key}={value}' for key, value in queryParams.items()]
                )
            # Set options
            options: typing.Dict[str, typing.Any] = {'timeout': cfg.uds_timeout}
            if cfg.uds_verify_ssl is False:
                options['ssl'] = False
            # Requests url with aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(url, **options) as r:
                    if not r.ok:
                        raise Exception(await r.text())
                    return await r.json()
        except Exception as e:
            raise Exception(f'TICKET COMMS ERROR: {ticket.decode()} {msg} {e!s}')

    @staticmethod
    async def getTicketFromUDS(
        cfg: config.ConfigurationType, ticket: bytes, address: typing.Tuple[str, int]
    ) -> typing.MutableMapping[str, typing.Any]:
        # Sanity checks
        if len(ticket) != consts.TICKET_LENGTH:
            raise ValueError(f'TICKET INVALID (len={len(ticket)})')

        for n, i in enumerate(ticket.decode(errors='ignore')):
            if (
                (i >= 'a' and i <= 'z')
                or (i >= '0' and i <= '9')
                or (i >= 'A' and i <= 'Z')
            ):
                continue  # Correctus
            raise ValueError(f'TICKET INVALID (char {i} at pos {n})')

        return await TunnelProtocol._readFromUDS(cfg, ticket, address[0])

    @staticmethod
    async def notifyEndToUds(
        cfg: config.ConfigurationType, ticket: bytes, counter: stats.Stats
    ) -> None:
        await TunnelProtocol._readFromUDS(
            cfg,
            ticket,
            'stop',
            {'sent': str(counter.sent), 'recv': str(counter.recv)},
        )
