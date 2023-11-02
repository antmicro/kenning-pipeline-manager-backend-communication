# Copyright (c) 2022-2023 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

import json
import logging
import threading
from jsonrpc import JSONRPCResponseManager, Dispatcher
from jsonrpc.jsonrpc import JSONRPCRequest
from jsonrpc.jsonrpc2 import JSONRPC20Request
from jsonrpc.exceptions import JSONRPCDispatchException
from importlib.resources import path
from jsonschema import RefResolver, Draft201909Validator, ValidationError
from typing import Optional, Callable, Dict, Tuple, Union, List

from pipeline_manager_backend_communication.misc_structures import (
    OutputTuple,
    Status
)


class JSONRPCBase:
    """
    Class containing basic features for sending and reveiving JSON-RPC messages
    """

    def __init__(self):
        self.api_specification = None
        self.dispatcher = None
        self.log = logging.getLogger()

        self.client_thread: threading.Thread = None

        self.__request_id = 0
        self.__not_resolved: Dict[int, Tuple[JSONRPC20Request, threading.Event]] = dict()  # noqa: E501
        self.__responses: Dict[int, Dict] = dict()

    def start_json_rpc_client(self, separate_thread: bool = False):
        """
        Starts JSON-RPC client which waits for messages and process them.

        Parameters
        ----------
        separate_thread : bool
            Run JSON-RPC client in separate thread

        Raises
        ------
        Exception :
            If previous thread is still alive
        """
        if self.client_thread and self.client_thread.is_alive():
            raise Exception(
                "Only one client thread can be alive at the same time"
            )
        if separate_thread:
            self.client_thread = threading.Thread(target=self._json_rpc_client)
            self.client_thread.start()
        else:
            self._json_rpc_client()

    def _generate_send_response(self, data: Dict):
        response = self.generate_json_rpc_response(data)
        self.send_jsonrpc_message(response.json)

    def _json_rpc_client(self):
        """
        This function run JSON-RPC client, as long as connection is not closed.
        """
        while True:
            # If the message has already been received and stored in the buffer
            # but has not been parsed
            out = self.parse_collected_data()
            if out.status == Status.DATA_READY:
                if out.data[0]:
                    # Method is defined -- message is a request
                    if threading.current_thread() == self.client_thread:
                        threading.Thread(
                            target=self._generate_send_response,
                            args=(out.data[1],)
                        ).start()
                    else:
                        self._generate_send_response(out.data[1])
                else:
                    # There is not method -- message is a response
                    self.receive_response(out.data[1])
            elif out.status == Status.CONNECTION_CLOSED:
                return out
            elif out.status != Status.NOTHING:
                self.log.error(f'Unexpected status received {out.status}, '
                               f'with data {out.data}')

            # If the message has not been received yet
            out = self._receive_message(timeout=1.0)
            if out.status == Status.CONNECTION_CLOSED:
                return out

    def send_jsonrpc_message(self, data: Dict) -> OutputTuple:
        """
        Sends a message of a specified type and content.

        ----------
        data : bytes, optional
            Content of the message compatible with JSON RPC.

        Returns
        -------
        OutputTuple :
            Where Status states whether sending the message was successful and
            the data argument is either a None or an exception that was
            raised while sending the message.
        """
        raise NotImplementedError

    def parse_collected_data(self) -> OutputTuple:
        """
        Collects all received bytes and checks whether collected a full
        message. If a complete message is collected then it is removed
        from the `collected_message` buffer and returned.

        Messages are of format:
        SIZE : 4 bytes | CONTENT : SIZE bytes

        Returns
        -------
        OutputTuple :
            Where Status states whether there is data to be read and the
            data argument is either a None or a message received from the
            client.
        """
        raise NotImplementedError

    def _receive_message(
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

    def notify(
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
        self.send_jsonrpc_message(request)

    def request(
        self,
        method: str,
        params: Optional[Dict] = None,
        non_blocking: bool = False,
    ) -> Union[int, Dict]:
        """
        Creates and sends request for method with specified params.

        Parameters
        ----------
        method : str
            Name of the requested method
        params : Optional[Dict]
            Parameters for requested method
        non_blocking : bool
            Should this method wait for response,
            works only when JSON-RPC client runs on separate thread

        Returns
        -------
        Union[int, Dict]
            Received response only when non_blocking is set to False,
            otherwise returns ID of request
        """
        response = None
        request = self.generate_request(method, params)
        self.send_jsonrpc_message(request)
        _id = request['id']
        if not non_blocking:
            event = threading.Event()
            self.__not_resolved[_id] = (request, event)
            event.wait()
            response = self.__responses.pop(_id)
        return response if response else _id

    def receive_response(self, response: Dict):
        """
        Method for registring response.

        It releases lock if some thread is waiting for this reponse.

        Parameters
        ----------
        response : Dict
            JSON-RPC response for send request
        """
        _id = response['id']
        if _id in self.__not_resolved:
            event = self.__not_resolved.pop(_id)
            self.__responses[_id] = response
            event[1].set()

    def response_for_id(self, _id: int) -> Optional[Dict]:
        """
        Get response for request with specified ID.

        If response has not been received yet or has already been taken,
        returns None.

        Parameters
        ----------
        _id : int
            ID of requested response

        Returns
        -------
        Optional[Dict] :
            Response with specified ID or None
        """
        if _id not in self.__not_resolved and _id in self.__responses:
            return self.__responses.pop(_id)
        return None

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

    def validation_middleware(
        self,
        func: Callable,
        specification: Dict,
        common_types: Dict
    ) -> Callable:
        """
        Decorator validating JSON-RPC method's params and return.

        Parameters
        ----------
        func : Callable
            JSON-RPC method
        specification : Dict
            Dictionary with 'params' and 'returns' values containing schema
        common_types : Dict
            Schema with types used in specification

        Returns
        -------
        Callable :
            Wrapped func with validation
        """
        resolver = RefResolver.from_schema(common_types)
        validator_params = Draft201909Validator(
            specification['params'], resolver=resolver)
        validator_returns = Draft201909Validator(
            specification['returns'], resolver=resolver)

        def _method_with_validation(**kwargs):
            try:
                validator_params.validate(kwargs)
            except ValidationError as ex:
                raise JSONRPCDispatchException(
                    code=-1, message=f"Invalid params\n{str(ex)}") from ex
            try:
                response = func(**kwargs)
            except Exception as ex:
                self.log.error(ex)
                raise JSONRPCDispatchException(
                    code=-3, message=str(ex)
                ) from ex
            try:
                validator_returns.validate(response)
            except ValidationError as ex:
                raise JSONRPCDispatchException(
                    code=-2, message=f"Invalid response\n{str(ex)}") from ex
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
            if name.startswith('_'):
                continue
            if specification:
                if not isinstance(
                    jsonRPCMethods.__getattribute__(name), Callable
                ):
                    continue
                if name not in specification[0][f'{methods}_endpoints']:
                    self.log.warn(f"Method not in specification: {name}")
                    continue
                self.dispatcher[name] = self.validation_middleware(
                    jsonRPCMethods.__getattribute__(name),
                    specification[0][f'{methods}_endpoints'][name],
                    specification[1],
                )
            else:
                self.dispatcher[name] = jsonRPCMethods.__getattribute__(name)

    def generate_json_rpc_response(
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
            return JSONRPCResponseManager.handle(data, self.dispatcher)
        return JSONRPCResponseManager.handle_request(
            JSONRPCRequest.from_data(data),
            self.dispatcher
        )
