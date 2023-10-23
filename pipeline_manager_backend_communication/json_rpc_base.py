# Copyright (c) 2022-2023 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

import json
from jsonrpc import JSONRPCResponseManager, Dispatcher
from jsonrpc.jsonrpc import JSONRPCRequest
from jsonrpc.exceptions import JSONRPCDispatchException
from importlib.resources import path
from jsonschema import RefResolver, Draft201909Validator, ValidationError
from typing import Optional, Callable, Dict, Tuple, Union, List


class JSONRPCBase:
    def __init__(self):
        self.api_specification = None
        self.dispatcher = None

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
                raise JSONRPCDispatchException from ex
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
