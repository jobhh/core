"""Data update coordinator for the Victron Energy Meter integration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import override

from modbus_connection import ModbusError
from modbus_connection.model import UpdateReport

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .helpers import Meter, manufacturer, meter_name

_LOGGER = logging.getLogger(__name__)


class VictronMeterCoordinator(DataUpdateCoordinator[UpdateReport]):
    """Poll one category of a meter's sub-systems."""

    config_entry: VictronMeterConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VictronMeterConfigEntry,
        meter: Meter,
        poll: Callable[[], Awaitable[UpdateReport]],
        interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=interval,
        )
        self.meter = meter
        self._poll = poll

    @override
    async def _async_update_data(self) -> UpdateReport:
        try:
            report = await self._poll()
        except ModbusError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err) or type(err).__name__},
            ) from err
        if report.failed and not report.updated:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="no_answer",
            ) from ExceptionGroup("every sub-system failed", list(report.failed.values()))
        return report


def device_info(meter: Meter) -> dr.DeviceInfo:
    """Describe the meter for the device registry."""
    model = meter.model
    assert model is not None
    serial = meter.serial_number
    info = dr.DeviceInfo(
        identifiers={(DOMAIN, str(serial))},
        name=meter_name(meter),
        manufacturer=manufacturer(meter),
        model=meter_name(meter),
        serial_number=serial,
    )
    if (firmware := meter.firmware_version) is not None:
        info["sw_version"] = str(firmware)
    if part_number := getattr(model, "part_number", None):
        info["model_id"] = part_number
    return info


@dataclass
class VictronMeterRuntimeData:
    """What a loaded entry holds."""

    meter: Meter
    readings: VictronMeterCoordinator
    settings: VictronMeterCoordinator
    device_info: dr.DeviceInfo


type VictronMeterConfigEntry = ConfigEntry[VictronMeterRuntimeData]
