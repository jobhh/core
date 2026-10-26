"""Tests for the Carlo Gavazzi Modbus diagnostics."""

from modbus_connection import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from homeassistant.core import HomeAssistant


@pytest.mark.parametrize("meter_fixture", ["em540.json", "et340.json"])
async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the diagnostics hold the decoded values and the raw registers."""
    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, init_integration
    )

    # How long the poll took depends on the machine running the test.
    assert isinstance(diagnostics["poll"]["duration"], float)
    assert diagnostics == snapshot(exclude=props("duration"))


async def test_diagnostics_meter_not_answering(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Test the diagnostics say why the raw registers are missing."""
    mock_modbus_unit.fail_requests(ModbusTimeoutError())

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, init_integration
    )

    assert diagnostics["raw"] is None
    assert diagnostics["raw_error"] == "ModbusTimeoutError"
