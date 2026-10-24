"""Base entity for the Carlo Gavazzi Modbus integration.

Every identity derives from the meter's serial number, which the config flow
stores as the config entry unique ID.
"""

from typing import TYPE_CHECKING, override

from carlo_gavazzi_energy_meter_modbus import EM500Meter

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import (
    CarloGavazziModbusConfigEntry,
    CarloGavazziModbusDataUpdateCoordinator,
)


def meter_name(meter: EM500Meter) -> str:
    """Return a name for a set-up meter, such as "Carlo Gavazzi EM540"."""
    if TYPE_CHECKING:
        assert meter.model is not None
    return f"Carlo Gavazzi {meter.model.family}"


def meter_device_info(meter: EM500Meter, serial_number: str) -> DeviceInfo:
    """Return device information for a set-up meter."""
    model = meter.model
    if TYPE_CHECKING:
        assert model is not None
    return DeviceInfo(
        identifiers={(DOMAIN, serial_number)},
        manufacturer="Carlo Gavazzi",
        # The model name carries the MID variant, such as "EM540 PFC"; the
        # part number spells out the rest.
        model=model.name,
        model_id=model.part_number,
        name=meter_name(meter),
        sw_version=meter.firmware_version,
        serial_number=serial_number,
    )


class CarloGavazziModbusEntity(
    CoordinatorEntity[CarloGavazziModbusDataUpdateCoordinator]
):
    """Defines a Carlo Gavazzi Modbus entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        *,
        entry: CarloGavazziModbusConfigEntry,
        subsystem: str,
        description: EntityDescription,
    ) -> None:
        """Initialize a Carlo Gavazzi Modbus entity."""
        super().__init__(coordinator=entry.runtime_data.coordinator)
        self.entity_description = description
        self._subsystem = subsystem
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = entry.runtime_data.device_info

    @property
    @override
    def available(self) -> bool:
        """Return whether this entity's sub-system answered the last poll."""
        return super().available and self._subsystem not in self.coordinator.data.failed
