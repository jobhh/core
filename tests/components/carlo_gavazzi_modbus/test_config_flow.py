"""Tests for the Carlo Gavazzi Modbus config flow."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

from modbus_connection import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.carlo_gavazzi_modbus.config_flow import (
    SECTION_MORE_OPTIONS,
)
from homeassistant.components.carlo_gavazzi_modbus.const import (
    CONF_BAUDRATE,
    CONF_UNIT_ID,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError

from .conftest import (
    BAUDRATE,
    DEVICE,
    ENTRY_DATA,
    SERIAL_NUMBER,
    SERIAL_REGISTERS,
    UNIT_ID,
)

USER_INPUT = {
    CONF_DEVICE: DEVICE,
    CONF_BAUDRATE: BAUDRATE,
    SECTION_MORE_OPTIONS: {CONF_UNIT_ID: UNIT_ID},
}

# An EM340, which speaks another register map.
EM340_MODEL_CODE = 341


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow(hass: HomeAssistant) -> None:
    """Test setting up a meter on a serial port."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Carlo Gavazzi EM540"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == SERIAL_NUMBER


def _no_answer(unit: MockModbusUnit) -> None:
    unit.fail_requests(ModbusTimeoutError())


def _other_model(unit: MockModbusUnit) -> None:
    read = unit.read_input_registers

    async def read_input_registers(address: int, count: int) -> list[int]:
        if address == 0x000B and count == 1:
            return [EM340_MODEL_CODE]
        return await read(address, count)

    unit.read_input_registers = read_input_registers  # type: ignore[method-assign]


def _no_serial(unit: MockModbusUnit) -> None:
    unit.input.update(dict.fromkeys(SERIAL_REGISTERS, 0))


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize(
    ("break_unit", "error"),
    [
        pytest.param(_no_answer, "cannot_connect", id="no_answer"),
        pytest.param(_other_model, "unsupported_meter", id="unsupported_meter"),
        pytest.param(_no_serial, "no_serial_number", id="no_serial_number"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    mock_modbus_unit: MockModbusUnit,
    break_unit: Any,
    error: str,
) -> None:
    """Test the form reports what went wrong, and recovers."""
    snapshot = (dict(mock_modbus_unit.input), dict(mock_modbus_unit.holding))
    read = mock_modbus_unit.read_input_registers
    break_unit(mock_modbus_unit)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_modbus_unit.fail_requests(None)
    mock_modbus_unit.input.update(snapshot[0])
    mock_modbus_unit.holding.update(snapshot[1])
    mock_modbus_unit.read_input_registers = read  # type: ignore[method-assign]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_port_in_use(hass: HomeAssistant) -> None:
    """Test a port in use at other line settings reports it, and recovers."""

    @asynccontextmanager
    async def in_use(
        hass: HomeAssistant, params: Any, unit_id: int
    ) -> AsyncIterator[MockModbusUnit]:
        raise HomeAssistantError("in use")
        yield  # pragma: no cover

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(
        "homeassistant.components.carlo_gavazzi_modbus.config_flow.async_get_temporary_unit",
        in_use,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test a meter that is already set up is not added twice."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert not mock_setup_entry.called
