"""Fixtures for the Victron Energy Meter integration tests."""

from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest

from homeassistant.components.victron_energy_meter.const import DOMAIN
from homeassistant.core import HomeAssistant

from . import (
    EM540_SERIAL,
    ET340_SERIAL,
    NETWORK_ENTRY_DATA,
    SERIAL_ENTRY_DATA,
    VM_SERIAL,
    seed_em540,
    seed_et340,
    seed_vm_3p75ct,
)

from tests.common import MockConfigEntry


@pytest.fixture
def meter_kind() -> str:
    """Which meter the mock answers as: ``em540``, ``et340`` or ``vm_3p75ct``."""
    return "em540"


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.victron_energy_meter.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def mock_connection(meter_kind: str) -> MockModbusConnection:
    """A mock link with unit 1 answering as the chosen meter."""
    connection = MockModbusConnection()
    seed = {"em540": seed_em540, "et340": seed_et340, "vm_3p75ct": seed_vm_3p75ct}
    seed[meter_kind](connection.for_unit(1))
    return connection


@pytest.fixture
def mock_unit(mock_connection: MockModbusConnection) -> MockModbusUnit:
    """The meter's unit on the mock link."""
    return mock_connection.for_unit(1)


@pytest.fixture
def mock_temporary_unit(mock_connection: MockModbusConnection) -> Generator[MagicMock]:
    """Hand out units on the mock link while a config flow probes."""

    @asynccontextmanager
    async def _get_temporary_unit(
        hass: HomeAssistant, params: Any, unit_id: int
    ) -> AsyncIterator[MockModbusUnit]:
        yield mock_connection.for_unit(unit_id)

    with patch(
        "homeassistant.components.victron_energy_meter.config_flow.async_get_temporary_unit",
        side_effect=_get_temporary_unit,
    ) as mock:
        yield mock


@pytest.fixture
def mock_get_unit(mock_connection: MockModbusConnection) -> Generator[MagicMock]:
    """Hand out units on the mock link when an entry sets up."""
    with patch(
        "homeassistant.components.victron_energy_meter.async_get_unit",
        side_effect=lambda hass, entry, params, unit_id: mock_connection.for_unit(
            unit_id
        ),
    ) as mock:
        yield mock


@pytest.fixture
def mock_config_entry(meter_kind: str) -> MockConfigEntry:
    """A config entry for the chosen meter."""
    if meter_kind == "vm_3p75ct":
        return MockConfigEntry(
            domain=DOMAIN,
            unique_id=VM_SERIAL,
            data=NETWORK_ENTRY_DATA,
            title="VM-3P75CT",
        )
    if meter_kind == "et340":
        return MockConfigEntry(
            domain=DOMAIN,
            unique_id=ET340_SERIAL,
            data=SERIAL_ENTRY_DATA,
            title="ET340",
        )
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=EM540_SERIAL,
        data=SERIAL_ENTRY_DATA,
        title="EM540 PFC",
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_get_unit: MagicMock,
) -> MockConfigEntry:
    """Set up the integration with the chosen meter."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
