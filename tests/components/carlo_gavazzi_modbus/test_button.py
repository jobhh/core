"""Tests for the Carlo Gavazzi Modbus buttons."""

from unittest.mock import patch

from modbus_connection import ServerDeviceFailureError
from modbus_connection.mock import MockModbusUnit, WriteEvent
import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

RESET_PARTIAL_COUNTERS = "button.carlo_gavazzi_em540_reset_partial_counters"


@pytest.mark.parametrize("meter_fixture", ["em540.json", "et340.json"])
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_buttons(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test every button each meter offers."""
    with patch(
        "homeassistant.components.carlo_gavazzi_modbus.PLATFORMS", [Platform.BUTTON]
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "init_integration")
@pytest.mark.parametrize(
    ("entity_id", "register"),
    [
        pytest.param(RESET_PARTIAL_COUNTERS, 0x4004, id="partial_counters"),
        pytest.param("button.carlo_gavazzi_em540_reset_demand", 0x4005, id="demand"),
        pytest.param(
            "button.carlo_gavazzi_em540_reset_tariff_counters", 0x4006, id="tariffs"
        ),
    ],
)
async def test_press(
    hass: HomeAssistant,
    mock_modbus_unit: MockModbusUnit,
    entity_id: str,
    register: int,
) -> None:
    """Test each button writes its command register."""
    writes: list[WriteEvent] = []
    mock_modbus_unit.on_write(writes.append)

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )

    assert writes == [WriteEvent("holding", register, [1], 0x06)]


@pytest.mark.usefixtures("init_integration")
async def test_refused_command_raises(
    hass: HomeAssistant, mock_modbus_unit: MockModbusUnit
) -> None:
    """Test a command the meter refuses surfaces as an error."""
    mock_modbus_unit.fail_write(0x4004, ServerDeviceFailureError())

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: RESET_PARTIAL_COUNTERS},
            blocking=True,
        )
    assert err.value.translation_key == "command_failed"
