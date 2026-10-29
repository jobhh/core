"""Tests for setting up the Carlo Gavazzi Modbus integration."""

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from modbus_connection import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.carlo_gavazzi_modbus.const import DOMAIN, SCAN_INTERVAL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from .conftest import ENTRY_DATA, SERIAL_REGISTERS, async_seed_unit

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


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Run one scheduled poll."""
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_other_meter_after_dead_link_is_refused(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a meter swapped in at the same address does not take over the entities.

    Swapping a meter takes the address off the bus for a while, after which
    the serial number is read again, and keeps being read until it matches.
    """
    power = "sensor.carlo_gavazzi_em540_power"
    serial = {address: mock_modbus_unit.input[address] for address in SERIAL_REGISTERS}

    mock_modbus_unit.fail_requests(ModbusTimeoutError())
    await _poll(hass, freezer)
    assert hass.states.get(power).state == STATE_UNAVAILABLE

    mock_modbus_unit.fail_requests(None)
    for registers in (mock_modbus_unit.input, mock_modbus_unit.holding):
        registers[SERIAL_REGISTERS.start] = 0x5959
    await _poll(hass, freezer)
    assert hass.states.get(power).state == STATE_UNAVAILABLE
    await _poll(hass, freezer)
    assert hass.states.get(power).state == STATE_UNAVAILABLE
    # Raised where it is seen, rather than only in the log.
    issue_id = f"wrong_meter_{init_integration.entry_id}"
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == "wrong_meter"
    assert issue.translation_placeholders == {"title": init_integration.title}

    for registers in (mock_modbus_unit.input, mock_modbus_unit.holding):
        registers.update(serial)
    await _poll(hass, freezer)
    assert hass.states.get(power).state != STATE_UNAVAILABLE
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

    # Once it matched, the serial number is not read on every poll.
    mock_modbus_unit.read_events.clear()
    await _poll(hass, freezer)
    assert all(
        event.address not in SERIAL_REGISTERS for event in mock_modbus_unit.read_events
    )


@pytest.mark.usefixtures("init_integration")
async def test_unanswered_check_of_the_meter_stays_due(
    hass: HomeAssistant,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a serial number read that goes unanswered is tried again."""
    power = "sensor.carlo_gavazzi_em540_power"
    mock_modbus_unit.fail_requests(ModbusTimeoutError())
    await _poll(hass, freezer)

    mock_modbus_unit.fail_requests(None)
    mock_modbus_unit.fail_read(
        SERIAL_REGISTERS.start, ModbusTimeoutError(), register_type="input"
    )
    await _poll(hass, freezer)
    assert hass.states.get(power).state == STATE_UNAVAILABLE

    mock_modbus_unit.fail_read(SERIAL_REGISTERS.start, None, register_type="input")
    mock_modbus_unit.read_events.clear()
    await _poll(hass, freezer)
    assert hass.states.get(power).state != STATE_UNAVAILABLE
    assert any(
        event.address in SERIAL_REGISTERS for event in mock_modbus_unit.read_events
    )


async def test_unloading_clears_the_other_meter_issue(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test unloading, such as to reconfigure, clears the issue it raised."""
    mock_modbus_unit.fail_requests(ModbusTimeoutError())
    await _poll(hass, freezer)
    mock_modbus_unit.fail_requests(None)
    for registers in (mock_modbus_unit.input, mock_modbus_unit.holding):
        registers[SERIAL_REGISTERS.start] = 0x5959
    await _poll(hass, freezer)
    issue_id = f"wrong_meter_{init_integration.entry_id}"
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None

    await hass.config_entries.async_unload(init_integration.entry_id)

    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
