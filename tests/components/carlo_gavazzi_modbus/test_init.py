"""Tests for setting up the Carlo Gavazzi Modbus integration."""

from unittest.mock import patch

from modbus_connection import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.carlo_gavazzi_modbus.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .conftest import ENTRY_DATA, async_seed_unit

# A model code no Carlo Gavazzi meter this integration supports reports.
UNKNOWN_MODEL_CODE = 9999


@pytest.mark.parametrize("meter_fixture", ["em540.json", "et340.json"])
async def test_setup_and_unload(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the meter sets up as a device, and unloads."""
    assert init_integration.state is ConfigEntryState.LOADED
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, init_integration.unique_id), init_integration.entry_id
    )
    assert device == snapshot

    await hass.config_entries.async_unload(init_integration.entry_id)
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_meter_not_answering_retries(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Test setup is retried while the meter does not answer."""
    mock_modbus_unit.fail_requests(ModbusTimeoutError())
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unsupported_meter_fails_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Test setup fails for good when the device is no supported meter."""
    await async_seed_unit(hass, mock_modbus_unit, model_code=UNKNOWN_MODEL_CODE)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert mock_config_entry.error_reason_translation_key == "unsupported_meter"
    assert mock_config_entry.error_reason_translation_placeholders == {
        "code": str(UNKNOWN_MODEL_CODE)
    }


async def test_wrong_meter_fails_setup(hass: HomeAssistant) -> None:
    """Test setup fails for good when another meter answers at the address."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Carlo Gavazzi EM540",
        unique_id="BX99999999999",
        data=ENTRY_DATA,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.error_reason_translation_key == "wrong_meter"


async def test_port_in_use_fails_setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test setup fails for good when the port is in use at other settings."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.carlo_gavazzi_modbus.async_get_unit",
        side_effect=HomeAssistantError("in use"),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert mock_config_entry.error_reason_translation_key == "link_settings_in_use"


async def test_first_poll_failing_retries(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test setup is retried when the meter stops answering after setup."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "carlo_gavazzi_energy_meter_modbus.EM500Meter.async_poll",
        side_effect=ModbusTimeoutError(),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
