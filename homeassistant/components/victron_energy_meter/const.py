"""Constants for the Victron Energy Meter integration."""

from datetime import timedelta
from enum import StrEnum

DOMAIN = "victron_energy_meter"

CONF_BAUDRATE = "baudrate"
CONF_UNIT_ID = "unit_id"

DEFAULT_BAUDRATE = 9600
DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1

SCAN_INTERVAL = timedelta(seconds=5)
SETTINGS_SCAN_INTERVAL = timedelta(minutes=5)


class LinkType(StrEnum):
    """How a meter is reached, which also settles which kind of meter it is."""

    NETWORK = "network"
    """A Victron VM-3P75CT or VM-3P5A, over Modbus UDP."""

    SERIAL = "serial"
    """A Carlo Gavazzi meter on an RS485 port, local or an ESPHome serial proxy."""

    GATEWAY = "gateway"
    """A Carlo Gavazzi meter behind an RS485-to-TCP gateway, in RTU framing."""
