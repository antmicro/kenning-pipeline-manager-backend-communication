# Copyright (c) 2022-2023 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

import mimetypes
from base64 import b64decode
from typing import Optional


def convert_message_to_bytes(message: str) -> bytes:
    """
    Converts message from base64 format to bytes.

    Parameters
    ----------
    message : str
        Base64 string

    Raises
    ------
    binascii.Error
        When message contains characters not supported by base64 format.
    """
    return b64decode(message, validate=True)


def convert_message_to_string(
    message: str,
    base64: bool,
    mime: Optional[str] = None,
    encoding: Optional[str] = None,
) -> str:
    """
    Converts message from base64 format to default string.

    Parameters
    ----------
    message : str
        Base64 string
    base64 : bool
        Whether message is in base64 format
    mime : Optional[str]
        MIME type
    encoding : Optional[str]
        Which encoding should be used to decode message,
        if not specified encoding associated
        with MIME type will be used or UTF-8.

    Returns
    -------
    str
        String with decoded message or unchanged string
        if it is not in base64 format.
    """
    if not base64:
        return message
    if encoding is None and mime is not None:
        extension = mimetypes.guess_extension(mime, True)
        encoding = mimetypes.encodings_map.get(extension, None)
    if not encoding:
        encoding = "utf"
    try:
        return convert_message_to_bytes(message).decode(encoding)
    except Exception as ex:
        print(ex)
        return message
