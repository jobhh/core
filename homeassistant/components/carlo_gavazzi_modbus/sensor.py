"""Support for Carlo Gavazzi Modbus sensor entities."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import override

from carlo_gavazzi_energy_meter_modbus import (
    DemandInterval,
    DeviceState,
    DigitalInputFunction,
    EM500Meter,
    MeasurementMode,
    MeasuringSystem,
    Meter,
    PhaseSequence,
    Tariff,
    TariffSource,
    em300,
)

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactiveEnergy,
    UnitOfReactivePower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import CarloGavazziModbusConfigEntry
from .entity import CarloGavazziModbusEntity

PARALLEL_UPDATES = 0

PHASES = (1, 2, 3)

# Where a value comes from where the two series keep it in different blocks.
SOURCE_TOTALS = "totals"
"""The energy totals, from the finest counters the meter serves."""
SOURCE_DETAIL = "detail"
"""The partial and per-phase energy counters."""
SOURCE_RUN_HOURS = "run_hours"


def _resolve(meter: Meter, subsystem: str) -> str:
    """Return the sub-system a value is read from on this meter."""
    if isinstance(meter, EM500Meter):
        if subsystem in (SOURCE_TOTALS, SOURCE_DETAIL, SOURCE_RUN_HOURS):
            return "energy"
        return subsystem
    if subsystem == SOURCE_TOTALS:
        best = meter.best_energy()
        return next(
            name
            for name in ("energy_wh", "energy_precise", "energy")
            if getattr(meter, name) is best
        )
    if subsystem == SOURCE_DETAIL:
        return "energy" if meter.energy_wh is None else "energy_wh"
    return subsystem


def _serves(meter: Meter, subsystem: str, field: str) -> bool:
    """Return whether the meter reads ``field`` of a sub-system.

    The EM300 series lacks some of the EM500 series' fields, serves some blocks
    only on certain models, and some fields only on certain models.
    """
    if (component := getattr(meter, subsystem, None)) is None:
        return False
    if field in component.declared_fields:
        return field in component.resolved_fields
    return isinstance(getattr(type(component), field, None), property)


LINES = {1: "L1-L2", 2: "L2-L3", 3: "L3-L1"}


@dataclass(frozen=True, kw_only=True)
class CarloGavazziModbusSensorEntityDescription(SensorEntityDescription):
    """Describes a Carlo Gavazzi Modbus sensor entity."""

    subsystem: str
    """The sub-system the value comes from, or one of the ``SOURCE_`` names."""

    field: str
    exists_fn: Callable[[Meter], bool] = lambda _: True


def _is_em500(meter: Meter) -> bool:
    """Return whether the meter is of the EM500 series."""
    return isinstance(meter, EM500Meter)


def _is_em300(meter: Meter) -> bool:
    """Return whether the meter is of the EM300 series."""
    return not isinstance(meter, EM500Meter)


def _has_phase(phase: int) -> Callable[[Meter], bool]:
    """Return whether the meter measures a phase: a 2P system has no L3."""
    return lambda meter: phase < 3 or meter.phases != 2


def _has_neutral_phase(phase: int) -> Callable[[Meter], bool]:
    """Return whether the meter measures a phase against a neutral."""
    return lambda meter: _has_phase(phase)(meter) and meter.has_neutral is not False


def _measures_export(meter: Meter) -> bool:
    """Return whether the exported energy counters move.

    In measurement mode A everything counts as imported.
    """
    return bool(meter.measures_export)


def _enum(
    *,
    key: str,
    subsystem: str,
    field: str,
    options: type[IntEnum],
    enabled: bool = False,
    exists_fn: Callable[[Meter], bool] = lambda _: True,
) -> CarloGavazziModbusSensorEntityDescription:
    """Describe a diagnostic sensor reporting one of an enum's members."""
    return CarloGavazziModbusSensorEntityDescription(
        key=key,
        translation_key=key,
        subsystem=subsystem,
        device_class=SensorDeviceClass.ENUM,
        options=[member.name.lower() for member in options],
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=enabled,
        exists_fn=exists_fn,
        field=field,
    )


def _per_phase(
    *,
    key: str,
    subsystem: str,
    field: str,
    translation_key: str,
    device_class: SensorDeviceClass | None,
    unit: str,
    precision: int,
    state_class: SensorStateClass = SensorStateClass.MEASUREMENT,
    enabled: bool = True,
    neutral: bool = False,
    exists_fn: Callable[[Meter], bool] = lambda _: True,
) -> tuple[CarloGavazziModbusSensorEntityDescription, ...]:
    """Describe one sensor per phase; ``{n}`` in key and field is the phase."""
    has_phase = _has_neutral_phase if neutral else _has_phase

    def exists(phase: int) -> Callable[[Meter], bool]:
        return lambda meter: has_phase(phase)(meter) and exists_fn(meter)

    return tuple(
        CarloGavazziModbusSensorEntityDescription(
            key=key.format(n=phase),
            translation_key=translation_key,
            translation_placeholders={"phase": f"L{phase}"},
            subsystem=subsystem,
            device_class=device_class,
            native_unit_of_measurement=unit,
            state_class=state_class,
            suggested_display_precision=precision,
            entity_registry_enabled_default=enabled,
            exists_fn=exists(phase),
            field=field.format(n=phase),
        )
        for phase in PHASES
    )


SENSORS: tuple[CarloGavazziModbusSensorEntityDescription, ...] = (
    CarloGavazziModbusSensorEntityDescription(
        key="active_power",
        subsystem="measurements",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        field="active_power",
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="apparent_power",
        subsystem="measurements",
        device_class=SensorDeviceClass.APPARENT_POWER,
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        field="apparent_power",
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="reactive_power",
        subsystem="measurements",
        device_class=SensorDeviceClass.REACTIVE_POWER,
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        field="reactive_power",
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="power_factor",
        subsystem="measurements",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        field="power_factor",
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="frequency",
        subsystem="measurements",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        field="frequency",
    ),
    *_per_phase(
        key="voltage_l{n}",
        subsystem="measurements",
        field="voltage_l{n}_n",
        translation_key="voltage_phase",
        device_class=SensorDeviceClass.VOLTAGE,
        unit=UnitOfElectricPotential.VOLT,
        precision=1,
        neutral=True,
    ),
    *(
        CarloGavazziModbusSensorEntityDescription(
            key=f"voltage_{line.lower().replace('-', '_')}",
            translation_key="voltage_line",
            translation_placeholders={"line": line},
            subsystem="measurements",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
            entity_registry_enabled_default=False,
            exists_fn=_has_phase(phase),
            field=f"voltage_{line.lower().replace('-', '_')}",
        )
        for phase, line in LINES.items()
    ),
    *_per_phase(
        key="current_l{n}",
        subsystem="measurements",
        field="current_l{n}",
        translation_key="current_phase",
        device_class=SensorDeviceClass.CURRENT,
        unit=UnitOfElectricCurrent.AMPERE,
        precision=2,
    ),
    *_per_phase(
        key="active_power_l{n}",
        subsystem="measurements",
        field="active_power_l{n}",
        translation_key="active_power_phase",
        device_class=SensorDeviceClass.POWER,
        unit=UnitOfPower.WATT,
        precision=0,
    ),
    *_per_phase(
        key="apparent_power_l{n}",
        subsystem="measurements",
        field="apparent_power_l{n}",
        translation_key="apparent_power_phase",
        device_class=SensorDeviceClass.APPARENT_POWER,
        unit=UnitOfApparentPower.VOLT_AMPERE,
        precision=0,
        enabled=False,
    ),
    *_per_phase(
        key="reactive_power_l{n}",
        subsystem="measurements",
        field="reactive_power_l{n}",
        translation_key="reactive_power_phase",
        device_class=SensorDeviceClass.REACTIVE_POWER,
        unit=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        precision=0,
        enabled=False,
    ),
    *(
        CarloGavazziModbusSensorEntityDescription(
            key=f"power_factor_l{phase}",
            translation_key="power_factor_phase",
            translation_placeholders={"phase": f"L{phase}"},
            subsystem="measurements",
            device_class=SensorDeviceClass.POWER_FACTOR,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=3,
            entity_registry_enabled_default=False,
            exists_fn=_has_phase(phase),
            field=f"power_factor_l{phase}",
        )
        for phase in PHASES
    ),
    _enum(
        key="phase_sequence",
        subsystem="measurements",
        field="phase_sequence",
        options=PhaseSequence,
        # Meaningful only with three phases.
        exists_fn=lambda meter: meter.phases != 2,
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="energy_imported",
        translation_key="energy_imported",
        subsystem=SOURCE_TOTALS,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        field="energy_imported",
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="energy_exported",
        translation_key="energy_exported",
        subsystem=SOURCE_TOTALS,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        exists_fn=_measures_export,
        field="energy_exported",
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="energy_imported_partial",
        translation_key="energy_imported_partial",
        subsystem=SOURCE_DETAIL,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        field="energy_imported_partial",
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="energy_exported_partial",
        translation_key="energy_exported_partial",
        subsystem=SOURCE_DETAIL,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        exists_fn=_measures_export,
        field="energy_exported_partial",
    ),
    *_per_phase(
        key="energy_imported_l{n}",
        subsystem=SOURCE_DETAIL,
        field="energy_imported_l{n}",
        translation_key="energy_imported_phase",
        device_class=SensorDeviceClass.ENERGY,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        enabled=False,
    ),
    *_per_phase(
        key="energy_exported_l{n}",
        subsystem="exported_per_phase",
        field="energy_exported_l{n}",
        translation_key="energy_exported_phase",
        device_class=SensorDeviceClass.ENERGY,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        enabled=False,
        exists_fn=_measures_export,
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="reactive_energy_imported",
        translation_key="reactive_energy_imported",
        subsystem=SOURCE_TOTALS,
        device_class=SensorDeviceClass.REACTIVE_ENERGY,
        native_unit_of_measurement=UnitOfReactiveEnergy.KILO_VOLT_AMPERE_REACTIVE_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        field="reactive_energy_imported",
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="reactive_energy_exported",
        translation_key="reactive_energy_exported",
        subsystem=SOURCE_TOTALS,
        device_class=SensorDeviceClass.REACTIVE_ENERGY,
        native_unit_of_measurement=UnitOfReactiveEnergy.KILO_VOLT_AMPERE_REACTIVE_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        exists_fn=_measures_export,
        field="reactive_energy_exported",
    ),
    *(
        CarloGavazziModbusSensorEntityDescription(
            key=f"energy_imported_tariff_{tariff}",
            translation_key="energy_imported_tariff",
            translation_placeholders={"tariff": str(tariff)},
            subsystem="tariff_energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL_INCREASING,
            suggested_display_precision=2,
            entity_registry_enabled_default=False,
            field=f"energy_imported_tariff_{tariff}",
        )
        for tariff in (1, 2)
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="run_hours",
        translation_key="run_hours",
        subsystem=SOURCE_RUN_HOURS,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        field="run_hours",
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="run_hours_lifetime",
        translation_key="run_hours_lifetime",
        subsystem="energy",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        field="run_hours_lifetime",
    ),
    *(
        CarloGavazziModbusSensorEntityDescription(
            key=key,
            translation_key=key,
            subsystem="demand",
            device_class=device_class,
            native_unit_of_measurement=unit,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
            entity_registry_enabled_default=False,
            field=f"{key}",
        )
        for key, device_class, unit in (
            ("active_power_demand", SensorDeviceClass.POWER, UnitOfPower.WATT),
            ("active_power_demand_max", SensorDeviceClass.POWER, UnitOfPower.WATT),
            (
                "apparent_power_demand",
                SensorDeviceClass.APPARENT_POWER,
                UnitOfApparentPower.VOLT_AMPERE,
            ),
            (
                "apparent_power_demand_max",
                SensorDeviceClass.APPARENT_POWER,
                UnitOfApparentPower.VOLT_AMPERE,
            ),
        )
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="neutral_current",
        translation_key="neutral_current",
        subsystem="power_quality",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        exists_fn=lambda meter: meter.has_neutral is not False,
        field="neutral_current",
    ),
    *_per_phase(
        key="thd_current_l{n}",
        subsystem="power_quality",
        field="thd_current_l{n}",
        translation_key="thd_current_phase",
        device_class=None,
        unit=PERCENTAGE,
        precision=2,
        enabled=False,
    ),
    *_per_phase(
        key="thd_voltage_l{n}",
        subsystem="power_quality",
        field="thd_voltage_l{n}_n",
        translation_key="thd_voltage_phase",
        device_class=None,
        unit=PERCENTAGE,
        precision=2,
        enabled=False,
        neutral=True,
    ),
    _enum(
        key="active_tariff",
        subsystem="status",
        field="active_tariff",
        options=Tariff,
    ),
    _enum(
        key="device_state",
        subsystem="status",
        field="device_state",
        options=DeviceState,
    ),
    # How the meter is set up on its own keys. The measuring system and mode
    # decide which of the sensors above exist, so they explain a missing one.
    _enum(
        key="measuring_system",
        subsystem="settings",
        field="measuring_system",
        options=MeasuringSystem,
        enabled=True,
    ),
    _enum(
        key="measurement_mode",
        subsystem="settings",
        field="measurement_mode",
        options=MeasurementMode,
        enabled=True,
        exists_fn=_is_em500,
    ),
    _enum(
        key="measurement_mode",
        subsystem="settings",
        field="measurement_mode",
        options=em300.MeasurementMode,
        enabled=True,
        exists_fn=_is_em300,
    ),
    CarloGavazziModbusSensorEntityDescription(
        key="demand_interval",
        translation_key="demand_interval",
        subsystem="settings",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        field="demand_interval",
    ),
    _enum(
        key="digital_input_function",
        subsystem="settings",
        field="digital_input_function",
        options=DigitalInputFunction,
    ),
    _enum(
        key="tariff_source",
        subsystem="settings",
        field="tariff_source",
        options=TariffSource,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CarloGavazziModbusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors for what the meter measures, as it is wired."""
    meter = entry.runtime_data.meter
    async_add_entities(
        CarloGavazziModbusSensorEntity(
            entry=entry, subsystem=subsystem, description=description
        )
        for description in SENSORS
        if _serves(
            meter,
            subsystem := _resolve(meter, description.subsystem),
            description.field,
        )
        and description.exists_fn(meter)
    )


class CarloGavazziModbusSensorEntity(CarloGavazziModbusEntity, SensorEntity):
    """Defines a Carlo Gavazzi Modbus sensor."""

    entity_description: CarloGavazziModbusSensorEntityDescription

    def __init__(
        self,
        *,
        entry: CarloGavazziModbusConfigEntry,
        subsystem: str,
        description: CarloGavazziModbusSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry=entry, subsystem=subsystem, description=description)
        self._field = description.field

    @property
    @override
    def native_value(self) -> StateType:
        """Return the value the meter reported on the last poll."""
        component = getattr(self.coordinator.meter, self._subsystem)
        value: StateType | IntEnum = getattr(component, self.entity_description.field)
        if isinstance(value, DemandInterval):
            # The EM300 series reports the interval in minutes to begin with.
            return value.minutes
        if isinstance(value, IntEnum):
            return value.name.lower()
        return value
