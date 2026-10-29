"""Constants for the Carlo Gavazzi Modbus integration."""

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "carlo_gavazzi_modbus"
LOGGER = logging.getLogger(__package__)

CONF_BAUDRATE: Final = "baudrate"
CONF_UNIT_ID: Final = "unit_id"

TYPE_SERIAL: Final = "serial"
TYPE_GATEWAY: Final = "gateway"

# The meters' factory defaults: 9600 baud 8N1, Modbus address 1.
DEFAULT_BAUDRATE: Final = 9600

# The rates both series offer on their RS485 port.
BAUDRATES: Final = (9600, 19200, 38400, 57600, 115200)

# How long to wait for the meter at each rate while looking for its baud rate.
# The model code is one register, which answers in milliseconds even at
# 9600 baud, so every rate the meter is not at costs this long.
DETECT_TIMEOUT: Final = 1.0
DEFAULT_UNIT_ID: Final = 1

# The usual Modbus TCP port, which gateways also use in transparent mode.
DEFAULT_PORT: Final = 502

# A full poll takes about a second at the factory 9600 baud.
SCAN_INTERVAL: Final = timedelta(seconds=5)

# The settings only change on the meter's own keys.
SETTINGS_SCAN_INTERVAL: Final = timedelta(minutes=10)
