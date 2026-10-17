"""The top-level object for a Victron VM-3P75CT or VM-3P5A energy meter."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Final

from modbus_connection.model import Device, Raw, UpdateReport

from .components import (
    Configuration,
    HighRangeCurrents,
    Identity,
    Phase,
    PhaseDetail,
    Totals,
)
from .enums import PhaseConfiguration
from .exceptions import UnsupportedFirmwareError, UnsupportedMeterError
from .models import FirmwareVersion, MeterModel, model_for_product_id

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

UNIT_ID: Final = 1
"""The only unit id the meter answers."""

PORT: Final = 502
"""The UDP port the meter listens on."""

MDNS_SERVICE: Final = "_victron-energy-meter._udp"
"""The mDNS service the meter announces."""

PHASES: Final = (1, 2, 3)

READINGS: Final = (
    "totals",
    *(f"phase_l{n}" for n in PHASES),
    *(f"detail_l{n}" for n in PHASES),
    "high_range_currents",
)
"""The sub-systems ``async_update_readings()`` refreshes."""

SETTINGS: Final = ("configuration",)
"""The sub-systems ``async_update_settings()`` refreshes."""

ALL: Final = ("identity", *SETTINGS, *READINGS)


async def async_identify(unit: ModbusUnit) -> MeterModel:
    """Read the product id alone and return the model it belongs to.

    Raises ``UnsupportedMeterError`` for a product id this library does not
    know, and modbus-connection's ``ModbusError`` subclasses if the read fails.
    """
    [product_id] = await unit.read_holding_registers(0x1000, 1)
    model = model_for_product_id(product_id)
    if model is None:
        raise UnsupportedMeterError(product_id)
    return model


class VictronEnergyMeter(Device):
    """A VM-3P75CT or VM-3P5A reached through a ``ModbusUnit``.

    The meter speaks Modbus over UDP on port 502, as unit 1. Setup runs on the
    first poll, or explicitly through ``async_ensure_setup()``. It reads the
    identity and the configuration, and settles which phases and registers
    this meter and its firmware serve.
    """

    def __init__(self, unit: ModbusUnit) -> None:
        super().__init__(unit)
        self.identity = Identity(unit)
        self.configuration = Configuration(unit)
        self.totals = Totals(unit)
        self.phase_l1: Phase | None = None
        self.phase_l2: Phase | None = None
        self.phase_l3: Phase | None = None
        self.detail_l1: PhaseDetail | None = None
        self.detail_l2: PhaseDetail | None = None
        self.detail_l3: PhaseDetail | None = None
        self.high_range_currents: HighRangeCurrents | None = None
        self._model: MeterModel | None = None
        self._firmware: FirmwareVersion | None = None
        self._phase_configuration: PhaseConfiguration | None = None

    async def _async_setup(self) -> None:
        """Identify the meter and settle what it serves."""
        await self.identity.async_update()
        product_id = self.identity.product_id
        model = model_for_product_id(product_id) if product_id is not None else None
        if model is None:
            raise UnsupportedMeterError(product_id)
        words = self.identity.firmware_words
        assert words is not None  # the identity read succeeded
        firmware = FirmwareVersion.from_words(*words)
        # Older firmware serves no measurements over Modbus.
        if not firmware.at_least(1, 3, 1):
            raise UnsupportedFirmwareError(
                f"{model.name} firmware {firmware} reports no measurements; "
                "update it to v1.03 or newer"
            )

        await self.configuration.async_update()
        # Single phase on L1 is 0, so test for None rather than truthiness.
        phase_configuration = self.configuration.phase_configuration
        if phase_configuration is None:
            phase_configuration = PhaseConfiguration.THREE_PHASE
        unit = self.modbus_unit
        has_detail = firmware.at_least(1, 7)
        has_v109 = firmware.at_least(1, 9)

        for n in phase_configuration.phases:
            phase = Phase(unit, base_offset=0x10 * (n - 1))
            if model.high_range_current:
                phase.restrict_fields(
                    [name for name in phase.declared_fields if name != "current"]
                )
            setattr(self, f"phase_l{n}", phase)
            if has_detail:
                detail = PhaseDetail(unit, base_offset=8 * (n - 1))
                if not has_v109:
                    detail.restrict_fields(["voltage_line_to_line"])
                setattr(self, f"detail_l{n}", detail)

        if model.high_range_current:
            currents = HighRangeCurrents(unit)
            currents.restrict_fields(
                [f"current_l{n}" for n in phase_configuration.phases]
            )
            self.high_range_currents = currents

        totals = list(Totals.declared_fields)
        if not has_detail:
            totals.remove("neutral_current")
        if not has_v109:
            for name in ("power_factor", "phase_sequence", "_alarms"):
                totals.remove(name)
        self.totals.restrict_fields(totals)
        if not has_v109:
            self.configuration.restrict_fields(
                [n for n in Configuration.declared_fields if n != "capabilities"]
            )

        self._model = model
        self._firmware = firmware
        self._phase_configuration = phase_configuration

    # -- identity ------------------------------------------------------------

    @property
    def model(self) -> MeterModel | None:
        """The meter model, once setup has run."""
        return self._model

    @property
    def firmware_version(self) -> FirmwareVersion | None:
        """The firmware version, once setup has run."""
        return self._firmware

    @property
    def serial_number(self) -> str | None:
        """The serial number."""
        serial = self.identity.serial_number
        if serial is None:
            return None
        return serial.strip() or None

    @property
    def phases(self) -> tuple[int, ...]:
        """The phases this meter measures, as set up."""
        if self._phase_configuration is None:
            return ()
        return self._phase_configuration.phases

    @property
    def configuration_changed(self) -> bool:
        """Whether the phase configuration differs from the one set up with.

        The set of polled registers follows the phase configuration, so a
        consumer should build a new ``VictronEnergyMeter`` when this is true.
        """
        current = self.configuration.phase_configuration
        return current is not None and current != self._phase_configuration

    # -- readings --------------------------------------------------------------

    def phase(self, n: int) -> Phase | None:
        """The main block of phase ``n`` (1-3), or ``None`` if not measured."""
        phase: Phase | None = getattr(self, f"phase_l{n}")
        return phase

    def detail(self, n: int) -> PhaseDetail | None:
        """The line voltage and power factor of phase ``n``, if served."""
        detail: PhaseDetail | None = getattr(self, f"detail_l{n}")
        return detail

    def current(self, n: int) -> float | None:
        """The current of phase ``n`` in A, from wherever this model reports it."""
        if self.high_range_currents is not None:
            current: float | None = getattr(self.high_range_currents, f"current_l{n}")
            return current
        phase = self.phase(n)
        return phase.current if phase is not None else None

    # -- polling ---------------------------------------------------------------

    async def async_update_readings(self) -> UpdateReport:
        """Refresh what the meter measures."""
        return await self.async_poll(READINGS)

    async def async_update_settings(self) -> UpdateReport:
        """Refresh how the meter is configured."""
        return await self.async_poll(SETTINGS)

    async def async_update(self) -> UpdateReport:
        """Refresh every polled sub-system."""
        report = await self.async_poll(READINGS)
        return await self.async_poll(SETTINGS, report)

    async def async_read_raw(self, names: Iterable[str] = ALL) -> Raw:
        """Every register this meter reads, undecoded, for diagnostics."""
        return await super().async_read_raw(names)
