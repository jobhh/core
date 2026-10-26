"""Diagnostics support for the Carlo Gavazzi Modbus integration."""

from typing import Any

from carlo_gavazzi_energy_meter_modbus import EM500Meter, Meter, em300, em500
from modbus_connection import ModbusError
from modbus_connection.model import Component, RegisterField

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import CarloGavazziModbusConfigEntry

TO_REDACT = {"serial_number"}

# The registers holding the serial number, dropped from the raw dump.
SERIAL_REGISTERS = range(0x5000, 0x5007)


def _component_data(component: Component | None) -> dict[str, Any] | None:
    """Every decoded register field and computed property of a component.

    ``None`` for a block this meter does not serve.
    """
    if component is None:
        return None
    names = {
        name
        for klass in type(component).__mro__
        if issubclass(klass, Component) and klass is not Component
        for name, attribute in vars(klass).items()
        if not name.startswith("_") and isinstance(attribute, (RegisterField, property))
    }
    return {name: getattr(component, name) for name in sorted(names)}


async def _async_read_whole(
    meter: Meter, names: tuple[str, ...]
) -> tuple[dict[str, Component | None], dict[str, dict[int, int | bool]]]:
    """Read fresh, whole copies of the named sub-systems, decoded and raw.

    The polled sub-systems may be cut down to what the entities show.
    """
    components: dict[str, Component | None] = {}
    raw: dict[str, dict[int, int | bool]] = {}
    for name in names:
        if (component := getattr(meter, name)) is None:
            components[name] = None
            continue
        fresh = type(component)(meter.modbus_unit)
        await fresh.async_update()
        components[name] = fresh
        for space, registers in (await fresh.async_read_raw()).items():
            raw.setdefault(space, {}).update(registers)
    return components, raw


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CarloGavazziModbusConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    The decoded values, what the last poll got, and every register the meter
    serves undecoded, read fresh: a value the integration decodes wrongly can
    only be told from what the meter sent.
    """
    coordinator = entry.runtime_data.coordinator
    meter = coordinator.meter
    names = em500.ALL if isinstance(meter, EM500Meter) else em300.ALL

    # Without an answer, what the polls last read is all there is.
    components: dict[str, Component | None] = {
        name: getattr(meter, name) for name in names
    }
    raw: dict[str, dict[int, int | bool]] | None = None
    raw_error: str | None = None
    try:
        components, raw = await _async_read_whole(meter, names)
    except ModbusError as err:
        raw_error = str(err) or type(err).__name__
    if raw is not None:
        for registers in raw.values():
            for address in SERIAL_REGISTERS:
                registers.pop(address, None)

    data: dict[str, Any] = {
        "wide_reads": meter.wide_reads if isinstance(meter, EM500Meter) else None,
        "poll": {
            "duration": (
                coordinator.last_poll_duration.total_seconds()
                if coordinator.last_poll_duration is not None
                else None
            ),
            "updated": sorted(coordinator.data.updated),
            "failed": {
                subsystem: str(error) or type(error).__name__
                for subsystem, error in coordinator.data.failed.items()
            },
        },
        **{name: _component_data(component) for name, component in components.items()},
        "raw": raw,
        "raw_error": raw_error,
    }
    return async_redact_data(data, TO_REDACT)
