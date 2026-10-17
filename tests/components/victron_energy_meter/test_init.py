"""Tests for setting up the Victron Energy Meter integration."""

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from modbus_connection import IllegalDataAddressError, ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest

from homeassistant.components.victron_energy_meter.const import (
    SCAN_INTERVAL,
    SETTINGS_SCAN_INTERVAL,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from . import EM540_SERIAL, VM_SERIAL

from tests.common import MockConfigEntry, async_fire_time_changed


@pytest.mark.parametrize(
    ("meter_kind", "serial", "manufacturer", "model"),
    [
        pytest.param("em540", EM540_SERIAL, "Carlo Gavazzi", "EM540 PFC", id="em540"),
        pytest.param("vm_3p75ct", VM_SERIAL, "Victron Energy", "VM-3P75CT", id="vm"),
    ],
)
async def test_setup_and_unload(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    serial: str,
    manufacturer: str,
    model: str,
) -> None:
    """Test a meter sets up as a device, and unloads."""
    assert init_integration.state is ConfigEntryState.LOADED
    device = device_registry.async_get_device_by_identifier(
        ("victron_energy_meter", serial), init_integration.entry_id
    )
    assert device is not None
    assert device.manufacturer == manufacturer
    assert device.model == model
    assert device.serial_number == serial

    await hass.config_entries.async_unload(init_integration.entry_id)
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_meter_not_answering_retries(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_get_unit: MagicMock,
    mock_unit: MockModbusUnit,
) -> None:
    """Test setup is retried while the meter does not answer."""
    mock_unit.fail_requests(ModbusTimeoutError())
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unsupported_meter_fails_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_get_unit: MagicMock,
    mock_unit: MockModbusUnit,
) -> None:
    """Test setup fails for good when the device is no supported meter."""
    read = mock_unit.read_input_registers

    async def unknown_model(address: int, count: int) -> list[int]:
        if address == 0x000B and count == 1:
            return [1234]
        return await read(address, count)

    mock_unit.read_input_registers = unknown_model  # type: ignore[method-assign]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


@pytest.mark.parametrize("meter_kind", ["vm_3p75ct"])
async def test_old_firmware_fails_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_get_unit: MagicMock,
    mock_unit: MockModbusUnit,
) -> None:
    """Test setup fails for good on firmware without Modbus measurements."""
    mock_unit.holding[0x100A] = 0x0200
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_another_meter_on_the_address_fails_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_get_unit: MagicMock,
    mock_unit: MockModbusUnit,
) -> None:
    """Test setup refuses a different meter answering on the entry's link."""
    mock_unit.input[0x5000] = (ord("Q") << 8) | ord("Q")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_link_in_use_fails_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_get_unit: MagicMock,
) -> None:
    """Test setup fails when the port is in use with other settings."""
    mock_get_unit.side_effect = HomeAssistantError("in use")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_meter_going_offline(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test measurements go unavailable while energy totals keep their value."""
    mock_unit.fail_requests(ModbusTimeoutError())
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.em540_pfc_active_power").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.em540_pfc_energy_imported").state == "12345.678"

    mock_unit.fail_requests(None)
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.em540_pfc_active_power").state == "1050.2"


async def test_refused_block_marks_only_its_entities_unavailable(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a refused sub-system leaves the others available."""
    mock_unit.fail_read(0x0300, IllegalDataAddressError(), register_type="input")
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (
        hass.states.get("binary_sensor.em540_pfc_wiring_error").state
        == STATE_UNAVAILABLE
    )
    assert hass.states.get("sensor.em540_pfc_active_power").state == "1050.2"


@pytest.mark.parametrize("meter_kind", ["vm_3p75ct"])
async def test_phase_configuration_change_reloads(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a Victron meter reconfigured to one phase sets up again."""
    assert hass.states.get("sensor.vm_3p75ct_voltage_l3") is not None

    mock_unit.holding[0x2000] = 0  # single phase on L1
    mock_unit.read_events.clear()
    freezer.tick(SETTINGS_SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert sorted({hex(e.address) for e in mock_unit.read_events}) == []  # debug
    assert init_integration.state is ConfigEntryState.LOADED
    assert init_integration.runtime_data.meter.phases == (1,)
    assert hass.states.get("sensor.vm_3p75ct_voltage_l1").state == "230.12"


async def test_every_sub_system_refused_marks_the_meter_unavailable(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a meter that answers but refuses every block counts as failed."""
    for address in (0x0000, 0x0076, 0x009A, 0x0500, 0x0046, 0x0300, 0x1105, 0x5012):
        mock_unit.fail_read(address, IllegalDataAddressError(), register_type="input")
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.em540_pfc_active_power").state == STATE_UNAVAILABLE
    assert (
        hass.states.get("binary_sensor.em540_pfc_wiring_error").state
        == STATE_UNAVAILABLE
    )
