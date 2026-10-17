"""Binary sensors for the Victron Energy Meter integration."""

from collections.abc import Callable
from dataclasses import dataclass
from operator import attrgetter
from typing import Any, override

from victron_energy_meter import VictronEnergyMeter

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import VictronMeterConfigEntry, VictronMeterRuntimeData
from .entity import VictronMeterEntity, VictronMeterEntityDescription

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class VictronMeterBinarySensorDescription(
    BinarySensorEntityDescription, VictronMeterEntityDescription
):
    """Describe a binary sensor on a Victron energy meter."""

    value_fn: Callable[[Any], bool | None]


CARLO_GAVAZZI_BINARY_SENSORS = (
    VictronMeterBinarySensorDescription(
        key="alarm",
        translation_key="alarm",
        component="status",
        value_fn=attrgetter("status.alarm"),
        entity_registry_enabled_default=False,
    ),
    VictronMeterBinarySensorDescription(
        key="digital_input",
        translation_key="digital_input",
        component="status",
        value_fn=attrgetter("status.digital_input"),
        entity_registry_enabled_default=False,
    ),
    VictronMeterBinarySensorDescription(
        key="wrong_connection",
        translation_key="wrong_connection",
        component="status",
        value_fn=attrgetter("status.wrong_connection"),
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VictronMeterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors of a Carlo Gavazzi meter.

    Victron's own meters report no on/off states.
    """
    runtime_data = entry.runtime_data
    meter = runtime_data.meter
    if isinstance(meter, VictronEnergyMeter):
        return
    # The EM300 series reports only the wiring check.
    async_add_entities(
        VictronMeterBinarySensor(runtime_data, description)
        for description in CARLO_GAVAZZI_BINARY_SENSORS
        if hasattr(getattr(meter, description.component), description.key)
    )


class VictronMeterBinarySensor(VictronMeterEntity, BinarySensorEntity):
    """A binary sensor on a Victron energy meter."""

    entity_description: VictronMeterBinarySensorDescription

    def __init__(
        self,
        runtime_data: VictronMeterRuntimeData,
        description: VictronMeterBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(runtime_data, description)
        self._meter = runtime_data.meter

    @property
    @override
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self._meter)
