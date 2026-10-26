"""DataUpdateCoordinator for the Carlo Gavazzi Modbus integration."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
import time
from typing import ClassVar, override

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
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER, SCAN_INTERVAL, SETTINGS_SCAN_INTERVAL

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
    """Polls a set of a Carlo Gavazzi meter's sub-systems.

    A poll can come back partial: the library reads every sub-system on its
    own, and the report names what refreshed, which is what entities read
    their availability from.

    The meter's serial number is read at setup, and again once the link comes
    back after nothing answered: replacing a meter takes it off the bus, and
    the one put in its place at the same address must not carry on under the
    old one's entities.

    Only what enabled entities show is read. Each entity names its field when
    it is added; a sub-system nobody wants is skipped, and the others are read
    for just the wanted fields. Enabling an entity reloads the entry, which
    starts over with every field.
    """

    config_entry: CarloGavazziModbusConfigEntry

    narrows: ClassVar[bool] = True
    """Whether the sub-systems are cut down to what enabled entities show."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: CarloGavazziModbusConfigEntry,
        meter: Meter,
        *,
        names: tuple[str, ...],
        interval: timedelta,
        name: str,
    ) -> None:
        """Initialize the coordinator."""
        self.meter = meter
        self.last_poll_duration: timedelta | None = None
        self._silent: set[str] = set()
        self._check_identity = False
        self._names = names
        # Until the entities are added, which happens after the first poll,
        # every sub-system is read.
        self._wanted: dict[str, set[str]] = {}
        self._narrowed = False
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=name,
            update_interval=interval,
        )

    @property
    def subsystems(self) -> tuple[str, ...]:
        """Return the sub-systems this coordinator polls."""
        return self._names

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
        names = self._names
        if self.narrows and self._wanted:
            if not self._narrowed:
                self._narrow()
            names = tuple(name for name in names if self._wanted.get(name))

        start = time.monotonic()
        try:
            if self._check_identity:
                await self._async_check_identity()
            report = await self.meter.async_poll(names)
        except ModbusError as err:
            self._check_identity = True
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

    async def _async_check_identity(self) -> None:
        """Read the serial number, and stop if another meter answers.

        Stays due until it passes, so a wrong meter keeps the entities
        unavailable for as long as it is there.
        """
        await self.meter.identity.async_update()
        if self.meter.serial_number != self.config_entry.unique_id:
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="wrong_meter",
            )
        self._check_identity = False

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
            self._check_identity = True
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


def _layout(meter: Meter) -> tuple[int | None, bool | None, bool | None]:
    """What of the meter's settings decides which entities it has."""
    return meter.phases, meter.has_neutral, meter.measures_export


class CarloGavazziModbusSettingsCoordinator(CarloGavazziModbusDataUpdateCoordinator):
    """Polls how a Carlo Gavazzi meter is configured.

    The settings are read at setup, and the entities follow from them: a
    meter wired without a neutral has no phase-to-neutral voltages, and one
    counting everything as imported no exported energy. They only change on
    the meter's own keys, so they are read seldom, and a change that alters
    the entities reloads the entry.

    Everything is read whatever the entities show, since the reload depends
    on it.
    """

    narrows = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: CarloGavazziModbusConfigEntry,
        meter: Meter,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            entry,
            meter,
            names=em500.SETTINGS if isinstance(meter, EM500Meter) else em300.SETTINGS,
            interval=SETTINGS_SCAN_INTERVAL,
            name=f"{entry.title} settings",
        )
        self._layout = _layout(meter)

    @override
    async def _async_update_data(self) -> UpdateReport:
        """Poll the settings, and reload when the entities no longer fit."""
        report = await super()._async_update_data()
        if _layout(self.meter) != self._layout:
            LOGGER.info(
                "%s: the meter's measuring settings changed, reloading to match",
                self.name,
            )
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        return report


def create_readings_coordinator(
    hass: HomeAssistant, entry: CarloGavazziModbusConfigEntry, meter: Meter
) -> CarloGavazziModbusDataUpdateCoordinator:
    """Return the coordinator polling what the meter measures."""
    return CarloGavazziModbusDataUpdateCoordinator(
        hass,
        entry,
        meter,
        names=em500.READINGS if isinstance(meter, EM500Meter) else em300.READINGS,
        interval=SCAN_INTERVAL,
        name=entry.title,
    )


@dataclass(kw_only=True)
class CarloGavazziModbusRuntimeData:
    """Runtime data for a Carlo Gavazzi Modbus config entry."""

    readings: CarloGavazziModbusDataUpdateCoordinator
    settings: CarloGavazziModbusSettingsCoordinator
    device_info: DeviceInfo

    @property
    def meter(self) -> Meter:
        """Return the polled meter, which both coordinators share."""
        return self.readings.meter

    def coordinator_for(
        self, subsystem: str
    ) -> CarloGavazziModbusDataUpdateCoordinator:
        """Return the coordinator that refreshes a given sub-system."""
        if subsystem in self.settings.subsystems:
            return self.settings
        return self.readings
