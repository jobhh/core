"""Base entity for the Victron Energy Meter integration."""

from dataclasses import dataclass
from typing import override

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import VictronMeterCoordinator, VictronMeterRuntimeData


@dataclass(frozen=True, kw_only=True)
class VictronMeterEntityDescription(EntityDescription):
    """Describe an entity backed by one sub-system of a meter."""

    component: str
    """The attribute of the library's device object this entity reads."""

    from_settings: bool = False
    """Whether the component is polled with the settings, not the readings."""


class VictronMeterEntity(CoordinatorEntity[VictronMeterCoordinator]):
    """An entity on a Victron energy meter."""

    _attr_has_entity_name = True
    entity_description: VictronMeterEntityDescription

    def __init__(
        self,
        runtime_data: VictronMeterRuntimeData,
        description: VictronMeterEntityDescription,
    ) -> None:
        """Initialize the entity."""
        coordinator = (
            runtime_data.settings if description.from_settings else runtime_data.readings
        )
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{runtime_data.meter.serial_number}_{description.key}"
        self._attr_device_info = runtime_data.device_info

    @property
    @override
    def available(self) -> bool:
        """Whether this entity's sub-system answered the latest poll."""
        if not super().available or self.coordinator.data is None:
            return False
        return self.entity_description.component not in self.coordinator.data.failed
