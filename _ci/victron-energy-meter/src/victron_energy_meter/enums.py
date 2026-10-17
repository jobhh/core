"""Enumerations the Victron energy meter register map decodes to."""

from __future__ import annotations

from enum import IntEnum, IntFlag


class PhaseConfiguration(IntEnum):
    """How the meter is wired (register 0x2000)."""

    SINGLE_PHASE_L1 = 0
    SINGLE_PHASE_L2 = 1
    SINGLE_PHASE_L3 = 2
    THREE_PHASE = 3
    SPLIT_PHASE = 4

    @property
    def phases(self) -> tuple[int, ...]:
        """The phases the meter measures in this configuration."""
        return {
            PhaseConfiguration.SINGLE_PHASE_L1: (1,),
            PhaseConfiguration.SINGLE_PHASE_L2: (2,),
            PhaseConfiguration.SINGLE_PHASE_L3: (3,),
            PhaseConfiguration.THREE_PHASE: (1, 2, 3),
            PhaseConfiguration.SPLIT_PHASE: (1, 2),
        }[self]


class Role(IntEnum):
    """What the meter measures (register 0x2001)."""

    GRID = 0
    PV_INVERTER = 1
    GENERATOR = 2
    AC_METER = 3
    EV_CHARGER = 4
    HEAT_PUMP = 5
    WATER_PUMP = 6
    WATER_HEATER = 7


class Position(IntEnum):
    """Where the measured device connects to the inverter (register 0x2022)."""

    AC_INPUT_1 = 0
    AC_OUTPUT = 1
    AC_INPUT_2 = 2


class PhaseSequence(IntEnum):
    """The phase rotation the meter sees (register 0x303B)."""

    L1_L2_L3 = 0
    L1_L3_L2 = 1


class PhaseRotationAlarm(IntEnum):
    """The phase rotation level, bits 1-0 of the alarm register (0x303C)."""

    UNSUPPORTED = 0
    OK = 1
    WARNING = 2
    ALARM = 3


class Capability(IntFlag):
    """What the meter supports (registers 0x2024-0x2025)."""

    ROLE_GRID = 1 << 0
    ROLE_PV_INVERTER = 1 << 1
    ROLE_GENERATOR = 1 << 2
    ROLE_AC_METER = 1 << 3
    ROLE_EV_CHARGER = 1 << 4
    ROLE_HEAT_PUMP = 1 << 5
    SPLIT_PHASE = 1 << 6
    ROLE_WATER_PUMP = 1 << 7
    ROLE_WATER_HEATER = 1 << 8
    PQ_SNAPSHOTS_TIMEOUT = 1 << 9
    UDP_PQ_SNAPSHOTS = 1 << 10
    SINGLE_PHASE_L2 = 1 << 11
    SINGLE_PHASE_L3 = 1 << 12
