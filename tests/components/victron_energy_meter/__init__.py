"""Tests for the Victron Energy Meter integration."""

from collections.abc import Mapping

from modbus_connection.mock import MockModbusUnit

from homeassistant.components.victron_energy_meter.const import (
    CONF_BAUDRATE,
    CONF_UNIT_ID,
    LinkType,
)
from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT, CONF_TYPE

EM540_SERIAL = "BX12345678901"
EM540_PFC = 1763
VM_SERIAL = "HQ2401ABCDE"

SERIAL_INPUT = {CONF_DEVICE: "/dev/ttyUSB0", CONF_BAUDRATE: 9600, CONF_UNIT_ID: 1}
GATEWAY_INPUT = {CONF_HOST: "192.168.1.60", CONF_PORT: 502, CONF_UNIT_ID: 1}
NETWORK_INPUT = {CONF_HOST: "192.168.1.70"}

SERIAL_ENTRY_DATA = {CONF_TYPE: LinkType.SERIAL, **SERIAL_INPUT}
GATEWAY_ENTRY_DATA = {CONF_TYPE: LinkType.GATEWAY, **GATEWAY_INPUT}
NETWORK_ENTRY_DATA = {CONF_TYPE: LinkType.NETWORK, **NETWORK_INPUT}


def _little(value: int, count: int) -> list[int]:
    """Encode ``value`` over ``count`` registers, low word first."""
    raw = value & ((1 << (16 * count)) - 1)
    return [(raw >> (16 * i)) & 0xFFFF for i in range(count)]


def _big(value: int, count: int) -> list[int]:
    """Encode ``value`` over ``count`` registers, high word first."""
    raw = value & ((1 << (16 * count)) - 1)
    return [(raw >> (16 * (count - 1 - i))) & 0xFFFF for i in range(count)]


def _ascii(text: str, count: int) -> list[int]:
    """Pack text into ``count`` registers, two characters each."""
    padded = text.ljust(count * 2, "\0")[: count * 2]
    return [(ord(padded[i]) << 8) | ord(padded[i + 1]) for i in range(0, count * 2, 2)]


def _flatten(registers: Mapping[int, int | list[int]]) -> dict[int, int]:
    flat: dict[int, int] = {}
    for address, value in registers.items():
        for offset, word in enumerate(value if isinstance(value, list) else [value]):
            flat[address + offset] = word
    return flat


EM540_INPUT = _flatten(
    {
        0x0000: _little(2301, 2),
        0x0002: _little(2312, 2),
        0x0004: _little(2298, 2),
        0x0006: _little(3985, 2),
        0x0008: _little(4001, 2),
        0x000A: _little(3979, 2),
        0x000C: _little(5432, 2),
        0x000E: _little(1234, 2),
        0x0010: _little(567, 2),
        0x0012: _little(12005, 2),
        0x0014: _little(-2503, 2),
        0x0016: _little(1000, 2),
        0x0018: _little(12500, 2),
        0x001A: _little(3002, 2),
        0x001C: _little(1304, 2),
        0x001E: _little(3001, 2),
        0x0020: _little(-502, 2),
        0x0022: _little(800, 2),
        0x0024: _little(2304, 2),
        0x0026: _little(3988, 2),
        0x0028: _little(10502, 2),
        0x002A: _little(16806, 2),
        0x002C: _little(3299, 2),
        0x002E: 960,
        0x002F: -834 & 0xFFFF,
        0x0030: 767,
        0x0031: 625,
        0x0032: 1,
        0x0033: 500,
        0x0046: _little(12345, 2),
        0x0048: _little(678, 2),
        0x0076: [1, 0xFFFF, 1, 1],
        0x0082: _little(312, 2),
        0x0098: _little(123, 2),
        0x00BE: _little(8800, 2),
        0x00C0: _little(52000, 2),
        0x0300: [0, 1],
        0x0302: 0x4302,
        0x0306: 0,
        0x1105: 0,
        0x0500: _little(12_345_678, 4),
        0x051C: _little(2_500_000, 4),
        0x0534: _little(123_456, 2),
        0x053E: _little(234_567, 2),
        0x5000: _ascii(EM540_SERIAL + "Z", 7),
        0x5007: 2023,
        0x5012: 0,
    }
)

EM540_HOLDING = _flatten(
    {
        0x1002: 0,  # 3Pn
        0x1010: _little(3, 2),
        0x1101: 1,
        0x1103: 2,  # mode C: export counters move
        0x1104: 1,
        0x1200: 1,
        0x1201: 1,
    }
)

VM_HOLDING = _flatten(
    {
        0x1000: 0xA1B1,
        0x1001: _ascii(VM_SERIAL, 8),
        0x1009: [0x0001, 0x09FF],  # v1.09
        0x100B: 3,
        0x2000: 3,
        0x2001: 0,
        0x2002: _ascii("Grid meter", 32),
        0x2024: _big(0x1FFF, 2),
        0x3000: [23012, 543],
        0x3002: _big(1200, 2) + _big(1250, 2) + _big(1_234_567, 2) + _big(23_456, 2),
        0x3010: [23120, -123 & 0xFFFF],
        0x3012: _big(-250, 2) + _big(300, 2) + _big(500_000, 2) + _big(100_000, 2),
        0x3020: [22980, 57],
        0x3022: _big(100, 2) + _big(130, 2) + _big(400_000, 2) + _big(0, 2),
        0x3030: _big(1050, 2) + [5001, 12],
        0x3034: _big(2_134_567, 2) + _big(123_456, 2) + [0, 45, 625, 0],
        0x303C: _big(1, 2) + [50012],
        0x3046: [39850, 960],
        0x304E: [40010, -834 & 0xFFFF],
        0x3056: [39790, 767],
    }
)


def seed_em540(unit: MockModbusUnit, model_code: int = EM540_PFC) -> None:
    """Seed an EM540 PFC on a three-phase connection with neutral.

    0x000B answers the model code to a one-register read, and otherwise holds
    the high word of the L3-L1 voltage, as the protocol describes.
    """
    unit.input.update(EM540_INPUT)
    unit.holding.update(EM540_HOLDING)
    read = unit.read_input_registers

    async def read_input_registers(address: int, count: int) -> list[int]:
        if address == 0x000B and count == 1:
            return [model_code]
        return await read(address, count)

    unit.read_input_registers = read_input_registers  # type: ignore[method-assign]


def seed_vm_3p75ct(unit: MockModbusUnit) -> None:
    """Seed a three-phase VM-3P75CT grid meter on firmware v1.09."""
    unit.holding.update(VM_HOLDING)
