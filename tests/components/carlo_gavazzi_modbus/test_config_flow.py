"""Tests for the Carlo Gavazzi Modbus config flow."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

from carlo_gavazzi_energy_meter_modbus import EM500Meter
from modbus_connection import ModbusTimeoutError
from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.carlo_gavazzi_modbus.config_flow import (
    SECTION_MORE_OPTIONS,
)
from homeassistant.components.carlo_gavazzi_modbus.const import (
    CONF_BAUDRATE,
    CONF_UNIT_ID,
    DOMAIN,
    TYPE_GATEWAY,
    TYPE_SERIAL,
)
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState, ConfigFlowResult
from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.exceptions import HomeAssistantError

from .conftest import (
    BAUDRATE,
    DEVICE,
    ENTRY_DATA,
    SERIAL_NUMBER,
    SERIAL_REGISTERS,
    UNIT_ID,
    async_seed_unit,
)

# Setting up on a serial port asks for the port, then for the baud rate.
PORT_INPUT = {
    CONF_DEVICE: DEVICE,
    SECTION_MORE_OPTIONS: {CONF_UNIT_ID: UNIT_ID},
}
USER_INPUT = {CONF_BAUDRATE: str(BAUDRATE)}

GATEWAY_INPUT = {
    CONF_HOST: "Gateway.local",
    CONF_PORT: 4196,
    SECTION_MORE_OPTIONS: {CONF_UNIT_ID: UNIT_ID},
}
GATEWAY_DATA = {
    CONF_TYPE: TYPE_GATEWAY,
    CONF_HOST: "gateway.local",
    CONF_PORT: 4196,
    CONF_UNIT_ID: UNIT_ID,
}


async def _start_flow(hass: HomeAssistant, link: str = "serial") -> ConfigFlowResult:
    """Start a user flow and pick how the meter is reached.

    On a serial port, this also picks the port, landing on the baud rate.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": link}
    )
    if link != TYPE_SERIAL:
        return result
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == TYPE_SERIAL
    return await hass.config_entries.flow.async_configure(result["flow_id"], PORT_INPUT)


def _suggested_baudrate(result: ConfigFlowResult) -> str:
    """Return the baud rate a form fills in."""
    key = next(key for key in result["data_schema"].schema if key == CONF_BAUDRATE)
    return key.description["suggested_value"]


def _answering_at(connection: MockModbusConnection, rate: int) -> Any:
    """Return temporary units that only answer at one baud rate."""

    @asynccontextmanager
    async def temporary_unit(
        hass: HomeAssistant, params: Any, unit_id: int
    ) -> AsyncIterator[MockModbusUnit]:
        if params.baudrate != rate:
            raise ModbusTimeoutError
        yield connection.for_unit(unit_id)

    return temporary_unit


# A model code no Carlo Gavazzi meter this integration supports reports.
UNKNOWN_MODEL_CODE = 9999


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow(hass: HomeAssistant) -> None:
    """Test setting up a meter on a serial port."""
    result = await _start_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "serial_baudrate"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Carlo Gavazzi EM540"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == SERIAL_NUMBER


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_typed_baudrate(hass: HomeAssistant) -> None:
    """Test a baud rate the list does not offer can be typed in."""
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_BAUDRATE: "4800"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BAUDRATE] == 4800
    assert result["result"].unique_id == SERIAL_NUMBER


@pytest.mark.parametrize("baudrate", ["fast", "300"])
async def test_user_flow_invalid_baudrate(hass: HomeAssistant, baudrate: str) -> None:
    """Test a typed baud rate that is no number, or too slow, is refused."""
    result = await _start_flow(hass)
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_BAUDRATE: baudrate}
        )


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_detects_the_baudrate(
    hass: HomeAssistant, mock_modbus_connection: MockModbusConnection
) -> None:
    """Test the baud rate the meter answers at is filled in."""
    with patch(
        "homeassistant.components.carlo_gavazzi_modbus.config_flow.async_get_temporary_unit",
        _answering_at(mock_modbus_connection, 57600),
    ):
        result = await _start_flow(hass)

    assert result["step_id"] == "serial_baudrate"
    assert result["errors"] == {}
    assert _suggested_baudrate(result) == "57600"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BAUDRATE: "57600"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == SERIAL_NUMBER
    assert result["data"][CONF_BAUDRATE] == 57600


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_baudrate_not_detected(
    hass: HomeAssistant, mock_modbus_connection: MockModbusConnection
) -> None:
    """Test a port where nothing answers says so, and still takes a rate."""
    temporary_unit = _answering_at(mock_modbus_connection, 0)
    with patch(
        "homeassistant.components.carlo_gavazzi_modbus.config_flow.async_get_temporary_unit",
        side_effect=temporary_unit,
    ) as tried:
        result = await _start_flow(hass)

    assert result["step_id"] == "serial_baudrate"
    assert result["errors"] == {"base": "baudrate_not_detected"}
    assert _suggested_baudrate(result) == "9600"
    # One attempt at each rate the meters offer.
    assert [call.args[1].baudrate for call in tried.call_args_list] == [
        9600,
        19200,
        38400,
        57600,
        115200,
    ]

    # The meter answers once its own rate is picked.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == SERIAL_NUMBER


def _no_answer(unit: MockModbusUnit) -> None:
    unit.fail_requests(ModbusTimeoutError())


def _other_model(unit: MockModbusUnit) -> None:
    read = unit.read_input_registers

    async def read_input_registers(address: int, count: int) -> list[int]:
        if address == 0x000B and count == 1:
            return [UNKNOWN_MODEL_CODE]
        return await read(address, count)

    unit.read_input_registers = read_input_registers  # type: ignore[method-assign]


def _no_serial(unit: MockModbusUnit) -> None:
    unit.input.update(dict.fromkeys(SERIAL_REGISTERS, 0))


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize(
    ("break_unit", "error", "placeholders"),
    [
        pytest.param(_no_answer, "cannot_connect", {}, id="no_answer"),
        pytest.param(
            _other_model,
            "unsupported_meter",
            {"code": str(UNKNOWN_MODEL_CODE)},
            id="unsupported_meter",
        ),
        pytest.param(_no_serial, "no_serial_number", {}, id="no_serial_number"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    mock_modbus_unit: MockModbusUnit,
    break_unit: Any,
    error: str,
    placeholders: dict[str, str],
) -> None:
    """Test the form reports what went wrong, and recovers."""
    snapshot = (dict(mock_modbus_unit.input), dict(mock_modbus_unit.holding))
    read = mock_modbus_unit.read_input_registers
    break_unit(mock_modbus_unit)

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert result["description_placeholders"] == placeholders

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

    result = await _start_flow(hass)
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

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert not mock_setup_entry.called


def _input(*, baudrate: int = BAUDRATE, unit_id: int = UNIT_ID) -> dict[str, Any]:
    """Return the form input for the seeded meter's port."""
    return {
        CONF_DEVICE: DEVICE,
        CONF_BAUDRATE: str(baudrate),
        SECTION_MORE_OPTIONS: {CONF_UNIT_ID: unit_id},
    }


def _other_serial(unit: MockModbusUnit) -> None:
    """Make a seeded unit answer as another meter of the same model."""
    unit.input.update(dict.fromkeys(SERIAL_REGISTERS, 0x4258))
    unit.holding.update(unit.input)


async def test_reconfigure_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_connection: MockModbusConnection,
) -> None:
    """Test the meter can be moved to another address."""
    mock_config_entry.add_to_hass(hass)
    # The same meter, now answering on address 2.
    await async_seed_unit(hass, mock_modbus_connection.for_unit(2))

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    # The stored rate is picked in the list, which holds strings.
    baudrate = next(key for key in result["data_schema"].schema if key == CONF_BAUDRATE)
    assert baudrate.description == {"suggested_value": str(BAUDRATE)}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _input(unit_id=2)
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_UNIT_ID] == 2


async def test_reconfigure_flow_wrong_meter(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_connection: MockModbusConnection,
) -> None:
    """Test reconfiguring onto a different meter is rejected."""
    mock_config_entry.add_to_hass(hass)
    unit = mock_modbus_connection.for_unit(2)
    await async_seed_unit(hass, unit)
    _other_serial(unit)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _input(unit_id=2)
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_meter"
    assert mock_config_entry.data[CONF_UNIT_ID] == UNIT_ID


async def test_reconfigure_flow_cannot_connect(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Test a reconfigure attempt reports cannot_connect, then recovers."""
    mock_config_entry.add_to_hass(hass)
    mock_modbus_unit.fail_requests(ModbusTimeoutError())

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _input())
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_modbus_unit.fail_requests(None)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _input())
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


@pytest.mark.usefixtures("init_integration")
async def test_reconfigure_flow_new_baudrate(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test a new baud rate is probed with the entry off the bus."""
    states: list[ConfigEntryState] = []
    setup = EM500Meter.async_ensure_setup

    async def setup_watching_the_entry(meter: EM500Meter) -> None:
        states.append(mock_config_entry.state)
        await setup(meter)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    with patch.object(EM500Meter, "async_ensure_setup", setup_watching_the_entry):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _input(baudrate=9600)
        )
    await hass.async_block_till_done()

    # The reload at the end sets the meter up again; the first setup is the flow's.
    assert states[0] is ConfigEntryState.NOT_LOADED
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_BAUDRATE] == 9600
    assert mock_config_entry.state is ConfigEntryState.LOADED


@pytest.mark.usefixtures("init_integration")
async def test_reconfigure_flow_new_baudrate_cannot_connect(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Test a failed probe puts the entry back on the bus it was taken off."""
    mock_modbus_unit.fail_requests(ModbusTimeoutError())

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _input(baudrate=9600)
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert mock_config_entry.data[CONF_BAUDRATE] == BAUDRATE
    # Setting the entry back up runs into the same silent meter, so it retries
    # rather than staying unloaded with nothing scheduled to fix it.
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY

    mock_modbus_unit.fail_requests(None)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _input(baudrate=9600)
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


@pytest.mark.usefixtures("init_integration")
async def test_reconfigure_flow_new_baudrate_wrong_meter(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_connection: MockModbusConnection,
) -> None:
    """Test a rejected reconfigure puts the entry back on the bus."""
    unit = mock_modbus_connection.for_unit(2)
    await async_seed_unit(hass, unit)
    _other_serial(unit)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _input(baudrate=9600, unit_id=2)
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_meter"
    assert mock_config_entry.data[CONF_BAUDRATE] == BAUDRATE
    assert mock_config_entry.state is ConfigEntryState.LOADED


async def test_reconfigure_flow_new_baudrate_while_retrying(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Test an entry waiting to retry is taken off the bus before the probe."""
    mock_modbus_unit.fail_requests(ModbusTimeoutError())
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY

    # The meter answers again, on a bus that now runs at another rate.
    mock_modbus_unit.fail_requests(None)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _input(baudrate=9600)
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_BAUDRATE] == 9600
    assert mock_config_entry.state is ConfigEntryState.LOADED


@pytest.mark.usefixtures("mock_setup_entry")
async def test_gateway_flow(hass: HomeAssistant) -> None:
    """Test setting up a meter behind an RS485-to-TCP gateway."""
    result = await _start_flow(hass, TYPE_GATEWAY)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == TYPE_GATEWAY

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], GATEWAY_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Carlo Gavazzi EM540"
    # One connection is shared per host, so the host is stored lowercased.
    assert result["data"] == GATEWAY_DATA
    assert result["result"].unique_id == SERIAL_NUMBER


async def test_reconfigure_flow_gateway(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Test a meter behind a gateway can move to another gateway port."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Carlo Gavazzi EM540",
        unique_id=SERIAL_NUMBER,
        data=GATEWAY_DATA,
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**GATEWAY_INPUT, CONF_PORT: 502}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {**GATEWAY_DATA, CONF_PORT: 502}
