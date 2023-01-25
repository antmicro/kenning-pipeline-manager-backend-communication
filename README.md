# Pipeline Manager Backend Communication

Copyright (c) 2022-2023 [Antmicro](https://www.antmicro.com)

Pipeline Manager Backend Communication is an implementation of a protocol used to communicate with [Pipeline Manager](https://github.com/antmicro/kenning-pipeline-manager).
It can be used to implement a client that can send and receive messages from Pipeline Manager.

## Example client implementation

```python
# Importing necessery objects
from pipeline_manager_backend_communication. \
    communication_backend import CommunicationBackend
from pipeline_manager_backend_communication \
    .misc_structures import MessageType, Status

host = 127.0.0.1
port = 5000

# Creating a client instance with host and port specified
client = CommunicationBackend(host, port)
client.initialize_client()

while True:
    # Receiving a message from Pipeline Manager
    status, message = client.wait_for_message()

    # Checking whether the message is ready to be read
    if status == Status.DATA_READY:
        # Message consists of message's type and its content
        message_type, data = message

        # Checking type of the message and sending an appropriate response
        if message_type == MessageType.SPECIFICATION:
            client.send_message(
                MessageType.ERROR,
                'Something went wrong...'.encode()
            )
        elif message_type == MessageType.VALIDATE:
            client.send_message(
                MessageType.ERROR,
                'Application can not validate it...'.encode()
            )
        elif message_type == MessageType.RUN:
            client.send_message(
                MessageType.ERROR,
                'Application can not run it...'.encode()
            )
        # Every possible type of MessageType has to be checked...
```
