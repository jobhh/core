"""Tests for the Carlo Gavazzi Modbus sensors."""

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from modbus_connection import IllegalDataAddressError, ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.carlo_gavazzi_modbus.const import SCAN_INTERVAL
from homeassistant.const import STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

POWER = "sensor.carlo_gavazzi_em540_power"
ENERGY_IMPORTED = "sensor.carlo_gavazzi_em540_energy_imported"

# The first register of the 64-bit energy counters.
ENERGY_REGISTER = 0x0500
# The first register of the measurements.
MEASUREMENTS_REGISTER = 0x0000


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_sensors(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test every sensor the captured EM540 serves."""
    with patch(
        "homeassistant.components.carlo_gavazzi_modbus.PLATFORMS", [Platform.SENSOR]
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("init_integration")
async def test_silent_subsystem_makes_its_sensors_unavailable(
    hass: HomeAssistant,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a sub-system that stops answering takes only its own sensors down."""
    mock_modbus_unit.fail_read(
        ENERGY_REGISTER, IllegalDataAddressError(), register_type="input"
    )
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(ENERGY_IMPORTED).state == STATE_UNAVAILABLE
    assert hass.states.get(POWER).state != STATE_UNAVAILABLE

    mock_modbus_unit.fail_read(ENERGY_REGISTER, None, register_type="input")
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(ENERGY_IMPORTED).state != STATE_UNAVAILABLE


@pytest.mark.usefixtures("init_integration")
async def test_one_lost_answer_is_retried(
    hass: HomeAssistant,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a sub-system that misses one answer is asked again in the same poll."""
    read = mock_modbus_unit.read_input_registers
    failed: list[int] = []

    async def read_input_registers(address: int, count: int) -> list[int]:
        if address == ENERGY_REGISTER and not failed:
            failed.append(address)
            raise IllegalDataAddressError
        return await read(address, count)

    mock_modbus_unit.read_input_registers = read_input_registers  # type: ignore[method-assign]
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert failed
    assert hass.states.get(ENERGY_IMPORTED).state != STATE_UNAVAILABLE


@pytest.mark.usefixtures("init_integration")
async def test_dead_link_makes_every_sensor_unavailable(
    hass: HomeAssistant,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a meter that stops answering takes every sensor down, and back."""
    mock_modbus_unit.fail_requests(ModbusTimeoutError())
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(POWER).state == STATE_UNAVAILABLE
    assert hass.states.get(ENERGY_IMPORTED).state == STATE_UNAVAILABLE

    mock_modbus_unit.fail_requests(None)
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(POWER).state != STATE_UNAVAILABLE


@pytest.mark.usefixtures("init_integration")
async def test_retry_on_a_dead_link_keeps_the_poll(
    hass: HomeAssistant,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a link that dies between a poll and its retry keeps what was read."""
    read = mock_modbus_unit.read_input_registers
    failed: list[int] = []

    async def read_input_registers(address: int, count: int) -> list[int]:
        if address == ENERGY_REGISTER and not failed:
            # The link goes down while the energy counters are read.
            failed.append(address)
            mock_modbus_unit.fail_requests(ModbusTimeoutError())
            raise IllegalDataAddressError
        return await read(address, count)

    mock_modbus_unit.read_input_registers = read_input_registers  # type: ignore[method-assign]
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(POWER).state != STATE_UNAVAILABLE
    assert hass.states.get(ENERGY_IMPORTED).state == STATE_UNAVAILABLE


@pytest.mark.usefixtures("init_integration")
async def test_silence_is_logged_once(
    hass: HomeAssistant,
    mock_modbus_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test a silent sub-system is logged when it falls silent and when it returns."""
    mock_modbus_unit.fail_read(
        ENERGY_REGISTER, IllegalDataAddressError(), register_type="input"
    )
    for _ in range(2):
        freezer.tick(SCAN_INTERVAL)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    assert caplog.text.count("energy did not answer") == 1

    mock_modbus_unit.fail_read(ENERGY_REGISTER, None, register_type="input")
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert "energy is answering again" in caplog.text
