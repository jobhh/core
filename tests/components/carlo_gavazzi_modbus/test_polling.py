"""Tests that only what enabled entities show is read."""

from freezegun.api import FrozenDateTimeFactory
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant.common import async_fire_time_changed

from homeassistant.components.carlo_gavazzi_modbus.const import SCAN_INTERVAL
from homeassistant.core import HomeAssistant

# A register in each block the default entities do not show.
NOT_SHOWN_BY_DEFAULT = {
    0x0082: "THD A L1, power quality",
    0x00BE: "W dmd, demand",
    0x0046: "kWh (+) t1, tariff energy",
    0x0300: "digital input, status",
    0x0306: "alarm, status",
    0x5012: "device state, status",
}
# The wiring error, in the status block, is shown by default.
WRONG_CONNECTION = 0x1105


async def _poll(
    hass: HomeAssistant, unit: MockModbusUnit, freezer: FrozenDateTimeFactory
) -> set[int]:
    """Run one scheduled poll, returning every register address it read."""
    unit.read_events.clear()
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    return {
        address
        for event in unit.read_events
        for address in range(event.address, event.address + event.count)
    }


@pytest.mark.usefixtures("init_integration")
async def test_default_entities_read_only_what_they_show(
    hass: HomeAssistant,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test blocks no enabled entity shows are skipped, and the rest cut down."""
    read = await _poll(hass, mock_modbus_unit, freezer)

    assert read.isdisjoint(NOT_SHOWN_BY_DEFAULT)
    assert WRONG_CONNECTION in read
    # The measurements and the energy counters stay one read each, and the
    # status block is cut down to the one register shown.
    assert [(event.address, event.count) for event in mock_modbus_unit.read_events] == [
        (0x0000, 52),
        (0x0500, 64),
        (WRONG_CONNECTION, 1),
    ]


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "init_integration")
async def test_every_entity_enabled_reads_everything(
    hass: HomeAssistant,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test every block is read when every entity is enabled."""
    read = await _poll(hass, mock_modbus_unit, freezer)

    assert {*NOT_SHOWN_BY_DEFAULT, WRONG_CONNECTION} <= read
