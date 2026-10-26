"""Support for Carlo Gavazzi Modbus button entities."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, override

from carlo_gavazzi_energy_meter_modbus import EM500Meter, Meter
from modbus_connection import ModbusError

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import CarloGavazziModbusConfigEntry
from .entity import CarloGavazziModbusEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class CarloGavazziModbusButtonEntityDescription(ButtonEntityDescription):
    """Describes a Carlo Gavazzi Modbus button entity."""

    subsystem: str
    press_fn: Callable[[Any], Awaitable[None]]
    supported_fn: Callable[[Meter], bool] = lambda _: True


# Resetting the lifetime counters is left out on purpose: it would break the
# long-term energy statistics, and the MID variants refuse it anyway.
BUTTONS: tuple[CarloGavazziModbusButtonEntityDescription, ...] = (
    CarloGavazziModbusButtonEntityDescription(
        key="reset_partial_counters",
        translation_key="reset_partial_counters",
        subsystem="energy",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda meter: meter.async_reset_partial_counters(),
    ),
    CarloGavazziModbusButtonEntityDescription(
        key="reset_demand",
        translation_key="reset_demand",
        subsystem="demand",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=lambda meter: meter.async_reset_demand(),
        supported_fn=lambda meter: isinstance(meter, EM500Meter),
    ),
    CarloGavazziModbusButtonEntityDescription(
        key="reset_tariff_counters",
        translation_key="reset_tariff_counters",
        subsystem="tariff_energy",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=lambda meter: meter.async_reset_tariff_counters(),
        supported_fn=lambda meter: isinstance(meter, EM500Meter),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CarloGavazziModbusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons for the meter's reset commands."""
    async_add_entities(
        CarloGavazziModbusButtonEntity(entry=entry, description=description)
        for description in BUTTONS
        if description.supported_fn(entry.runtime_data.meter)
    )


class CarloGavazziModbusButtonEntity(CarloGavazziModbusEntity, ButtonEntity):
    """Defines a Carlo Gavazzi Modbus button."""

    entity_description: CarloGavazziModbusButtonEntityDescription

    def __init__(
        self,
        *,
        entry: CarloGavazziModbusConfigEntry,
        description: CarloGavazziModbusButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(
            entry=entry, subsystem=description.subsystem, description=description
        )

    @override
    async def async_press(self) -> None:
        """Send the command, then read back what it changed."""
        try:
            await self.entity_description.press_fn(self.coordinator.meter)
        except ModbusError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err) or type(err).__name__},
            ) from err
        await self.coordinator.async_request_refresh()
