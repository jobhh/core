"""Helpers for the Carlo Gavazzi Modbus integration."""

from collections.abc import Mapping
from typing import Any

from carlo_gavazzi_energy_meter_modbus import Meter, async_identify, create_meter
from modbus_connection import ModbusSerialParams, ModbusUnit

from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT, CONF_TYPE

from .const import CONF_BAUDRATE, TYPE_GATEWAY


def create_modbus_params(data: Mapping[str, Any]) -> ModbusSerialParams:
    """Build the Modbus link parameters from config entry data.

    The library's serial defaults are 8N1, which is what the meters speak out
    of the box; only the baud rate is worth asking for.
    """
    if data[CONF_TYPE] == TYPE_GATEWAY:
        # A transparent gateway passes RTU frames through, so it is a serial
        # link over a socket. An IPv6 literal needs brackets in the URL.
        host = data[CONF_HOST]
        if ":" in host:
            host = f"[{host}]"
        return ModbusSerialParams(
            device=f"socket://{host}:{data[CONF_PORT]}", framer="rtu"
        )
    return ModbusSerialParams(device=data[CONF_DEVICE], baudrate=data[CONF_BAUDRATE])


async def async_setup_meter(unit: ModbusUnit) -> Meter:
    """Identify the meter on ``unit`` and return it, set up.

    The model code alone tells the series, and with it the register map.
    """
    meter = create_meter(unit, await async_identify(unit))
    await meter.async_ensure_setup()
    return meter
