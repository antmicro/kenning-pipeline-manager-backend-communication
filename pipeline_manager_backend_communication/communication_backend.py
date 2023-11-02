# Copyright (c) 2022-2023 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

from collections import defaultdict
import select
import socket
import json
from typing import Optional, Callable, Dict

from pipeline_manager_backend_communication.misc_structures import OutputTuple, Status  # noqa: E501
from pipeline_manager_backend_communication.json_rpc_base import JSONRPCBase


class CommunicationBackend(JSONRPCBase):
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

    def __init__(self, host: str, port: int, encoding_format: str = 'UTF-8'):
        """
        Creates the instance of CommunicationBackend.

        Parameters
        ----------
        host : str
            IPv4 of the socket that is going to be used.
        port : str
            Application port that is going to be used.
        """
        super().__init__()

        self.host = host
        self.port = port
        self.encoding_format = encoding_format

        self.server_socket = None
        self.client_socket = None
        self.packet_size = 4096
        self.collected_data = bytes()

        self.callbacks = defaultdict(list)

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

    def initialize_server(self) -> OutputTuple:
        """
        Initializes the server socket.

        Returns
        -------
        OutputTuple :
            Where Status states whether the initialization was successful.
        """
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1
        )
        self.server_socket.bind((self.host, self.port))
        self.server_socket.setblocking(False)
        self.server_socket.listen(1)
        self.log.info('Server was initialized')
        return OutputTuple(Status.SERVER_INITIALIZED, None)

    def initialize_client(self, jsonRPCMethods: object) -> OutputTuple:
        """
        Initializes and connects the client socket.

        Returns
        -------
        OutputTuple :
            Where Status states whether the connection was successful.
        """
        self.register_methods(jsonRPCMethods)
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client_socket.connect((self.host, self.port))
        self.log.info('Client was initialized and connected')
        return OutputTuple(Status.CLIENT_CONNECTED, None)

    def wait_for_client(
            self,
            timeout: Optional[float] = None
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
        self.log.info(f'Server is listening on {self.host}:{self.port}')
        ready, _, _ = select.select([self.server_socket], [], [], timeout)
        if ready:
            code = self.accept_client()
            return code
        return OutputTuple(Status.NOTHING, None)

    def accept_client(self) -> OutputTuple:
        """
        Accepts a client that has connected to the server socket.

        Returns
        -------
        OutputTuple :
            Where Status states whether the initialization was successful.
        """
        socket, addr = self.server_socket.accept()
        if self.client_socket is not None:
            self.log.info('Different client already connected')
            socket.close()
            return OutputTuple(Status.CLIENT_IGNORED, None)
        else:
            self.log.info('Client connected')
            self.client_socket = socket
            self.client_socket.setblocking(False)
        return OutputTuple(Status.CLIENT_CONNECTED, None)

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
        out = self._receive_message(0)
        if out.status == Status.CONNECTION_CLOSED:
            return False
        return True

    def wait_for_message(self) -> OutputTuple:
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
            # If the message has already been received and stored in the buffer
            # but has not been parsed
            out = self.parse_collected_data()
            if out.status == Status.DATA_READY:
                return out

            # If the message has not been received yet
            out = self._receive_message()
            if out.status == Status.CONNECTION_CLOSED:
                return out

    def _receive_message(
        self,
        timeout: Optional[float] = None
    ) -> OutputTuple:
        if self.client_socket is None:
            self.log.info('Cannot receive any messages. Connection is closed.')
            return OutputTuple(Status.CONNECTION_CLOSED, None)

        try:
            ready, _, _ = select.select([self.client_socket], [], [], timeout)
        except (Exception, ConnectionResetError) as ex:
            self.log.info('Error while waiting for the client socket. Aborting.')  # noqa: E501
            self.disconnect()
            return OutputTuple(Status.CONNECTION_CLOSED, ex)

        if ready and self.client_socket:
            try:
                data = self.client_socket.recv(self.packet_size)
            except BlockingIOError:
                return OutputTuple(Status.NOTHING, None)
            self.collected_data += data

            if len(data) == 0:
                self.log.info('Other side closed the connection. Closing the socket')  # noqa: E501
                self.client_socket.close()
                self.client_socket = None
                return OutputTuple(Status.CONNECTION_CLOSED, None)

        return OutputTuple(Status.NOTHING, None)

    def parse_collected_data(self) -> OutputTuple:
        # Checking whether a header of the message was received
        if len(self.collected_data) < 4:
            return OutputTuple(Status.NOTHING, None)

        content_size = int.from_bytes(
            self.collected_data[:4],
            byteorder='big',
            signed=False
        )

        # Checking whether a full message was received.
        if len(self.collected_data) - 4 < content_size:
            return OutputTuple(Status.NOTHING, None)

        # Collecting the message and removing the bytes from the buffer.
        message = self.collected_data[4:4 + content_size]
        self.collected_data = self.collected_data[4 + content_size:]

        message_content = json.loads(message.decode('UTF-8'))
        message_type = message_content["method"] \
            if "method" in message_content else None

        # Invoke callbacks registered for this message type
        for callback in self.callbacks.get(message_type, []):
            fun, args = callback
            self.log.info(f'Invoking callback for {message_type} message')
            fun(message_type, message_content, self, *args)

        return OutputTuple(Status.DATA_READY, (message_type, message_content))

    def send_message(self, mtype: str, data: Dict) -> OutputTuple:
        """
        Sends a message of a specified type and content.

        ----------
        mtype : MessageType
            Type of the message.
        data : bytes, optional
            Content of the message.

        Returns
        -------
        OutputTuple :
            Where Status states whether sending the message was successful and
            the data argument is either a None or an exception that was
            raised while sending the message.
        """
        return self._send_message(mtype.encode(self.encoding_format) + data)

    def send_jsonrpc_message(self, data: Dict) -> OutputTuple:
        return self._send_message(
            json.dumps(data, ensure_ascii=False).encode(self.encoding_format)
        )

    def _send_message(
            self,
            data: bytes
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
        length = (len(data)).to_bytes(4, byteorder='big', signed=False)
        message = length + data
        try:
            self.client_socket.sendall(message)
            return OutputTuple(Status.DATA_SENT, None)
        except Exception as ex:
            self.log.exception('Something went wrong when sending a message. Disconnecting')  # noqa: E501
            self.disconnect()
            return OutputTuple(Status.ERROR, ex)

    def disconnect(self) -> OutputTuple:
        """
        Disconnects both server socket and client socket.

        Returns
        -------
        OutputTuple :
            Where Status states whether disconnecting was successful.
        """
        if self.client_socket:
            self.client_socket.close()
            self.client_socket = None
            self.log.info('Client socket was disconnected')
        if self.server_socket:
            self.server_socket.close()
            self.server_socket = None
            self.log.info('Server socket was disconnected')
        return OutputTuple(Status.CONNECTION_CLOSED, None)
