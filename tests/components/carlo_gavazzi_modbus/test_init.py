"""Tests for setting up the Carlo Gavazzi Modbus integration."""

import logging
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from modbus_connection import ModbusConnectionError, ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.carlo_gavazzi_modbus.const import DOMAIN, SCAN_INTERVAL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .conftest import ENTRY_DATA, SERIAL_NUMBER, async_seed_unit

# An EM340, which speaks another register map.
EM340_MODEL_CODE = 341

# The library names the port in its errors, and an ESPHome serial proxy's port
# carries the device's encryption key.
PORT_KEY = "c2VjcmV0LWtleQ=="
LEAKING_ERROR = f"could not open serial port esphome://proxy/?noise_psk={PORT_KEY}"


async def test_setup_and_unload(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the meter sets up as a device, and unloads."""
    assert init_integration.state is ConfigEntryState.LOADED
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, SERIAL_NUMBER), init_integration.entry_id
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


async def test_port_key_stays_out_of_setup_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test an ESPHome encryption key in the port is neither shown nor logged.

    Debug logging still shows the error's cause, which is up to the library.
    """
    caplog.set_level(logging.INFO)
    mock_modbus_unit.fail_requests(ModbusConnectionError(LEAKING_ERROR))
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert PORT_KEY not in str(mock_config_entry.reason)
    assert PORT_KEY not in caplog.text


async def test_port_key_stays_out_of_poll_errors(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test an ESPHome encryption key in the port is not logged while polling."""
    caplog.set_level(logging.INFO)
    mock_modbus_unit.fail_requests(ModbusConnectionError(LEAKING_ERROR))
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert "Could not communicate with the meter" in caplog.text
    assert PORT_KEY not in caplog.text


async def test_unsupported_meter_fails_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Test setup fails for good when the device is no EM530 or EM540."""
    await async_seed_unit(hass, mock_modbus_unit, model_code=EM340_MODEL_CODE)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert mock_config_entry.error_reason_translation_key == "unsupported_meter"


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
