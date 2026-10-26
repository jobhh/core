"""DataUpdateCoordinator for the Carlo Gavazzi Modbus integration."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
import time
from typing import override

from carlo_gavazzi_energy_meter_modbus import (
    EM500Meter,
    Meter,
    UpdateReport,
    em300,
    em500,
)
from modbus_connection import ModbusError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
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
    """Polls what a Carlo Gavazzi meter measures.

    A poll can come back partial: the library reads every sub-system on its
    own, and the report names what refreshed, which is what entities read
    their availability from.

    Only what enabled entities show is read. Each entity names its field when
    it is added; a sub-system nobody wants is skipped, and the others are read
    for just the wanted fields. Enabling an entity reloads the entry, which
    starts over with every field.
    """

    config_entry: CarloGavazziModbusConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: CarloGavazziModbusConfigEntry,
        meter: Meter,
    ) -> None:
        """Initialize the coordinator."""
        self.meter = meter
        self.last_poll_duration: timedelta | None = None
        self._silent: set[str] = set()
        self._readings: tuple[str, ...] = (
            em500.READINGS if isinstance(meter, EM500Meter) else em300.READINGS
        )
        # Until the entities are added, which happens after the first poll,
        # every sub-system is read.
        self._wanted: dict[str, set[str]] = {}
        self._narrowed = False
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=SCAN_INTERVAL,
        )

    @callback
    def async_want(self, subsystem: str, field: str) -> CALLBACK_TYPE:
        """Have a field read on every poll, until the returned callback runs."""
        self._wanted.setdefault(subsystem, set()).add(field)

        @callback
        def _release() -> None:
            self._wanted[subsystem].discard(field)

        return _release

    def _narrow(self) -> None:
        """Cut wanted sub-systems down to the wanted fields, where that saves reads.

        Only a sub-system that declares the ranges it can be read in is cut
        down: it is read one range at a time, so dropping fields drops whole
        reads. Any other is read as one block across its fields, and cutting
        fields out of the middle would split that block into several reads.

        A read plan can only be narrowed, which is why this happens once, after
        every entity has said what it wants. A field computed from others,
        rather than read, leaves its sub-system as it is.
        """
        self._narrowed = True
        for subsystem, fields in self._wanted.items():
            component = getattr(self.meter, subsystem)
            if (
                fields
                and component.register_ranges is not None
                and fields <= component.resolved_fields.keys()
            ):
                component.restrict_fields(fields)

    @override
    async def _async_update_data(self) -> UpdateReport:
        """Poll the meter, reporting what answered."""
        names = self._readings
        if self._wanted:
            if not self._narrowed:
                self._narrow()
            names = tuple(name for name in names if self._wanted.get(name))

        start = time.monotonic()
        try:
            report = await self.meter.async_poll(names)
        except ModbusError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err) or type(err).__name__},
            ) from err

        # A sub-system that just fell silent is asked once more, so one lost
        # frame on the RS485 bus does not blank its entities. One that stays
        # silent is not, or it would double every poll from here on.
        if retry := report.failed.keys() - self._silent:
            report = await self._async_retry(report, retry)

        self.last_poll_duration = timedelta(seconds=time.monotonic() - start)
        self._log_silence(report)
        return report

    async def _async_retry(
        self, report: UpdateReport, names: Iterable[str]
    ) -> UpdateReport:
        """Poll the named sub-systems again, keeping the report if that dies.

        Values read a moment ago are not stale because the link dropped right
        after; the next poll reports the dead link.
        """
        try:
            retried = await self.meter.async_poll(names)
        except ModbusError as err:
            LOGGER.debug("%s: the retry failed (%s); keeping the poll", self.name, err)
            return report
        return _merge(report, retried)

    def _log_silence(self, report: UpdateReport) -> None:
        """Log a sub-system falling silent once, and log its return."""
        for subsystem, error in report.failed.items():
            if subsystem not in self._silent:
                self._silent.add(subsystem)
                LOGGER.warning(
                    "%s: %s did not answer this poll: %s",
                    self.name,
                    subsystem,
                    str(error) or type(error).__name__,
                )

        for subsystem in report.updated & self._silent:
            self._silent.discard(subsystem)
            LOGGER.info("%s: %s is answering again", self.name, subsystem)


@dataclass(kw_only=True)
class CarloGavazziModbusRuntimeData:
    """Runtime data for a Carlo Gavazzi Modbus config entry."""

    coordinator: CarloGavazziModbusDataUpdateCoordinator
    device_info: DeviceInfo
