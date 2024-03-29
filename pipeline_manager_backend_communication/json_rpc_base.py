# Copyright (c) 2022-2024 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import re
import json
import logging
import traceback
from contextvars import ContextVar
from jsonrpc import JSONRPCResponseManager, Dispatcher
from jsonrpc.jsonrpc import JSONRPCRequest
from jsonrpc.jsonrpc2 import (
    JSONRPC20Request, JSONRPC20Response,
    JSONRPC20BatchRequest, JSONRPC20BatchResponse,
)
from jsonrpc.exceptions import JSONRPCDispatchException, JSONRPCMethodNotFound
from importlib.resources import path
from typing import Optional, Callable, Dict, Tuple, Union, List

from pipeline_manager_backend_communication.misc_structures import (
    OutputTuple,
    Status,
    CustomErrorCode,
)


class JSONRPCBase:
    """
    Class containing basic features for sending and reveiving JSON-RPC messages
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop = None,
        receive_message_timeout: float = None,
    ):
        self.receive_message_timeout = receive_message_timeout
        self.api_specification = None
        self.dispatcher = None
        self.log = logging.getLogger()

        if loop:
            self.loop = loop
        else:
            self.loop = asyncio.get_event_loop()

        self.__context_sid = ContextVar('Session ID of current context')
        self.__request_id = 0
        self.__not_resolved: Dict[int, asyncio.Future[Dict]] = dict()

    @staticmethod
    def _get_key(data: Dict) -> str:
        """
        Returns key based on the data type.

        Returns
        -------
        str :
            Either `error`, `params` or `result` depending on the message type
        """
        if 'error' in data:
            return 'error'
        elif 'method' in data:
            return 'params'
        else:
            return 'result'

    async def start_json_rpc_client(self):
        """
        Starts JSON-RPC client which waits for messages and process them.
        """
        await self._json_rpc_client()

    async def _generate_send_response(self, data: Dict):
        """
        Generates response to JSON-RPC request and sends it back.

        Parameters
        ----------
        data : Dict
            JSON-RPC request
        """
        key = self._get_key(data)
        self.__context_sid.set(data[key].pop('sid'))
        if key in data[key]:
            data[key] = data[key][key]
        response = await self.generate_json_rpc_response(data)
        if response:
            await self.send_jsonrpc_message_with_sid(response.data)

    async def _json_rpc_client(self):
        """
        This method run JSON-RPC client, as long as connection is not closed.
        """
        while True:
            message = await self._receive_message(
                timeout=self.receive_message_timeout
            )
            if message.status == Status.CONNECTION_CLOSED:
                return message
            elif message.status != Status.DATA_READY:
                continue

            # If the message has already been received and stored in the buffer
            # but has not been parsed
            out = await self.parse_collected_data(message.data)
            if out.status == Status.DATA_READY:
                if out.data[0]:
                    # Method is defined -- message is a request
                    self.loop.create_task(
                        self._generate_send_response(out.data[1])
                    )
                else:
                    # There is not method -- message is a response
                    self.receive_response(out.data[1])
            elif out.status == Status.CONNECTION_CLOSED:
                return out
            elif out.status != Status.NOTHING:
                self.log.error(f'Unexpected status received {out.status}, '
                               f'with data {out.data}')

    async def send_jsonrpc_message(self, data: Dict) -> OutputTuple:
        """
        Sends a message of a specified type and content.

        Parameters
        ----------
        data : Dict
            Content of the message compatible with JSON RPC.

        Returns
        -------
        OutputTuple :
            Where Status states whether sending the message was successful and
            the data argument is either a None or an exception that was
            raised while sending the message.
        """
        raise NotImplementedError

    async def send_jsonrpc_message_with_sid(
        self,
        data: Dict,
        sid: Optional[str] = None,
    ) -> OutputTuple:
        """
        Sends a message with information about session ID.
        The format of the message changes from:

        .. code-block:: python
            {
                "id": id,
                "jsonrpc": "2.0",
                key: data
            }

        to:

        .. code-block:: python
            {
                "id": id,
                "jsonrpc": "2.0",
                key: {
                    key: data,
                    "sid": sid
                }
            }

        Parameters
        ----------
        data : Dict
            Content of the message compatible with JSON RPC.
        sid : Optional[str]
            Session ID wich will be added to the message.
            If None, context_sid will be used if exists.

        Returns
        -------
        OutputTuple :
            Where Status states whether sending the message was successful and
            the data argument is either a None or an exception that was
            raised while sending the message.
        """
        sid = sid if sid else self.__context_sid.get(None)
        if sid:
            key = self._get_key(data)
            if key in data and data[key]:
                data[key] = {
                    'sid': sid,
                    key: data[key]
                }
            else:
                data[key] = {
                    'sid': sid,
                    key: {}
                }
        return await self.send_jsonrpc_message(data)

    async def parse_collected_data(self, message: bytes) -> OutputTuple:
        """
        Collects all received bytes and checks whether collected a full
        message. If a complete message is collected then it is removed
        from the `collected_message` buffer and returned.

        Messages are of format:
        SIZE : 4 bytes | CONTENT : SIZE bytes

        Parameters
        ----------
        message : bytes
            Received bytes

        Returns
        -------
        OutputTuple :
            Where Status states whether there is data to be read and the
            data argument is either a None or a message received from the
            client.
        """
        raise NotImplementedError

    async def _receive_message(
        self,
        timeout: Optional[float] = None
    ) -> OutputTuple:
        """
        Waits for a message from the socket for time specificed
        in `timeout`.

        Reads data from the socket and adds it to the buffer of all received
        data  that is later used by `parse_collected_data` function to gather
        complete messages.

        This function should only be used internally.

        Parameters
        ----------
        timeout : Optional[float]
            Time to wait for a message. If it is none then the socket
            blocks indefinitely.

        Returns
        -------
        OutputTuple :
            Where Status states whether there is data to be read and the
            data argument is either a None or a message received from the
            client.
        """
        raise NotImplementedError

    def generate_request(
        self,
        method: str,
        params: Optional[Dict] = None,
        _id: Optional[int] = None,
    ) -> Dict:
        """
        Generates JSON-RPC notification.

        Parameters
        ----------
        method : str
            Name of the notification's method
        params : Optional[Dict]
            Parameters of the notification's method
        _id : Optional[int]
            Request's ID, if not specified new one will be
            automatically generated

        Returns
        -------
        Dict :
            Dictionary with data in JSON-RPC request format
        """
        if not _id:
            _id = self.__request_id
            self.__request_id += 1
        return JSONRPC20Request(method, params, _id, False).data

    def generate_notification(self, method: str, params: Dict) -> Dict:
        """
        Generates JSON-RPC notification.

        Parameters
        ----------
        method : str
            Name of the notification's method
        params : Optional[Dict]
            Parameters of the notification's method

        Returns
        -------
        Dict :
            Dictionary with data in JSON-RPC notification format
        """
        return JSONRPC20Request(method, params, None, True).data

    async def notify(
        self,
        method: str,
        params: Optional[Dict] = None,
    ):
        """
        Creates and sends JSON-RPC notification with method
        and specified params.

        Parameters
        ----------
        method : str
            Name of the notification's method
        params : Optional[Dict]
            Parameters of the notification's method
        """
        request = self.generate_notification(method, params)
        await self.send_jsonrpc_message_with_sid(request)

    async def request(
        self,
        method: str,
        params: Optional[Dict] = None,
    ) -> Dict:
        """
        Creates and sends request for method with specified params.

        Parameters
        ----------
        method : str
            Name of the requested method
        params : Optional[Dict]
            Parameters for requested method

        Returns
        -------
        Union[int, Dict]
            Received response only when non_blocking is set to False,
            otherwise returns ID of request
        """
        response = None
        request = self.generate_request(method, params)
        _id = request['id']
        self.__not_resolved[_id] = self.loop.create_future()
        await self.send_jsonrpc_message_with_sid(request)
        response = await self.__not_resolved[_id]
        del self.__not_resolved[_id]
        key = self._get_key(response)
        if key in response and response[key]:
            response[key] = response[key][key]
        return response

    def receive_response(self, response: Dict):
        """
        Method for registring response.

        It sets result of Future instance connected with request.

        Parameters
        ----------
        response : Dict
            JSON-RPC response for send request
        """
        _id = response['id']
        if _id in self.__not_resolved:
            self.__not_resolved[_id].set_result(response)
        else:
            self.log.error(f'Wrong ID of received message: {_id}')

    def get_specification(self) -> Optional[Tuple[Dict, Dict]]:
        """
        Loads specification (API specification and common types)
        from Pipeline Manager and stores it.

        Returns
        -------
        Optional[Tuple[Dict, Dict]] :
            None if specification cannot be loaded,
            otherwise tuple of API specification and used common types.
        """
        if not self.api_specification:
            try:
                from pipeline_manager.resources import api_specification
                with path(api_specification, 'specification.json') as spec_path:  # noqa: E501
                    with open(spec_path, 'r') as fd:
                        spec = json.load(fd)
                with path(api_specification, 'common_types.json') as types_path:  # noqa: E501
                    with open(types_path, 'r') as fd:
                        common_types = json.load(fd)
                self.api_specification = (spec, common_types)
            except ModuleNotFoundError:
                self.api_specification = None
        return self.api_specification

    def wrapper_middleware(self, func: Callable) -> Callable:
        """
        Decorator caching exception from JSON-RPC methods
        and creating JSON-RPC error response from them.

        Parameters
        ----------
        func : Callable
            JSON-RPC method

        Returns
        -------
        Callable :
            Wrapped func with validation
        """

        async def _method_with_validation(**kwargs):
            try:
                response = func(**kwargs)
                if asyncio.iscoroutine(response):
                    response = await response
            except JSONRPCDispatchException:
                raise
            except Exception as ex:
                self.log.error(ex)
                traceback.print_exception(
                    None,
                    value=ex,
                    tb=ex.__traceback__,
                )
                raise JSONRPCDispatchException(
                    code=CustomErrorCode.EXCEPTION_RAISED.value,
                    message=str(ex),
                ) from ex
            return response

        return _method_with_validation

    def register_methods(
        self,
        jsonRPCMethods: object,
        methods: str = 'external',
    ):
        """
        Register JSON-RPC methods.

        Parameters
        ----------
        jsonRPCMethods : object
            Object with methods
        """
        if not self.dispatcher:
            self.dispatcher = Dispatcher()
        specification = self.get_specification()
        for name in jsonRPCMethods.__dir__():
            if name.startswith('_') or not isinstance(
                jsonRPCMethods.__getattribute__(name), Callable
            ):
                continue
            if (
                specification and
                not (
                    re.match(r'^custom_.*$', name) or
                    name in specification[0][f'{methods}_endpoints']
                )
            ):
                self.log.warn(f"Method not in specification: {name}")
                continue
            self.dispatcher[name] = self.wrapper_middleware(
                jsonRPCMethods.__getattribute__(name),
            )

    async def generate_json_rpc_response(
        self,
        data: Union[str, Dict, List[Dict]],
    ) -> Union[Dict, List[Dict]]:
        """
        Generates response to JSON-RPC message.

        Parameters
        ----------
        data : str
            Received message

        Returns
        -------
        Union[Dict, List] :
            Generated response in Dict format. If request was send in batch,
            List will be returned.
        """
        if not self.dispatcher:
            self.log.error(
                "No JSON-RPC method register, cannot generate response")
            return None
        if isinstance(data, (str, bytes)):
            return await AsyncJSONRPCResponseManager.handle(
                data, self.dispatcher)
        return await AsyncJSONRPCResponseManager.handle_request(
            JSONRPCRequest.from_data(data),
            self.dispatcher
        )


class AsyncJSONRPCResponseManager(JSONRPCResponseManager):
    @classmethod
    async def _response(
        cls,
        request: JSONRPC20Request,
        dispatcher: Dispatcher,
        method: Callable,
        context: Optional[Dict] = None,
    ):
        try:
            kwargs = request.kwargs
            if context is not None:
                context_arg = dispatcher.context_arg_for_method.get(
                    request.method
                )
                if context_arg:
                    context["request"] = request
                    kwargs[context_arg] = context
            result = await method(*request.args, **kwargs)
            return JSONRPC20Response(_id=request._id, result=result)
        except JSONRPCDispatchException as e:
            return JSONRPC20Response(_id=request._id, error=e.error._data)

    @classmethod
    async def _get_responses(
        cls,
        requests: List[JSONRPC20Request],
        dispatcher: Dispatcher,
        context: Optional[Dict] = None,
    ):
        responses = []
        methods = []
        valid_requests = []
        for request in requests:
            if request.method in dispatcher:
                methods.append(dispatcher[request.method])
                valid_requests.append(request)
                continue
            responses.append(JSONRPC20Response(
                _id=request._id, error=JSONRPCMethodNotFound()._data
            ))
        v_responses: List[JSONRPC20Response] = await asyncio.gather(*[
            cls._response(request, dispatcher, method, context)
            for request, method in zip(valid_requests, methods)
        ])
        return responses + [r for r in v_responses if r._id]

    @classmethod
    async def handle_request(
        cls,
        request: Union[JSONRPC20Request, JSONRPC20BatchRequest],
        dispatcher: Dispatcher,
        context: Optional[Dict] = None,
    ):
        rs = request if isinstance(request, JSONRPC20BatchRequest) \
            else [request]
        responses = [
            r for r in await cls._get_responses(rs, dispatcher, context)
            if r is not None
        ]

        # notifications
        if not responses:
            return

        if isinstance(request, JSONRPC20BatchRequest):
            response = JSONRPC20BatchResponse(*responses)
            response.request = request
            return response
        else:
            return responses[0]
