"""Tests for the Carlo Gavazzi Modbus binary sensors."""

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.carlo_gavazzi_modbus.const import SCAN_INTERVAL
from homeassistant.const import STATE_OFF, STATE_ON, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

WIRING_ERROR = "binary_sensor.carlo_gavazzi_em540_wiring_error"

# Where the meter reports a wiring error.
WRONG_CONNECTION_REGISTER = 0x1105


@pytest.mark.parametrize("meter_fixture", ["em540.json", "et340.json"])
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_binary_sensors(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test every binary sensor each meter serves."""
    with patch(
        "homeassistant.components.carlo_gavazzi_modbus.PLATFORMS",
        [Platform.BINARY_SENSOR],
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("init_integration")
async def test_wiring_error_follows_the_meter(
    hass: HomeAssistant,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the wiring error turns off once the meter stops reporting it."""
    # The capture was taken with one phase exporting, which the meter flags.
    assert hass.states.get(WIRING_ERROR).state == STATE_ON

    mock_modbus_unit.input[WRONG_CONNECTION_REGISTER] = 0
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(WIRING_ERROR).state == STATE_OFF
