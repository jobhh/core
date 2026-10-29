"""DataUpdateCoordinator for the Carlo Gavazzi Modbus integration."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import override

from carlo_gavazzi_energy_meter_modbus import EM500Meter, UpdateReport
from carlo_gavazzi_energy_meter_modbus.em500 import READINGS
from modbus_connection import ModbusError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER, SCAN_INTERVAL

type CarloGavazziModbusConfigEntry = ConfigEntry[CarloGavazziModbusRuntimeData]


def _merge(first: UpdateReport, retry: UpdateReport) -> UpdateReport:
    """Fold a retry of some failed sub-systems into the poll it followed."""
    return UpdateReport(
        updated=first.updated | retry.updated,
        failed={
            subsystem: retry.failed.get(subsystem, error)
            for subsystem, error in first.failed.items()
            if subsystem not in retry.updated
        },
    )


class CarloGavazziModbusDataUpdateCoordinator(DataUpdateCoordinator[UpdateReport]):
    """Polls what an EM530 or EM540 measures.

    A poll can come back partial: the library reads every sub-system on its
    own, and the report names what refreshed, which is what entities read
    their availability from.
    """

    config_entry: CarloGavazziModbusConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: CarloGavazziModbusConfigEntry,
        meter: EM500Meter,
    ) -> None:
        """Initialize the coordinator."""
        self.meter = meter
        self._silent: set[str] = set()
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=SCAN_INTERVAL,
        )

    @override
    async def _async_update_data(self) -> UpdateReport:
        """Poll the meter, reporting what answered."""
        try:
            report = await self.meter.async_poll(READINGS)
        except ModbusError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="communication_error",
            ) from err

        # Retry only what just fell silent, so a lost frame does not blank
        # entities and a block that stays silent does not double every poll.
        if retry := report.failed.keys() - self._silent:
            report = await self._async_retry(report, retry)

        self._log_silence(report)
        return report

    async def _async_retry(
        self, report: UpdateReport, names: Iterable[str]
    ) -> UpdateReport:
        """Poll the named sub-systems again, keeping the report if that dies."""
        try:
            retried = await self.meter.async_poll(names)
        except ModbusError as err:
            LOGGER.debug(
                "%s: the retry failed (%s); keeping the poll",
                self.name,
                type(err).__name__,
            )
            return report
        return _merge(report, retried)

    def _log_silence(self, report: UpdateReport) -> None:
        """Log a sub-system falling silent once, and log its return."""
        for subsystem, error in report.failed.items():
            if subsystem not in self._silent:
                self._silent.add(subsystem)
                # The error's text can name the port, which may carry an
                # ESPHome encryption key.
                LOGGER.warning(
                    "%s: %s did not answer this poll: %s",
                    self.name,
                    subsystem,
                    type(error).__name__,
                )

        for subsystem in report.updated & self._silent:
            self._silent.discard(subsystem)
            LOGGER.info("%s: %s is answering again", self.name, subsystem)


@dataclass(kw_only=True)
class CarloGavazziModbusRuntimeData:
    """Runtime data for a Carlo Gavazzi Modbus config entry."""

    coordinator: CarloGavazziModbusDataUpdateCoordinator
    device_info: DeviceInfo
