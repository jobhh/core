"""Constants for the Carlo Gavazzi Modbus integration."""

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "carlo_gavazzi_modbus"
LOGGER = logging.getLogger(__package__)

CONF_BAUDRATE: Final = "baudrate"
CONF_UNIT_ID: Final = "unit_id"

TYPE_SERIAL: Final = "serial"

# The meters' factory defaults: 9600 baud 8N1, Modbus address 1.
DEFAULT_BAUDRATE: Final = 9600
DEFAULT_UNIT_ID: Final = 1

# A full poll takes about a second at the factory 9600 baud.
SCAN_INTERVAL: Final = timedelta(seconds=5)

# The meter's configuration only changes when someone sets it on the meter.
SETTINGS_SCAN_INTERVAL: Final = timedelta(minutes=5)
