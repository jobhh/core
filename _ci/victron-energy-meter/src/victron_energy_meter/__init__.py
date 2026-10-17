"""Read Victron Energy VM-3P75CT and VM-3P5A energy meters over Modbus UDP."""

from modbus_connection.model import UpdateReport

from .components import (
    Configuration,
    HighRangeCurrents,
    Identity,
    Phase,
    PhaseDetail,
    Totals,
)
from .device import (
    MDNS_SERVICE,
    PORT,
    UNIT_ID,
    VictronEnergyMeter,
    async_identify,
)
from .enums import (
    Capability,
    PhaseConfiguration,
    PhaseRotationAlarm,
    PhaseSequence,
    Position,
    Role,
)
from .exceptions import (
    UnsupportedFirmwareError,
    UnsupportedMeterError,
    VictronEnergyMeterError,
)
from .models import MODELS, FirmwareVersion, MeterModel, ProductId, model_for_product_id

__all__ = [
    "MDNS_SERVICE",
    "MODELS",
    "PORT",
    "UNIT_ID",
    "Capability",
    "Configuration",
    "FirmwareVersion",
    "HighRangeCurrents",
    "Identity",
    "MeterModel",
    "Phase",
    "PhaseConfiguration",
    "PhaseDetail",
    "PhaseRotationAlarm",
    "PhaseSequence",
    "Position",
    "ProductId",
    "Role",
    "Totals",
    "UnsupportedFirmwareError",
    "UnsupportedMeterError",
    "UpdateReport",
    "VictronEnergyMeter",
    "VictronEnergyMeterError",
    "async_identify",
    "model_for_product_id",
]
