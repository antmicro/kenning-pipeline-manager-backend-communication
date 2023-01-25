import socket
import select
import logging
from typing import Optional
from pipeline_manager_backend_communication.misc_structures import MessageType, Status, OutputTuple  # noqa: E501


class CommunicationBackend(object):
    """
    TCP-based communication tool with a single client.
    It can be used both to create a TCP client and a TCP server part.

    Every message is of a format:

    SIZE : 4 bytes | TYPE : 2 bytes | CONTENT : SIZE bytes

    Where:
    - SIZE    - four first bytes are unsigned int and state the size of the
                content of the message in bytes.
    - TYPE    - two next bytes are unsinged int and state the type of
                the message.
    - CONTENT - the rest of the bytes convey the data.

    Every function that can be invoked should return a tuple (Status, Any).
    The first element states a status of the server after executing the
    function.
    The second element can be any additional information.
    """
    def __init__(self, host: str, port: int) -> None:
        """
        Creates the instance of CommunicationBackend.

        Parameters
        ----------
        host : str
            IPv4 of the socket that is going to be used.
        port : str
            Application port that is going to be used.
        """
        self.host = host
        self.port = port

        self.server_socket = None
        self.client_socket = None
        self.packet_size = 4096
        self.collected_data = bytes()
        self.log = logging.getLogger()

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

    def initialize_client(self) -> OutputTuple:
        """
        Initializes and connects the client socket.

        Returns
        -------
        OutputTuple :
            Where Status states whether the connection was successful.
        """
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

    def wait_for_message(
            self,
            timeout: Optional[float] = None
            ) -> OutputTuple:
        """
        Waits for a message from the client socket.

        Parameters
        ----------
        timeout : float
            Time that the server is going to wait for a client's message.
            If it is none then the server socket blocks indefinitely.

        Returns
        -------
        OutputTuple :
            Where Status states whether there is data to be read and the
            data argument is either a None or a message received from the
            client.
        """
        ready, _, _ = select.select([self.client_socket], [], [], timeout)
        if ready:
            return self.receive_data()

        return OutputTuple(Status.NOTHING, None)

    def receive_data(
            self
            ) -> OutputTuple:
        """
        Tries to read data from the client.

        Returns
        -------
        OutputTuple :
            Where Status states whether there is data to be read and the
            data argument is either a None or a message received from the
            client.
        """
        data = self.client_socket.recv(self.packet_size)
        if not data:
            self.log.info('Client disconnected from the server')
            self.client_socket.close()
            self.client_socket = None
            return OutputTuple(Status.CLIENT_DISCONNECTED, None)
        return self.parse_received(data)

    def parse_received(
            self,
            data: bytes
            ) -> OutputTuple:
        """
        Collects received bytes and checks whether collected a full message.
        All bytes that are received from the client socket using `recv` should
        be passed to this function.

        Messages are of format:

        SIZE : 4 bytes | TYPE : 2 bytes | CONTENT : SIZE bytes

        Parameters
        ----------
        data : bytes
            Bytes that are received from the client socket sequentially.

        Returns
        -------
        OutputTuple :
            Where Status states whether there is data to be read and the
            data argument is either a None or a message received from the
            client.
        """
        self.collected_data += data

        # Checking whether a header of the message was received
        if len(self.collected_data) < 6:
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

        message_type = MessageType.from_bytes(message[:2])
        message_content = message[2:]

        return OutputTuple(Status.DATA_READY, (message_type, message_content))

    def send_message(
            self,
            mtype: MessageType,
            data: bytes = bytes()
            ) -> OutputTuple:
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
        return self._send_message(mtype.to_bytes() + data)

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
        if self.server_socket:
            self.server_socket.close()
            self.server_socket = None
            self.log.info('Server socket was disconnected')
        if self.client_socket:
            self.client_socket.close()
            self.client_socket = None
            self.log.info('Client socket was disconnected')

        return OutputTuple(Status.SERVER_DISCONNECTED, None)
