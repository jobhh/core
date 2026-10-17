"""Fixtures: Victron energy meters on modbus-connection's in-memory mock backend.

Values are written as the meter encodes them: big endian, high word first.
``VM_3P75CT`` describes a three-phase grid meter on firmware v1.09.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from modbus_connection.mock import MockModbusUnit

from victron_energy_meter import VictronEnergyMeter


def words(value: int, count: int) -> list[int]:
    """Encode ``value`` over ``count`` registers, high word first."""
    raw = value & ((1 << (16 * count)) - 1)
    return [(raw >> (16 * (count - 1 - i))) & 0xFFFF for i in range(count)]


def int16(value: int) -> int:
    """Encode a signed 16-bit value as its register word."""
    return value & 0xFFFF


def ascii_words(text: str, count: int) -> list[int]:
    """Pack text into ``count`` registers, two characters each (high, low)."""
    padded = text.ljust(count * 2, "\0")[: count * 2]
    return [(ord(padded[i]) << 8) | ord(padded[i + 1]) for i in range(0, count * 2, 2)]


def flatten(registers: Mapping[int, int | list[int]]) -> dict[int, int]:
    """Spread multi-register values so every address has its own entry."""
    flat: dict[int, int] = {}
    for address, value in registers.items():
        values = value if isinstance(value, list) else [value]
        for offset, word in enumerate(values):
            flat[address + offset] = word
    return flat


SERIAL = "HQ2401ABCDE"
FIRMWARE_V109 = [0x0001, 0x09FF]  # v1.09, release

VM_3P75CT: dict[int, int] = flatten(
    {
        # -- identity --
        0x1000: 0xA1B1,
        0x1001: ascii_words(SERIAL, 8),
        0x1009: FIRMWARE_V109,
        0x100B: 3,  # hardware revision
        # -- configuration --
        0x2000: 3,  # three-phase
        0x2001: 0,  # grid
        0x2002: ascii_words("Grid meter", 32),
        0x2022: 0,  # AC input 1
        0x2023: 1,  # system instance
        0x2024: words(0x0000_1FFF, 2),  # every capability bit 0-12
        # -- phase L1 --
        0x3000: 23012,  # 230.12 V
        0x3001: 543,  # 5.43 A
        0x3002: words(1200, 2),  # 1200 W
        0x3004: words(1250, 2),  # 1250 VA
        0x3006: words(1_234_567, 2),  # 12345.67 kWh
        0x3008: words(23_456, 2),  # 234.56 kWh
        # -- phase L2 --
        0x3010: 23120,  # 231.20 V
        0x3011: int16(-123),  # -1.23 A (exporting)
        0x3012: words(-250, 2),  # -250 W
        0x3014: words(300, 2),  # 300 VA
        0x3016: words(500_000, 2),  # 5000.00 kWh
        0x3018: words(100_000, 2),  # 1000.00 kWh
        # -- phase L3 --
        0x3020: 22980,  # 229.80 V
        0x3021: 57,  # 0.57 A
        0x3022: words(100, 2),  # 100 W
        0x3024: words(130, 2),  # 130 VA
        0x3026: words(400_000, 2),  # 4000.00 kWh
        0x3028: words(0, 2),
        # -- totals --
        0x3030: words(1050, 2),  # 1050 W
        0x3032: 5001,  # 50.01 Hz
        0x3033: 12,  # 0.12 V PE-N
        0x3034: words(2_134_567, 2),  # 21345.67 kWh
        0x3036: words(123_456, 2),  # 1234.56 kWh
        0x3038: 0,  # no error
        0x3039: 45,  # 0.45 A neutral, per the manual's 0.01 A
        0x303A: 625,  # 0.625
        0x303B: 0,  # L1-L2-L3
        0x303C: words(0b01, 2),  # phase rotation OK
        0x303E: 50012,  # 50.012 Hz
        # -- phase details --
        0x3046: 39850,  # L1-L2 398.50 V
        0x3047: 960,  # 0.960
        0x304E: 40010,  # 400.10 V
        0x304F: int16(-834),  # -0.834
        0x3056: 39790,  # 397.90 V
        0x3057: 767,  # 0.767
    }
)


def seed(unit: MockModbusUnit, registers: Mapping[int, int] = VM_3P75CT) -> None:
    """Load ``registers`` into the holding store of ``unit``."""
    unit.holding.update(registers)


@pytest.fixture
def vm_3p75ct(mock_modbus_unit: MockModbusUnit) -> MockModbusUnit:
    """The mock unit, answering as a three-phase VM-3P75CT on firmware v1.09."""
    seed(mock_modbus_unit)
    return mock_modbus_unit


@pytest.fixture
def meter(vm_3p75ct: MockModbusUnit) -> VictronEnergyMeter:
    """A ``VictronEnergyMeter`` on the seeded mock unit."""
    return VictronEnergyMeter(vm_3p75ct)
