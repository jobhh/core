"""Helpers for the Victron Energy Meter integration."""

from collections.abc import Mapping
from typing import Any

from carlo_gavazzi_energy_meter_modbus import (
    Meter as CarloGavazziMeter,
    async_identify as async_identify_carlo_gavazzi,
    create_meter as create_carlo_gavazzi_meter,
)
from modbus_connection import ModbusSerialParams, ModbusUdpParams, ModbusUnit
from victron_energy_meter_modbus import (
    PORT as VICTRON_PORT,
    UNIT_ID as VICTRON_UNIT_ID,
    VictronEnergyMeter,
)

from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT, CONF_TYPE

from .const import CONF_BAUDRATE, CONF_UNIT_ID, LinkType

type Meter = CarloGavazziMeter | VictronEnergyMeter


def create_modbus_params(
    data: Mapping[str, Any],
) -> ModbusSerialParams | ModbusUdpParams:
    """Build the Modbus link parameters from config entry data."""
    match LinkType(data[CONF_TYPE]):
        case LinkType.NETWORK:
            return ModbusUdpParams(host=data[CONF_HOST], port=VICTRON_PORT)
        case LinkType.SERIAL:
            return ModbusSerialParams(
                device=data[CONF_DEVICE], baudrate=data[CONF_BAUDRATE]
            )
        case LinkType.GATEWAY:
            # RTU frames a serial line, so a transparent gateway is a serial
            # link over a socket. An IPv6 literal needs brackets in the URL.
            host = data[CONF_HOST]
            host = f"[{host}]" if ":" in host else host
            return ModbusSerialParams(
                device=f"socket://{host}:{data[CONF_PORT]}", framer="rtu"
            )


def unit_id(data: Mapping[str, Any]) -> int:
    """The Modbus unit id of the meter; a Victron meter answers only as unit 1."""
    if LinkType(data[CONF_TYPE]) is LinkType.NETWORK:
        return VICTRON_UNIT_ID
    return int(data[CONF_UNIT_ID])


async def async_setup_meter(data: Mapping[str, Any], unit: ModbusUnit) -> Meter:
    """Identify the meter on ``unit`` and return its device object, set up.

    A network link reaches Victron's own meters; on a serial link the model
    code tells which Carlo Gavazzi series answers.
    """
    meter: Meter
    if LinkType(data[CONF_TYPE]) is LinkType.NETWORK:
        meter = VictronEnergyMeter(unit)
    else:
        model = await async_identify_carlo_gavazzi(unit)
        meter = create_carlo_gavazzi_meter(unit, model)
    await meter.async_ensure_setup()
    return meter


def meter_name(meter: Meter) -> str:
    """The model name of a set-up meter."""
    model = meter.model
    assert model is not None
    return model.name


def manufacturer(meter: Meter) -> str:
    """Who makes the meter."""
    return (
        "Victron Energy" if isinstance(meter, VictronEnergyMeter) else "Carlo Gavazzi"
    )
