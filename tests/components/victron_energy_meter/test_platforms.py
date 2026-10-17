"""Snapshot tests of every entity, and tests of the command buttons."""

from unittest.mock import patch

from modbus_connection import ServerDeviceFailureError
from modbus_connection.mock import MockModbusUnit, WriteEvent
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry, snapshot_platform


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "mock_get_unit")
@pytest.mark.parametrize(
    ("meter_kind", "platform"),
    [
        pytest.param("em540", Platform.BINARY_SENSOR, id="em540-binary_sensor"),
        pytest.param("em540", Platform.BUTTON, id="em540-button"),
        pytest.param("em540", Platform.SENSOR, id="em540-sensor"),
        pytest.param("et340", Platform.BINARY_SENSOR, id="et340-binary_sensor"),
        pytest.param("et340", Platform.BUTTON, id="et340-button"),
        pytest.param("et340", Platform.SENSOR, id="et340-sensor"),
        pytest.param("vm_3p75ct", Platform.SENSOR, id="vm_3p75ct-sensor"),
    ],
)
async def test_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    mock_config_entry: MockConfigEntry,
    platform: Platform,
) -> None:
    """Test every entity a meter serves, with every entity enabled."""
    with patch("homeassistant.components.victron_energy_meter.PLATFORMS", [platform]):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "init_integration")
@pytest.mark.parametrize(
    ("meter_kind", "entity_id", "register"),
    [
        pytest.param(
            "em540", "button.em540_pfc_reset_partial_counters", 0x4004, id="partial"
        ),
        pytest.param("em540", "button.em540_pfc_reset_demand", 0x4005, id="demand"),
        pytest.param(
            "em540", "button.em540_pfc_reset_tariff_counters", 0x4006, id="tariff"
        ),
        pytest.param(
            "et340", "button.et340_reset_partial_counters", 0x4000, id="et340-partial"
        ),
    ],
)
async def test_reset_buttons(
    hass: HomeAssistant, mock_unit: MockModbusUnit, entity_id: str, register: int
) -> None:
    """Test each reset button writes its command register."""
    writes: list[WriteEvent] = []
    mock_unit.on_write(writes.append)

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )

    assert writes == [WriteEvent("holding", register, [1], 0x06)]


@pytest.mark.usefixtures("init_integration")
async def test_refused_command_raises(
    hass: HomeAssistant, mock_unit: MockModbusUnit
) -> None:
    """Test a command the meter refuses surfaces as an error."""
    mock_unit.fail_write(0x4004, ServerDeviceFailureError())

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: "button.em540_pfc_reset_partial_counters"},
            blocking=True,
        )
    assert err.value.translation_key == "command_failed"


@pytest.mark.parametrize("meter_kind", ["vm_3p75ct"])
@pytest.mark.usefixtures("init_integration")
async def test_victron_meter_has_no_buttons_or_binary_sensors(
    hass: HomeAssistant,
) -> None:
    """Test Victron's own meters get neither commands nor binary sensors."""
    assert hass.states.async_entity_ids(BUTTON_DOMAIN) == []
    assert hass.states.async_entity_ids("binary_sensor") == []
