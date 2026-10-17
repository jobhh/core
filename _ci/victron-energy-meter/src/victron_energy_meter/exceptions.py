"""Errors raised by this library on top of modbus-connection's."""

from __future__ import annotations


class VictronEnergyMeterError(Exception):
    """Base class for the errors this library raises itself.

    Errors on the link or from the device are modbus-connection's
    ``ModbusError`` subclasses, and propagate unchanged.
    """


class UnsupportedMeterError(VictronEnergyMeterError):
    """The device answers, but not with a product id this library knows."""

    def __init__(self, product_id: int | None) -> None:
        self.product_id = product_id
        shown = f"{product_id:#06x}" if product_id is not None else "none"
        super().__init__(f"Unsupported product id: {shown}")


class UnsupportedFirmwareError(VictronEnergyMeterError):
    """The meter's firmware is too old to report measurements over Modbus."""
