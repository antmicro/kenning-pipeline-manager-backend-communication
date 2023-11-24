# Copyright (c) 2022-2023 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import json
import signal
from collections import defaultdict
from typing import Optional, Callable, Dict, List
from jsonrpc.exceptions import JSONRPCDispatchException

from pipeline_manager_backend_communication.misc_structures import OutputTuple, Status, CustomErrorCode  # noqa: E501
from pipeline_manager_backend_communication.json_rpc_base import JSONRPCBase


class CommunicationBackend(JSONRPCBase, asyncio.Protocol):
    """
    TCP-based communication tool with a single client.
    It can be used both to create a TCP client and a TCP server part.

    Every message is of a format:

    SIZE : 4 bytes | CONTENT : SIZE bytes

    Where:
    - SIZE    - four first bytes are unsigned int and state the size of the
                content of the message in bytes.
    - CONTENT - the rest of the bytes convey the data in JSON-RPC format.

    Every function that can be invoked should return a tuple (Status, Any).
    The first element states a status of the server after executing the
    function.
    The second element can be any additional information.
    """

    def __init__(
        self,
        host: str,
        port: int,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        receive_message_timeout: float = None,
        encoding_format: str = 'UTF-8',
        add_signal_handler: bool = False,
    ):
        """
        Creates the instance of CommunicationBackend.

        Parameters
        ----------
        host : str
            IPv4 of the socket that is going to be used.
        port : str
            Application port that is going to be used.
        loop: Optional[asyncio.AbstractEventLoop] = None
            Event loop used. By default uvloop.Loop is used.
        receive_message_timeout : float
            Timeout for receiving message.
        encoding_format : str
            Encoding format used to decode and encode messages.
        add_signal_handler : bool
            Add SIGINT hadler to close connection and shutdown the server.
        """
        super().__init__(loop, receive_message_timeout)

        self.host = host
        self.port = port
        self.encoding_format = encoding_format

        self.server = None
        self.client_transport = None
        self.packet_size = 4096
        self.collected_data = bytes()

        self.callbacks = defaultdict(list)

        self.__connected = False
        self.__can_write = asyncio.Event()
        self.__can_write.set()

        self.__wait_for_client_future: asyncio.Future[OutputTuple] = None
        self.__wait_for_client_semaphore = asyncio.Semaphore(1)

        self.__wait_for_message_future: List[asyncio.Future[bytes]] = []
        self.__wait_for_message_semaphore = asyncio.Semaphore(1)

        if add_signal_handler:
            self.loop.add_signal_handler(
                signal.SIGINT,
                lambda: self.client_transport.abort()
                if self.client_transport else None,
            )

    # asyncio.Protocol methods

    def connection_made(self, transport: asyncio.Transport):
        if self.client_transport is not None:
            self.log.info('Different client already connected')
            transport.close()
            if not self.__wait_for_client_future.cancelled():
                self.__wait_for_client_future.set_result(
                    OutputTuple(Status.CLIENT_IGNORED, None)
                )
        else:
            self.log.info('Client connected')
            self.client_transport = transport
            self.__connected = True
            self.__wait_for_message_future = [self.loop.create_future()]
            if self.server and not self.__wait_for_client_future.cancelled():
                self.__wait_for_client_future.set_result(
                    OutputTuple(Status.CLIENT_CONNECTED, None)
                )

    def data_received(self, data: bytes):
        self.collected_data += data
        valid, size = self.check_message_length()
        while valid:
            received = self.collected_data[4:4 + size]
            self.collected_data = self.collected_data[4 + size:]
            if not self.__wait_for_message_future[-1].done():
                self.__wait_for_message_future[-1].set_result(received)
                self.__wait_for_message_future.append(
                    self.loop.create_future()
                )
            elif self.__wait_for_message_future[-1].cancelled():
                self.__wait_for_message_future.append(
                    self.loop.create_future()
                )
                self.__wait_for_message_future[-1].set_result(received)
                self.__wait_for_message_future.append(
                    self.loop.create_future()
                )
            valid, size = self.check_message_length()

    def eof_received(self):
        self.log.warning('EOF received')

    def connection_lost(self, exc: Optional[Exception]):
        self.__connected = False
        if self.client_transport and not self.client_transport.is_closing():
            self.client_transport.close()
        self.client_transport = None
        # Cancel currently used awaits
        if self.__wait_for_client_future and \
                not self.__wait_for_client_future.done():
            if exc:
                self.__wait_for_client_future.cancel(str(exc))
            else:
                self.__wait_for_client_future.cancel('Connection lost')
        if not self.__wait_for_message_future[-1].done():
            if exc:
                self.__wait_for_message_future[-1].cancel(str(exc))
            else:
                self.__wait_for_message_future[-1].cancel('Connection lost')

    def pause_writing(self):
        if self.__can_write.is_set():
            self.__can_write.clear()

    def resume_writing(self):
        if not self.__can_write.is_set():
            self.__can_write.set()

    # CommunicationBackend methods

    def register_callback(
            self,
            message_type: str,
            callback: Callable[..., None],
            *args) -> None:
        self.callbacks[message_type].append((callback, args))

    def unregister_callback(
            self,
            message_type: str,
            callback: Callable[..., None]) -> None:
        self.callbacks[message_type] = [
            c for c in self.callbacks[message_type][0]
            if callback != c
        ]

    async def initialize_server(self) -> OutputTuple:
        """
        Initializes the server socket.

        Returns
        -------
        OutputTuple :
            Where Status states whether the initialization was successful.
        """

        self.server = await self.loop.create_server(
            lambda: self,
            host=self.host,
            port=self.port,
            reuse_address=True,
            start_serving=False,
        )
        self.log.info('Server was initialized')
        return OutputTuple(Status.SERVER_INITIALIZED, None)

    async def initialize_client(self, jsonRPCMethods: object) -> OutputTuple:
        """
        Initializes and connects the client socket.

        Returns
        -------
        OutputTuple :
            Where Status states whether the connection was successful.
        """
        self.register_methods(jsonRPCMethods)
        self.client_transport, _ = await self.loop.create_connection(
            lambda: self,
            host=self.host,
            port=self.port,
        )
        self.log.info('Client was initialized and connected')
        return OutputTuple(Status.CLIENT_CONNECTED, None)

    async def wait_for_client(
        self,
        timeout: Optional[float] = None,
    ) -> OutputTuple:
        """
        Listens on the server socket for a client to connect.

        Parameters
        ----------
        timeout : float
            Time that the server socket is going to wait for
            a client to connect. If it is None then the server socket
            blocks indefinitely.

        Returns
        -------
        OutputTuple :
            Where Status states whether a client was connected.
        """
        await self.__wait_for_client_semaphore.acquire()
        try:
            self.__wait_for_client_future = self.loop.create_future()
            await self.server.start_serving()
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(self.__wait_for_client_future),
                    timeout=timeout,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError) as er:
                result = OutputTuple(Status.ERROR, er)
        finally:
            if self.server and self.server.is_serving():
                self.server.close()
                await self.server.wait_closed()
            self.__wait_for_client_future = None
            self.__wait_for_client_semaphore.release()
        return result

    @property
    def connected(self):
        """
        Function checks whether the connection is alive.
        It does that by reading from the socket. There are three possible
        cases:
        * The socket is readable and the message is not empty. That means
        that the client is still connected. Read bytes that will be later used
        to gather a complete message are added to the internal
        `collected_data` buffer.
        * The socket is readable and the message is empty. That means that the
        client closed the connection. The socket is closed.
        * The socket is not readable. That means that there the client is
        still connected and there is no message to receive.

        Returns
        -------
        bool :
            True if the client socket is connected. False otherwise
        """
        return self.__connected

    async def wait_for_message(self) -> OutputTuple:
        """
        This function checks whether a complete message has been received.
        If not it waits until the message is received.

        Returns
        -------
        OutputTuple :
            Where Status states whether there is data to be read and the
            data argument is either a None or a message received from the
            client.
        """
        while True:
            message = await self._receive_message(self.receive_message_timeout)
            if message.status == Status.CONNECTION_CLOSED:
                return message
            elif message.status != Status.DATA_READY:
                continue

            out = await self.parse_collected_data(message.data)
            if out.status == Status.DATA_READY:
                return out

    async def _receive_message(
        self,
        timeout: Optional[float] = None,
    ) -> OutputTuple:
        if self.client_transport is None or self.client_transport.is_closing():
            self.log.info('Cannot receive any messages. Connection is closed.')
            return OutputTuple(Status.CONNECTION_CLOSED, None)

        async with self.__wait_for_message_semaphore:
            future = self.__wait_for_message_future[0]
            try:
                message = await asyncio.wait_for(
                    asyncio.shield(future),
                    timeout=timeout
                )
                self.__wait_for_message_future.pop(0)
                return OutputTuple(Status.DATA_READY, message)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                return OutputTuple(Status.NOTHING, None)

    def check_message_length(self) -> bool:
        # Checking whether a header of the message was received
        if len(self.collected_data) < 4:
            return False, None

        content_size = int.from_bytes(
            self.collected_data[:4],
            byteorder='big',
            signed=False
        )

        # Checking whether a full message was received.
        return len(self.collected_data) - 4 >= content_size, content_size

    async def parse_collected_data(self, message: bytes) -> OutputTuple:
        message_content = json.loads(message.decode('UTF-8'))
        message_type = message_content["method"] if (
            isinstance(message_content, Dict) and "method" in message_content
        ) else None

        # Invoke callbacks registered for this message type
        for callback in self.callbacks.get(message_type, []):
            fun, args = callback
            self.log.info(f'Invoking callback for {message_type} message')
            if asyncio.iscoroutinefunction(fun):
                await fun(message_type, message_content, self, *args)
            else:
                fun(message_type, message_content, self, *args)

        return OutputTuple(Status.DATA_READY, (message_type, message_content))

    async def send_jsonrpc_message(self, data: Dict) -> OutputTuple:
        return await self._send_message(
            json.dumps(data, ensure_ascii=False).encode(self.encoding_format)
        )

    async def _send_message(
        self,
        data: bytes,
    ) -> OutputTuple:
        """
        An internal function that adds a length block to the message and sends
        it to the client socket.

        Parameters
        ----------
        data : bytes
            Content of the message.

        Returns
        -------
        OutputTuple :
            Where Status states whether sending the message was successful and
            the data argument is either a None or an exception that was
            raised while sending the message.
        """
        if self.client_transport is None or self.client_transport.is_closing():
            raise JSONRPCDispatchException(
                code=CustomErrorCode.EXTERNAL_APPLICATION_NOT_CONNECTED.value,
                message="Message cannot be send, application is not connected"
            )
        await self.__can_write.wait()

        length = (len(data)).to_bytes(4, byteorder='big', signed=False)
        message = length + data
        self.client_transport.write(message)
        return OutputTuple(Status.DATA_SENT, None)

    async def disconnect(self) -> OutputTuple:
        if self.__wait_for_client_future and \
                not self.__wait_for_client_future.done():
            self.__wait_for_client_future.cancel('Server disconnected')
        if self.client_transport:
            if self.client_transport.can_write_eof():
                self.client_transport.write_eof()
            self.client_transport.close()
            self.client_transport = None
            self.log.info('Client socket was disconnected')
        if self.server:
            if self.server.is_serving():
                self.server.close()
                await self.server.wait_closed()
            self.server = None
            self.log.info('Server socket was disconnected')
        return OutputTuple(Status.CONNECTION_CLOSED, None)
