"""Diagnostics support for the Victron Energy Meter integration."""

from typing import Any

from modbus_connection import ModbusError
from victron_energy_meter import VictronEnergyMeter

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import VictronMeterConfigEntry
from .helpers import meter_name

TO_REDACT = {"serial_number", "host", "unique_id"}

# The registers holding the serial number, dropped from the raw dump.
_CARLO_GAVAZZI_SERIAL_REGISTERS = range(0x5000, 0x5007)
_VICTRON_SERIAL_REGISTERS = range(0x1001, 0x1009)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VictronMeterConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime_data = entry.runtime_data
    meter = runtime_data.meter
    raw: dict[str, dict[int, int | bool]] | None = None
    read_error = None
    try:
        raw = await meter.async_read_raw()
    except ModbusError as err:
        read_error = type(err).__name__

    if raw is not None:
        serial_registers = (
            _VICTRON_SERIAL_REGISTERS
            if isinstance(meter, VictronEnergyMeter)
            else _CARLO_GAVAZZI_SERIAL_REGISTERS
        )
        for space in raw.values():
            for address in serial_registers:
                space.pop(address, None)

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "meter": async_redact_data(
            {
                "model": meter_name(meter),
                "firmware": str(meter.firmware_version),
                "serial_number": meter.serial_number,
            },
            TO_REDACT,
        ),
        "readings_failed": sorted(runtime_data.readings.data.failed),
        "settings_failed": sorted(runtime_data.settings.data.failed),
        "read_error": read_error,
        "raw": raw,
    }
