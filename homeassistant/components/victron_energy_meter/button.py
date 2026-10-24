"""Buttons for the Victron Energy Meter integration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, override

from carlo_gavazzi_energy_meter_modbus import EM500Meter, Meter as CarloGavazziMeter
from modbus_connection import ModbusError
from victron_energy_meter_modbus import VictronEnergyMeter

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

    press_fn: Callable[[Any], Awaitable[None]]
    supported_fn: Callable[[CarloGavazziMeter], bool] = lambda _: True


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
        # The EM300 series resets the demand with the partial counters.
        supported_fn=lambda meter: isinstance(meter, EM500Meter),
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    VictronMeterButtonDescription(
        key="reset_tariff_counters",
        translation_key="reset_tariff_counters",
        component="tariff_energy",
        press_fn=lambda meter: meter.async_reset_tariff_counters(),
        supported_fn=lambda meter: isinstance(meter, EM500Meter),
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
    meter = runtime_data.meter
    if isinstance(meter, VictronEnergyMeter):
        return
    async_add_entities(
        VictronMeterButton(runtime_data, meter, description)
        for description in CARLO_GAVAZZI_BUTTONS
        if description.supported_fn(meter)
    )


class VictronMeterButton(VictronMeterEntity, ButtonEntity):
    """A command button on a meter."""

    entity_description: VictronMeterButtonDescription

    def __init__(
        self,
        runtime_data: VictronMeterRuntimeData,
        meter: CarloGavazziMeter,
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
