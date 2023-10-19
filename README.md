# Pipeline Manager Backend Communication

Copyright (c) 2022-2023 [Antmicro](https://www.antmicro.com)

Pipeline Manager Backend Communication is an implementation of a protocol used to communicate with [Pipeline Manager](https://github.com/antmicro/kenning-pipeline-manager).
It can be used to implement a client that can send and receive messages from Pipeline Manager.

## Installation

To install the module, `pip` and `Python3` are required.
After installing them, install the module with:

```bash
pip install 'pipeline_manager_backend_communication[pipeline-manager] git+https://github.com/antmicro/kenning-pipeline-manager-backend-communication.git'
```

## Example client implementation

```python
# Importing necessery objects
from pipeline_manager_backend_communication. \
    communication_backend import CommunicationBackend
from pipeline_manager_backend_communication \
    .misc_structures import MessageType, Status

host = '127.0.0.1'
port = 5000

# Implements JSON-RPC methods
class RPCMethods:
    # Methods have to have matching names with JSON-RPC methods
    def request_specification(self) -> Dict:
        # ...
        return {'type': MessageType.OK.value, 'content': spec}

    # Method's parameters have to match with received message
    # or **kwargs can be used to get all received params
    def validate_dataflow(self, dataflow: Dict) -> Dict:
        # ...
        return {'type': MessageType.OK.value}

    def run_dataflow(self, dataflow: Dict) -> Dict:
        # ...
        return {'type': MessageType.OK.value}

    def export_dataflow(self, dataflow: Dict) -> Dict:
        # ...
        return {'type': MessageType.OK.value, 'content': dataflow}

    def import_dataflow(self, **kwargs) -> Dict:
        # ...
        return {'type': MessageType.OK.value, 'content': kwargs['external_application_dataflow']}

# Creating a client instance with host and port specified
client = CommunicationBackend(host, port)
# Initialize client with registering methods
client.initialize_client(RPCMethods())
# Start JSON-RPC client
client.start_json_rpc_client()
```
