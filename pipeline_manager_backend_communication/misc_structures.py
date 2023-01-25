from enum import Enum
from typing import NamedTuple, Union


class MessageType(Enum):
    """
    Enum that is used do specify a message type.

    Those messages should only be used by the external application:
    * OK - type indicating success. Should only be used by the client.
    * ERROR - type indicating error. Should only be used by the client.

    Those messages should only be used by Pipeline Manager:
    * VALIDATE - type indicating that the message is a validation request.
    * SPECIFICATION - type indicating that the message is a specification
        request.
    * RUN - type indicating that the message is a request to run sent dataflow.
    * IMPORT - type indicating that the message is a request to import sent
        dataflow into Pipeline Manager graph format from the external
        application format.
    * EXPORT - type indicating that the message is a request to export and
        save a sent dataflow in external application's format.
    """
    OK = 0
    ERROR = 1
    VALIDATE = 2
    SPECIFICATION = 3
    RUN = 4
    IMPORT = 5
    EXPORT = 6

    def to_bytes(self) -> bytes():
        """
        Converts MessageType Enum to bytes.

        Returns
        -------
        bytes :
            Converted Enum
        """
        return int(self.value).to_bytes(length=2, byteorder='big', signed=False)  # noqa: E501

    @staticmethod
    def from_bytes(b: bytes) -> 'MessageType':
        """
        Converts two bytes to a MesssageType Enum

        Parameters
        ----------
        b : bytes
            Bytes that represent a MessageType Enum.

        Returns
        -------
        MessageType :
            Enum that is represented by `b` parameter.

        """
        return MessageType(int.from_bytes(b, byteorder='big', signed=False))


class Status(Enum):
    """
    Enum that is used to represent server status after a function was called.

    NOTHING - general use type used when there is no particular server status.
    SERVER_INITIALIZED - type indicating that the server was initialized
        successfully.
    CLIENT_CONNECTED - type indicating that a client was connected
        successfully.
    CLIENT_DISCONNECTED - type indicating that a client disconnected.
    CLIENT_IGNORE - type indicating that there was a new connection request
        which was ignored, because there is already a client connected.
    DATA_READY - type indicating that a message was fully received and can
        be read.
    DATA_SENT - type indicating that a message was successfully sent.
    ERROR - type indicating that function that was called raised an error.
    SERVER_DISCONNECTED - type indicating that the server was disconnected,
        along with a client if there was one.
    """
    NOTHING = 0
    SERVER_INITIALIZED = 1
    CLIENT_CONNECTED = 2
    CLIENT_DISCONNECTED = 3
    CLIENT_IGNORED = 4
    DATA_READY = 5
    DATA_SENT = 6
    ERROR = 7
    SERVER_DISCONNECTED = 8


class OutputTuple(NamedTuple):
    """
    Simple structure that should be used to return information when
    invoking a function from CommunicationBackend.

    Parameters
    ----------
    status : Status
        Status of the server when returning from a function.
    data : Union[tuple(MessageType, bytes), Exception, None]
        Any additional information that should be passed,
        along with the status.
    """
    status: Status
    data: Union[tuple[MessageType, bytes], Exception, None]
