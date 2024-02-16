# Copyright (c) 2022-2024 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

"""
Main module of the backend communication.

This module should be used to communicate between Pipeline Manager application
and other Python based applications.
"""

import asyncio
import uvloop

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
