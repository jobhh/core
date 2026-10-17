"""Buttons for the Victron Energy Meter integration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import override

from carlo_gavazzi_modbus import EM500Meter
from modbus_connection import ModbusError

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import VictronMeterConfigEntry, VictronMeterRuntimeData
from .entity import VictronMeterEntity, VictronMeterEntityDescription

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class VictronMeterButtonDescription(
    ButtonEntityDescription, VictronMeterEntityDescription
):
    """Describe a command button on a meter."""

    press_fn: Callable[[EM500Meter], Awaitable[None]]


# Resetting the lifetime counters is left out on purpose: it would break the
# long-term energy statistics, and MID meters refuse it anyway.
CARLO_GAVAZZI_BUTTONS = (
    VictronMeterButtonDescription(
        key="reset_partial_counters",
        translation_key="reset_partial_counters",
        component="energy",
        press_fn=lambda meter: meter.async_reset_partial_counters(),
        entity_category=EntityCategory.CONFIG,
    ),
    VictronMeterButtonDescription(
        key="reset_demand",
        translation_key="reset_demand",
        component="demand",
        press_fn=lambda meter: meter.async_reset_demand(),
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    VictronMeterButtonDescription(
        key="reset_tariff_counters",
        translation_key="reset_tariff_counters",
        component="tariff_energy",
        press_fn=lambda meter: meter.async_reset_tariff_counters(),
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VictronMeterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the command buttons of a Carlo Gavazzi meter.

    Victron's own meters accept no commands over Modbus.
    """
    runtime_data = entry.runtime_data
    if not isinstance(runtime_data.meter, EM500Meter):
        return
    async_add_entities(
        VictronMeterButton(runtime_data, runtime_data.meter, description)
        for description in CARLO_GAVAZZI_BUTTONS
    )


class VictronMeterButton(VictronMeterEntity, ButtonEntity):
    """A command button on a meter."""

    entity_description: VictronMeterButtonDescription

    def __init__(
        self,
        runtime_data: VictronMeterRuntimeData,
        meter: EM500Meter,
        description: VictronMeterButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(runtime_data, description)
        self._meter = meter

    @override
    async def async_press(self) -> None:
        try:
            await self.entity_description.press_fn(self._meter)
        except ModbusError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err) or type(err).__name__},
            ) from err
        await self.coordinator.async_request_refresh()
