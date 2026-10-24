"""Support for Carlo Gavazzi energy meters over Modbus.

The meter is a Modbus device. This integration does not own its connection:
it borrows a ``ModbusUnit`` from the ``modbus`` integration, which shares one
connection per serial port between everything talking on that bus, and hands
that unit to the ``carlo-gavazzi-energy-meter-modbus`` library.
"""

from typing import TYPE_CHECKING

from carlo_gavazzi_energy_meter_modbus import UnsupportedMeterError
from modbus_connection import ModbusError

from homeassistant.components.modbus import async_get_unit
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
)

from .const import CONF_UNIT_ID, DOMAIN
from .coordinator import (
    CarloGavazziModbusConfigEntry,
    CarloGavazziModbusDataUpdateCoordinator,
    CarloGavazziModbusRuntimeData,
)
from .entity import meter_device_info
from .helpers import async_setup_meter, create_modbus_params

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: CarloGavazziModbusConfigEntry
) -> None:
    """Set up Carlo Gavazzi Modbus from a config entry."""
    serial_number = entry.unique_id
    if TYPE_CHECKING:
        assert serial_number is not None

    try:
        unit = async_get_unit(
            hass, entry, create_modbus_params(entry.data), entry.data[CONF_UNIT_ID]
        )
    except HomeAssistantError as err:
        # The port is already in use at other line settings, which one shared
        # connection cannot honour.
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="link_settings_in_use",
            translation_placeholders={"error": str(err)},
        ) from err

    try:
        meter = await async_setup_meter(unit)
    except ModbusError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="communication_error",
            translation_placeholders={"error": str(err) or type(err).__name__},
        ) from err
    except UnsupportedMeterError as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="unsupported_meter",
        ) from err

    # The address can come to point at another meter, such as after rewiring
    # the bus; every identity here derives from the serial number.
    if meter.serial_number != serial_number:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="wrong_meter",
        )

    coordinator = CarloGavazziModbusDataUpdateCoordinator(hass, entry, meter)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = CarloGavazziModbusRuntimeData(
        coordinator=coordinator,
        device_info=meter_device_info(meter, serial_number),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(
    hass: HomeAssistant, entry: CarloGavazziModbusConfigEntry
) -> None:
    """Unload a Carlo Gavazzi Modbus config entry."""
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
