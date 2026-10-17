"""Tests for the Victron Energy Meter config flow."""

from ipaddress import ip_address
from unittest.mock import AsyncMock, MagicMock

from modbus_connection import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest

from homeassistant.components.victron_energy_meter.const import DOMAIN, LinkType
from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from . import EM540_SERIAL, GATEWAY_INPUT, NETWORK_INPUT, SERIAL_INPUT, VM_SERIAL

from tests.common import MockConfigEntry

pytestmark = pytest.mark.usefixtures("mock_setup_entry", "mock_temporary_unit")

ZEROCONF_DISCOVERY = ZeroconfServiceInfo(
    ip_address=ip_address("192.168.1.70"),
    ip_addresses=[ip_address("192.168.1.70")],
    hostname="vm-3p75ct.local.",
    name="VM-3P75CT HQ2401ABCDE._victron-energy-meter._udp.local.",
    port=502,
    properties={},
    type="_victron-energy-meter._udp.local.",
)


@pytest.mark.parametrize(
    ("meter_kind", "link", "user_input", "serial", "title"),
    [
        pytest.param(
            "em540",
            LinkType.SERIAL,
            SERIAL_INPUT,
            EM540_SERIAL,
            "EM540 PFC",
            id="serial",
        ),
        pytest.param(
            "em540",
            LinkType.GATEWAY,
            GATEWAY_INPUT,
            EM540_SERIAL,
            "EM540 PFC",
            id="gateway",
        ),
        pytest.param(
            "vm_3p75ct",
            LinkType.NETWORK,
            NETWORK_INPUT,
            VM_SERIAL,
            "VM-3P75CT",
            id="network",
        ),
    ],
)
async def test_user_flow(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    link: LinkType,
    user_input: dict[str, object],
    serial: str,
    title: str,
) -> None:
    """Test adding a meter over each kind of link."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": link}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == link

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == title
    assert result["data"] == {CONF_TYPE: link, **user_input}
    assert result["result"].unique_id == serial
    assert len(mock_setup_entry.mock_calls) == 1


async def _start_serial_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": LinkType.SERIAL}
    )
    return result["flow_id"]


async def test_cannot_connect_then_recover(
    hass: HomeAssistant, mock_unit: MockModbusUnit
) -> None:
    """Test a meter that does not answer, then does."""
    flow_id = await _start_serial_flow(hass)
    mock_unit.fail_requests(ModbusTimeoutError())

    result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_unit.fail_requests(None)
    result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_unsupported_meter(
    hass: HomeAssistant, mock_unit: MockModbusUnit
) -> None:
    """Test a device that answers with an unknown model code."""
    read = mock_unit.read_input_registers

    async def unknown_model(address: int, count: int) -> list[int]:
        if address == 0x000B and count == 1:
            return [1234]
        return await read(address, count)

    mock_unit.read_input_registers = unknown_model  # type: ignore[method-assign]
    flow_id = await _start_serial_flow(hass)

    result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)
    assert result["errors"] == {"base": "unsupported_meter"}


@pytest.mark.parametrize("meter_kind", ["vm_3p75ct"])
async def test_unsupported_firmware(
    hass: HomeAssistant, mock_unit: MockModbusUnit
) -> None:
    """Test a Victron meter on firmware without Modbus measurements."""
    mock_unit.holding[0x100A] = 0x0200  # v1.02 beta 0
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": LinkType.NETWORK}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], NETWORK_INPUT
    )
    assert result["errors"] == {"base": "unsupported_firmware"}


async def test_no_serial_number(hass: HomeAssistant, mock_unit: MockModbusUnit) -> None:
    """Test a meter that reports an empty serial number."""
    for address in range(0x5000, 0x5007):
        mock_unit.input[address] = 0
    flow_id = await _start_serial_flow(hass)

    result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)
    assert result["errors"] == {"base": "no_serial_number"}


async def test_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test adding a meter that is already set up."""
    mock_config_entry.add_to_hass(hass)
    flow_id = await _start_serial_flow(hass)

    result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize("meter_kind", ["vm_3p75ct"])
async def test_zeroconf(hass: HomeAssistant, mock_setup_entry: AsyncMock) -> None:
    """Test a Victron meter discovered over mDNS."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF_DISCOVERY
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"] == {
        "name": "VM-3P75CT",
        "host": "192.168.1.70",
    }

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_TYPE: LinkType.NETWORK, CONF_HOST: "192.168.1.70"}
    assert result["result"].unique_id == VM_SERIAL


@pytest.mark.parametrize("meter_kind", ["vm_3p75ct"])
async def test_zeroconf_updates_the_host(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test a known meter that moved to another address."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_HOST: "192.168.1.5"},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF_DISCOVERY
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.70"


@pytest.mark.parametrize("meter_kind", ["vm_3p75ct"])
async def test_zeroconf_cannot_connect(
    hass: HomeAssistant, mock_unit: MockModbusUnit
) -> None:
    """Test a discovered meter that does not answer."""
    mock_unit.fail_requests(ModbusTimeoutError())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF_DISCOVERY
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_reconfigure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test moving a meter to another serial port."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**SERIAL_INPUT, "device": "/dev/ttyUSB1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["device"] == "/dev/ttyUSB1"


async def test_reconfigure_errors_then_wrong_meter(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_unit: MockModbusUnit,
) -> None:
    """Test a reconfigure that cannot connect, then finds another meter."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)

    mock_unit.fail_requests(ModbusTimeoutError())
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], SERIAL_INPUT
    )
    assert result["errors"] == {"base": "cannot_connect"}

    mock_unit.fail_requests(None)
    mock_unit.input[0x5000] = (ord("Q") << 8) | ord("Q")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], SERIAL_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_meter"


async def test_link_in_use(hass: HomeAssistant, mock_temporary_unit: MagicMock) -> None:
    """Test a port already in use with other link settings."""
    mock_temporary_unit.side_effect = HomeAssistantError("in use")
    flow_id = await _start_serial_flow(hass)

    result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)
    assert result["errors"] == {"base": "cannot_connect"}
