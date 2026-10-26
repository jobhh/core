"""Tests for following the Carlo Gavazzi meter's own settings."""

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from homeassistant.components.carlo_gavazzi_modbus.const import SETTINGS_SCAN_INTERVAL
from homeassistant.core import HomeAssistant

# On the EM500 series: the demand interval, and the measurement mode.
DEMAND_INTERVAL = 0x1010
MEASUREMENT_MODE = 0x1103


def _set(unit: MockModbusUnit, address: int, value: int) -> None:
    """Change a setting, the way the meter's own keys would."""
    unit.holding[address] = value
    unit.input[address] = value


async def _poll_settings(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Run one scheduled settings poll."""
    freezer.tick(SETTINGS_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_setting_change_is_shown(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a changed setting shows up on the next settings poll."""
    entity_id = "sensor.carlo_gavazzi_em540_demand_interval"
    assert hass.states.get(entity_id).state == "15"

    _set(mock_modbus_unit, DEMAND_INTERVAL, 0)
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        await _poll_settings(hass, freezer)

    assert hass.states.get(entity_id).state == "1"
    # The entities do not depend on the demand interval.
    reload.assert_not_called()


async def test_measuring_change_reloads(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a change that alters which entities exist reloads the entry.

    In measurement mode A everything counts as imported, so the exported
    energy sensors go.
    """
    assert hass.states.get("sensor.carlo_gavazzi_em540_energy_exported")

    _set(mock_modbus_unit, MEASUREMENT_MODE, 0)
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        await _poll_settings(hass, freezer)

    reload.assert_called_once_with(init_integration.entry_id)
