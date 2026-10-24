"""Tests for the Carlo Gavazzi Modbus helpers."""

import pytest

from homeassistant.components.carlo_gavazzi_modbus.const import (
    CONF_UNIT_ID,
    TYPE_GATEWAY,
)
from homeassistant.components.carlo_gavazzi_modbus.helpers import create_modbus_params
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TYPE


@pytest.mark.parametrize(
    ("host", "device"),
    [
        pytest.param("192.168.1.60", "socket://192.168.1.60:502", id="ipv4"),
        pytest.param("gateway.local", "socket://gateway.local:502", id="hostname"),
        pytest.param("fd00::60", "socket://[fd00::60]:502", id="ipv6"),
    ],
)
def test_gateway_params(host: str, device: str) -> None:
    """Test a gateway is a serial link over a socket, in RTU framing."""
    params = create_modbus_params(
        {CONF_TYPE: TYPE_GATEWAY, CONF_HOST: host, CONF_PORT: 502, CONF_UNIT_ID: 1}
    )

    assert params.device == device
    assert params.framer == "rtu"
