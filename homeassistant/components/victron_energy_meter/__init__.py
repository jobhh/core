"""The Victron Energy Meter integration.

The meters are Modbus devices. This integration does not own a connection: it
borrows a ``ModbusUnit`` from the ``modbus`` integration and hands it to the
library for the kind of meter. Victron's VM-3P75CT and VM-3P5A use
``victron-energy-meter``; the Carlo Gavazzi meters Victron sells use
``carlo-gavazzi-modbus``.
"""

from carlo_gavazzi_modbus import UnsupportedMeterError as CarloGavazziUnsupported
from modbus_connection import ModbusError
from victron_energy_meter import (
    UnsupportedFirmwareError,
    UnsupportedMeterError as VictronUnsupported,
    VictronEnergyMeter,
)

from homeassistant.components.modbus import async_get_unit
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
)

from .const import DOMAIN, SCAN_INTERVAL, SETTINGS_SCAN_INTERVAL
from .coordinator import (
    VictronMeterConfigEntry,
    VictronMeterCoordinator,
    VictronMeterRuntimeData,
    device_info,
)
from .helpers import async_setup_meter, create_modbus_params, unit_id

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: VictronMeterConfigEntry
) -> bool:
    """Set up a Victron energy meter from a config entry."""
    try:
        unit = async_get_unit(
            hass, entry, create_modbus_params(entry.data), unit_id(entry.data)
        )
    except HomeAssistantError as err:
        # The port is already in use with other link settings.
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="link_settings_in_use",
            translation_placeholders={"error": str(err)},
        ) from err

    try:
        meter = await async_setup_meter(entry.data, unit)
    except ModbusError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="communication_error",
            translation_placeholders={"error": str(err) or type(err).__name__},
        ) from err
    except (CarloGavazziUnsupported, VictronUnsupported) as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="unsupported_meter",
        ) from err
    except UnsupportedFirmwareError as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="unsupported_firmware",
        ) from err

    # The address can come to point at another meter, such as after a DHCP
    # lease is handed out again; every identity here derives from the serial.
    if meter.serial_number != entry.unique_id:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="wrong_meter",
        )

    readings = VictronMeterCoordinator(
        hass, entry, meter, meter.async_update_readings, SCAN_INTERVAL
    )
    settings = VictronMeterCoordinator(
        hass, entry, meter, meter.async_update_settings, SETTINGS_SCAN_INTERVAL
    )
    await readings.async_config_entry_first_refresh()
    await settings.async_config_entry_first_refresh()

    entry.runtime_data = VictronMeterRuntimeData(
        meter=meter,
        readings=readings,
        settings=settings,
        device_info=device_info(meter),
    )

    if isinstance(meter, VictronEnergyMeter):
        # Which phases are polled is settled at setup.
        @callback
        def _async_reload_on_reconfigure() -> None:
            if meter.configuration_changed:
                hass.config_entries.async_schedule_reload(entry.entry_id)

        entry.async_on_unload(settings.async_add_listener(_async_reload_on_reconfigure))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: VictronMeterConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
