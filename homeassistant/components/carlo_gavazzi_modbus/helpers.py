"""Helpers for the Carlo Gavazzi Modbus integration."""

from collections.abc import Mapping
from typing import Any

from modbus_connection import ModbusSerialParams

from homeassistant.const import CONF_DEVICE

from .const import CONF_BAUDRATE


def create_modbus_params(data: Mapping[str, Any]) -> ModbusSerialParams:
    """Build the Modbus link parameters from config entry data.

    The library's serial defaults are 8N1, which is what the meters speak out
    of the box; only the baud rate is worth asking for.
    """
    return ModbusSerialParams(device=data[CONF_DEVICE], baudrate=data[CONF_BAUDRATE])
