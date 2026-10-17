"""The meter's register blocks, one component each.

The meter answers function 03h only, and refuses a read that crosses from one
block into the next. Each component declares its block as its readable range,
so the planner never crosses it. All values are big endian, high word first.

The register map follows the Modbus appendix of the VM-3P5A manual, checked
against Victron's open-source GX driver (dbus-modbus-client).
"""

from __future__ import annotations

from typing import Final

from modbus_connection.model import (
    Component,
    NumberField,
    RegisterSpace,
    enum,
    flags,
    gauge,
    int32,
    integer,
    string,
    uint32,
)

from .enums import (
    Capability,
    PhaseConfiguration,
    PhaseRotationAlarm,
    PhaseSequence,
    Position,
    Role,
)

INT16_INVALID: Final = 0x7FFF
UINT16_INVALID: Final = 0xFFFF
INT32_INVALID: Final = 0x7FFFFFFF
UINT32_INVALID: Final = 0xFFFFFFFF

MAX_REGISTERS_PER_READ: Final = 125


class VictronComponent(Component):
    """A register block of a Victron energy meter."""

    register_space: RegisterSpace = "holding"
    max_span = MAX_REGISTERS_PER_READ


def _voltage(address: int) -> NumberField[float]:
    return gauge(address, 0.01, nan=INT16_INVALID, unit="V")


def _current(address: int) -> NumberField[float]:
    return gauge(address, 0.01, nan=INT16_INVALID, unit="A")


def _power(address: int, unit: str) -> NumberField[float]:
    return int32(address, nan=INT32_INVALID, unit=unit)


def _energy(address: int) -> NumberField[float]:
    return uint32(address, scale=0.01, nan=UINT32_INVALID, unit="kWh")


class Identity(VictronComponent):
    """Product id, serial number, firmware and hardware (0x1000 block)."""

    register_ranges = ((0x1000, 0x100B),)

    product_id = integer(0x1000, signed=False)
    serial_number = string(0x1001, 8)
    _firmware = uint32(0x1009)
    hardware_version = integer(0x100B, signed=False)

    @property
    def firmware_words(self) -> tuple[int, int] | None:
        """The firmware version registers, high word first."""
        value = self._firmware
        if value is None:
            return None
        return (value >> 16) & 0xFFFF, value & 0xFFFF


class Configuration(VictronComponent):
    """How the meter is set up (0x2000 block).

    The meter is configured in VictronConnect. Over Modbus these are read only.
    """

    register_ranges = ((0x2000, 0x2025),)

    phase_configuration = enum(0x2000, PhaseConfiguration)
    role = enum(0x2001, Role)
    description = string(0x2002, 32)
    """The name the user gave the meter, up to 64 characters."""

    position = enum(0x2022, Position)
    """Where the measured device connects. Meaningful for some roles only."""

    system_instance = integer(0x2023, signed=False)
    capabilities = flags(0x2024, Capability, count=2)


class Totals(VictronComponent):
    """System totals and grid values (0x3030-0x303F, in the 0x3000 block)."""

    register_ranges = ((0x3000, 0x303F),)

    active_power = _power(0x3030, "W")
    """The total real power. Negative while exporting."""

    frequency = gauge(0x3032, 0.01, nan=UINT16_INVALID, signed=False, unit="Hz")
    pe_n_voltage = _voltage(0x3033)
    """The voltage between protective earth and neutral."""

    energy_forward = _energy(0x3034)
    """Imported energy, all phases."""

    energy_reverse = _energy(0x3036)
    """Exported energy, all phases."""

    error_code = integer(0x3038, signed=False)

    neutral_current = _current(0x3039)
    """The neutral current. Firmware v1.07 and newer.

    The manual gives 0.01 A. Victron's GX driver divides by 10 instead; this
    library follows the manual until a real meter settles it.
    """

    power_factor = gauge(0x303A, 0.001, nan=INT16_INVALID)
    """The total power factor. Firmware v1.09 and newer."""

    phase_sequence = enum(0x303B, PhaseSequence, nan=0xFF)
    """The phase rotation. Firmware v1.09 and newer."""

    _alarms = uint32(0x303C)

    frequency_precise = gauge(
        0x303E, 0.001, nan=(0, UINT16_INVALID), signed=False, unit="Hz"
    )
    """The frequency in mHz resolution. Absent (0) on older firmware."""

    @property
    def phase_rotation_alarm(self) -> PhaseRotationAlarm | None:
        """The phase rotation level, bits 1-0 of the alarm register.

        Firmware v1.09 and newer.
        """
        alarms = self._alarms
        return None if alarms is None else PhaseRotationAlarm(alarms & 0b11)


class Phase(VictronComponent):
    """One phase's main block: L1 at 0x3000, L2 at 0x3010, L3 at 0x3020.

    Place it with ``base_offset=0x10 * (phase - 1)``. The range is the phase's
    own sixteen registers, so it moves with the placement.
    """

    register_ranges = ((0x3000, 0x300F),)

    voltage = _voltage(0x3000)
    current = _current(0x3001)
    """The current, VM-3P75CT only. The VM-3P5A reports it in HighRangeCurrents."""

    active_power = _power(0x3002, "W")
    apparent_power = _power(0x3004, "VA")
    energy_forward = _energy(0x3006)
    energy_reverse = _energy(0x3008)


class PhaseDetail(VictronComponent):
    """One phase's line-to-line voltage and power factor (0x3040 block).

    L1 sits at 0x3046, L2 at 0x304E, L3 at 0x3056. Place it with
    ``base_offset=8 * (phase - 1)``. Firmware v1.07 adds the line voltage,
    v1.09 the power factor.
    """

    register_ranges = ((0x3046, 0x3047),)

    voltage_line_to_line = gauge(
        0x3046, 0.01, nan=UINT16_INVALID, signed=False, unit="V"
    )
    power_factor = gauge(0x3047, 0.001, nan=INT16_INVALID)


class HighRangeCurrents(VictronComponent):
    """The phase currents of a VM-3P5A, as 32-bit values (0x3058-0x305D)."""

    register_ranges = ((0x3040, 0x305F),)

    current_l1 = int32(0x3058, scale=0.01, nan=INT32_INVALID, unit="A")
    current_l2 = int32(0x305A, scale=0.01, nan=INT32_INVALID, unit="A")
    current_l3 = int32(0x305C, scale=0.01, nan=INT32_INVALID, unit="A")
