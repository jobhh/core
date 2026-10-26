"""Support for Carlo Gavazzi Modbus binary sensor entities."""

from collections.abc import Callable
from dataclasses import dataclass
from operator import attrgetter
from typing import override

from carlo_gavazzi_energy_meter_modbus import Meter

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import CarloGavazziModbusConfigEntry
from .entity import CarloGavazziModbusEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class CarloGavazziModbusBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Carlo Gavazzi Modbus binary sensor entity."""

    subsystem: str
    value_fn: Callable[[Meter], bool | None]


BINARY_SENSORS: tuple[CarloGavazziModbusBinarySensorEntityDescription, ...] = (
    CarloGavazziModbusBinarySensorEntityDescription(
        key="wrong_connection",
        translation_key="wrong_connection",
        subsystem="status",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=attrgetter("status.wrong_connection"),
    ),
    CarloGavazziModbusBinarySensorEntityDescription(
        key="alarm",
        translation_key="alarm",
        subsystem="status",
        entity_registry_enabled_default=False,
        value_fn=attrgetter("status.alarm"),
    ),
    CarloGavazziModbusBinarySensorEntityDescription(
        key="digital_input",
        translation_key="digital_input",
        subsystem="status",
        entity_registry_enabled_default=False,
        value_fn=attrgetter("status.digital_input"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CarloGavazziModbusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors for what the meter reports about itself.

    The EM300 series reports only the wiring check.
    """
    status = type(entry.runtime_data.coordinator.meter.status)
    async_add_entities(
        CarloGavazziModbusBinarySensorEntity(entry=entry, description=description)
        for description in BINARY_SENSORS
        if hasattr(status, description.key)
    )


class CarloGavazziModbusBinarySensorEntity(
    CarloGavazziModbusEntity, BinarySensorEntity
):
    """Defines a Carlo Gavazzi Modbus binary sensor."""

    entity_description: CarloGavazziModbusBinarySensorEntityDescription

    def __init__(
        self,
        *,
        entry: CarloGavazziModbusConfigEntry,
        description: CarloGavazziModbusBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            entry=entry, subsystem=description.subsystem, description=description
        )
        self._field = description.key

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the state the meter reported on the last poll."""
        return self.entity_description.value_fn(self.coordinator.meter)
