"""Fixtures for the Carlo Gavazzi Modbus integration tests."""

from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from modbus_connection import ModbusUnit
from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_load_json_object_fixture

from homeassistant.components.carlo_gavazzi_modbus.const import (
    CONF_BAUDRATE,
    CONF_UNIT_ID,
    DOMAIN,
    TYPE_SERIAL,
)
from homeassistant.const import CONF_DEVICE, CONF_TYPE
from homeassistant.core import HomeAssistant

# What the EM540 capture holds in place of the meter's serial number.
SERIAL_NUMBER = "XX0000000000X"

# The meters the tests can run against: an EM540 captured from a real meter,
# and an ET340 of the EM300 series, from hand-picked registers.
METERS = {
    "em540.json": (SERIAL_NUMBER, "Carlo Gavazzi EM540"),
    "et340.json": ("KX12345", "Carlo Gavazzi ET340"),
}
SERIAL_REGISTERS = range(0x5000, 0x5007)

DEVICE = "/dev/ttyUSB0"
BAUDRATE = 57600
UNIT_ID = 1

ENTRY_DATA = {
    CONF_TYPE: TYPE_SERIAL,
    CONF_DEVICE: DEVICE,
    CONF_BAUDRATE: BAUDRATE,
    CONF_UNIT_ID: UNIT_ID,
}

# The register that answers the model code to a read of it alone.
MODEL_CODE_REGISTER = 0x000B


async def async_seed_unit(
    hass: HomeAssistant,
    unit: MockModbusUnit,
    *,
    meter: str = "em540.json",
    model_code: int | None = None,
) -> None:
    """Seed a mock unit with a meter's registers, by default an EM540.

    The capture merges every read by address, so 0x000B holds the L3-L1
    voltage's high word; the meter answers its model code there only to a read
    of that register alone. Pass ``model_code`` to answer as another model.
    """
    fixture = await async_load_json_object_fixture(hass, meter, DOMAIN)
    for space, registers in fixture["raw"].items():
        unit.load_raw({space: {int(a, 16): v for a, v in registers.items()}})
    # Functions 03h and 04h read the same data on this meter.
    unit.holding.update({**unit.input, **unit.holding})
    unit.input.update(unit.holding)

    code = fixture["model_code"] if model_code is None else model_code
    read = unit.read_input_registers

    async def read_input_registers(address: int, count: int) -> list[int]:
        if address == MODEL_CODE_REGISTER and count == 1:
            return [code]
        return await read(address, count)

    unit.read_input_registers = read_input_registers  # type: ignore[method-assign]


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.carlo_gavazzi_modbus.async_setup_entry",
        return_value=None,
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def meter_fixture() -> str:
    """Return which of ``METERS`` answers on the mock link."""
    return "em540.json"


@pytest.fixture
async def mock_modbus_unit(
    hass: HomeAssistant,
    mock_modbus_connection: MockModbusConnection,
    meter_fixture: str,
) -> MockModbusUnit:
    """A seeded meter on unit ``UNIT_ID``.

    Overrides the library plugin's ``mock_modbus_unit`` to preload the
    meter's registers.
    """
    unit = mock_modbus_connection.for_unit(UNIT_ID)
    await async_seed_unit(hass, unit, meter=meter_fixture)
    return unit


@pytest.fixture(autouse=True)
def mock_shared_connection(
    mock_modbus_connection: MockModbusConnection, mock_modbus_unit: MockModbusUnit
) -> Generator[None]:
    """Hand out units on the seeded mock instead of opening a real connection."""

    @asynccontextmanager
    async def async_temporary_unit(
        hass: HomeAssistant, params: Any, unit_id: int
    ) -> AsyncIterator[ModbusUnit]:
        yield mock_modbus_connection.for_unit(unit_id)

    with (
        patch(
            "homeassistant.components.carlo_gavazzi_modbus.async_get_unit",
            side_effect=lambda hass, entry, params, unit_id: (
                mock_modbus_connection.for_unit(unit_id)
            ),
        ),
        patch(
            "homeassistant.components.carlo_gavazzi_modbus.config_flow.async_get_temporary_unit",
            async_temporary_unit,
        ),
    ):
        yield


@pytest.fixture
def mock_config_entry(meter_fixture: str) -> MockConfigEntry:
    """A Carlo Gavazzi Modbus config entry for the seeded meter."""
    serial_number, title = METERS[meter_fixture]
    return MockConfigEntry(
        domain=DOMAIN,
        title=title,
        unique_id=serial_number,
        data=ENTRY_DATA,
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> MockConfigEntry:
    """Set up the integration with the seeded meter.

    Time is frozen first: freezing it later moves the clock, which would set
    off the slow settings poll along with the next readings poll.
    """
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
