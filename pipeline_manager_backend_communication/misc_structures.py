# Copyright (c) 2022-2023 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
from typing import NamedTuple, Tuple, Union


class MessageType(Enum):
    """
    Enum that is used do specify a message type.
    Used for 'type' in returned message.

    * OK - type indicating success. Should only be used by the client.
    * ERROR - type indicating error. Should only be used by the client.
    * PROGRESS - type indicating progress message.
    * WARNING - type indicating warning. Should only be used by the client.
    """
    OK = 0
    ERROR = 1
    PROGRESS = 2
    WARNING = 3

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
    CLIENT_CONNECTED - type indicating that client was connected
        successfully.
    CONNECTION_CLOSED - type indicating that connection is disconnected.
    CLIENT_IGNORE - type indicating that there was a new connection request
        which was ignored, because there is already a client connected.
    DATA_READY - type indicating that a message was fully received and can
        be read.
    DATA_SENT - type indicating that a message was successfully sent.
    ERROR - type indicating that function that was called raised an error.
    """
    NOTHING = 0
    SERVER_INITIALIZED = 1
    CLIENT_CONNECTED = 2
    CONNECTION_CLOSED = 3
    CLIENT_IGNORED = 4
    DATA_READY = 5
    DATA_SENT = 6
    ERROR = 7


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
    data: Union[Tuple[MessageType, bytes], Exception, None]


class CustomErrorCode(Enum):
    """
    Enum defining custom error codes of JSON-RPC error response.

    EXCEPTION_RAISED - used when JSON-RPC method raises exception
    EXTERNAL_APPLICATION_NOT_CONNECTED - used when
    """
    EXCEPTION_RAISED = -1
    EXTERNAL_APPLICATION_NOT_CONNECTED = -2
