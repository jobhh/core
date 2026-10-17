"""Sensors for the Victron Energy Meter integration."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from operator import attrgetter, methodcaller
from typing import Any, override

from carlo_gavazzi_modbus import (
    DeviceState,
    EM500Meter,
    PhaseSequence as CarloGavazziPhaseSequence,
    Tariff,
)
from victron_energy_meter import (
    PhaseRotationAlarm,
    PhaseSequence as VictronPhaseSequence,
    VictronEnergyMeter,
)

from homeassistant.components.sensor import (
    RestoreSensor,
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

from .coordinator import VictronMeterConfigEntry, VictronMeterRuntimeData
from .entity import VictronMeterEntity, VictronMeterEntityDescription
from .helpers import Meter

PARALLEL_UPDATES = 0

LINES = {1: "L1-L2", 2: "L2-L3", 3: "L3-L1"}


@dataclass(frozen=True, kw_only=True)
class VictronMeterSensorDescription(
    SensorEntityDescription, VictronMeterEntityDescription
):
    """Describe a sensor on a Victron energy meter."""

    value_fn: Callable[[Any], Any]


@dataclass(frozen=True, kw_only=True)
class _Kind:
    """The device class, unit and state class a kind of measurement shares."""

    device_class: SensorDeviceClass | None
    unit: str | None
    state_class: SensorStateClass | None
    precision: int | None = None


POWER = _Kind(
    device_class=SensorDeviceClass.POWER,
    unit=UnitOfPower.WATT,
    state_class=SensorStateClass.MEASUREMENT,
    precision=0,
)
APPARENT_POWER = _Kind(
    device_class=SensorDeviceClass.APPARENT_POWER,
    unit=UnitOfApparentPower.VOLT_AMPERE,
    state_class=SensorStateClass.MEASUREMENT,
    precision=0,
)
REACTIVE_POWER = _Kind(
    device_class=SensorDeviceClass.REACTIVE_POWER,
    unit=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
    state_class=SensorStateClass.MEASUREMENT,
    precision=0,
)
VOLTAGE = _Kind(
    device_class=SensorDeviceClass.VOLTAGE,
    unit=UnitOfElectricPotential.VOLT,
    state_class=SensorStateClass.MEASUREMENT,
    precision=1,
)
CURRENT = _Kind(
    device_class=SensorDeviceClass.CURRENT,
    unit=UnitOfElectricCurrent.AMPERE,
    state_class=SensorStateClass.MEASUREMENT,
    precision=2,
)
FREQUENCY = _Kind(
    device_class=SensorDeviceClass.FREQUENCY,
    unit=UnitOfFrequency.HERTZ,
    state_class=SensorStateClass.MEASUREMENT,
    precision=2,
)
POWER_FACTOR = _Kind(
    device_class=SensorDeviceClass.POWER_FACTOR,
    unit=None,
    state_class=SensorStateClass.MEASUREMENT,
    precision=3,
)
ENERGY = _Kind(
    device_class=SensorDeviceClass.ENERGY,
    unit=UnitOfEnergy.KILO_WATT_HOUR,
    state_class=SensorStateClass.TOTAL_INCREASING,
    precision=2,
)
REACTIVE_ENERGY = _Kind(
    device_class=SensorDeviceClass.REACTIVE_ENERGY,
    unit=UnitOfReactiveEnergy.KILO_VOLT_AMPERE_REACTIVE_HOUR,
    state_class=SensorStateClass.TOTAL_INCREASING,
    precision=2,
)
PERCENT = _Kind(
    device_class=None,
    unit=PERCENTAGE,
    state_class=SensorStateClass.MEASUREMENT,
    precision=2,
)
HOURS = _Kind(
    device_class=SensorDeviceClass.DURATION,
    unit=UnitOfTime.HOURS,
    state_class=SensorStateClass.TOTAL_INCREASING,
    precision=2,
)


def _sensor(
    key: str,
    component: str,
    value_fn: Callable[[Any], Any],
    kind: _Kind,
    *,
    translation_key: str | None = None,
    phase: str | None = None,
    enabled: bool = True,
    diagnostic: bool = False,
) -> VictronMeterSensorDescription:
    """Describe a numeric sensor."""
    return VictronMeterSensorDescription(
        key=key,
        translation_key=translation_key or key,
        translation_placeholders={"phase": phase} if phase is not None else None,
        component=component,
        value_fn=value_fn,
        device_class=kind.device_class,
        native_unit_of_measurement=kind.unit,
        state_class=kind.state_class,
        suggested_display_precision=kind.precision,
        entity_registry_enabled_default=enabled,
        entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,
    )


def _enum_sensor(
    key: str,
    component: str,
    value_fn: Callable[[Any], Any],
    options: type[IntEnum],
    *,
    enabled: bool = False,
    from_settings: bool = False,
) -> VictronMeterSensorDescription:
    """Describe a diagnostic sensor reporting one of an enum's members."""
    return VictronMeterSensorDescription(
        key=key,
        translation_key=key,
        component=component,
        from_settings=from_settings,
        value_fn=value_fn,
        device_class=SensorDeviceClass.ENUM,
        options=[member.name.lower() for member in options],
        entity_registry_enabled_default=enabled,
        entity_category=EntityCategory.DIAGNOSTIC,
    )


def _carlo_gavazzi(meter: EM500Meter) -> list[VictronMeterSensorDescription]:
    """The sensors an EM530 or EM540 serves, as it is wired and configured."""
    phases = (1, 2) if meter.phases == 2 else (1, 2, 3)
    neutral = meter.has_neutral is not False
    export = bool(meter.measures_export)
    m, q, d, e = "measurements", "power_quality", "demand", "energy"

    sensors = [
        _sensor("active_power", m, attrgetter(f"{m}.active_power"), POWER),
        _sensor(
            "apparent_power",
            m,
            attrgetter(f"{m}.apparent_power"),
            APPARENT_POWER,
            enabled=False,
        ),
        _sensor(
            "reactive_power",
            m,
            attrgetter(f"{m}.reactive_power"),
            REACTIVE_POWER,
            enabled=False,
        ),
        _sensor("power_factor", m, attrgetter(f"{m}.power_factor"), POWER_FACTOR),
        _sensor("frequency", m, attrgetter(f"{m}.frequency"), FREQUENCY),
        _sensor("energy_imported", e, attrgetter(f"{e}.energy_imported"), ENERGY),
        _sensor(
            "energy_imported_partial",
            e,
            attrgetter(f"{e}.energy_imported_partial"),
            ENERGY,
            enabled=False,
        ),
        _sensor(
            "reactive_energy_imported",
            e,
            attrgetter(f"{e}.reactive_energy_imported"),
            REACTIVE_ENERGY,
            enabled=False,
        ),
        _sensor(
            "energy_imported_tariff_1",
            "tariff_energy",
            attrgetter("tariff_energy.energy_imported_tariff_1"),
            ENERGY,
            enabled=False,
        ),
        _sensor(
            "energy_imported_tariff_2",
            "tariff_energy",
            attrgetter("tariff_energy.energy_imported_tariff_2"),
            ENERGY,
            enabled=False,
        ),
        _sensor(
            "active_power_demand",
            d,
            attrgetter(f"{d}.active_power_demand"),
            POWER,
            enabled=False,
        ),
        _sensor(
            "active_power_demand_max",
            d,
            attrgetter(f"{d}.active_power_demand_max"),
            POWER,
            enabled=False,
        ),
        _sensor(
            "apparent_power_demand",
            d,
            attrgetter(f"{d}.apparent_power_demand"),
            APPARENT_POWER,
            enabled=False,
        ),
        _sensor(
            "apparent_power_demand_max",
            d,
            attrgetter(f"{d}.apparent_power_demand_max"),
            APPARENT_POWER,
            enabled=False,
        ),
        _sensor(
            "run_hours",
            e,
            attrgetter(f"{e}.run_hours"),
            HOURS,
            enabled=False,
            diagnostic=True,
        ),
        _sensor(
            "run_hours_lifetime",
            e,
            attrgetter(f"{e}.run_hours_lifetime"),
            HOURS,
            enabled=False,
            diagnostic=True,
        ),
        _enum_sensor(
            "active_tariff", "status", attrgetter("status.active_tariff"), Tariff
        ),
        _enum_sensor(
            "device_state", "status", attrgetter("status.device_state"), DeviceState
        ),
    ]
    if export:
        sensors += [
            _sensor("energy_exported", e, attrgetter(f"{e}.energy_exported"), ENERGY),
            _sensor(
                "energy_exported_partial",
                e,
                attrgetter(f"{e}.energy_exported_partial"),
                ENERGY,
                enabled=False,
            ),
            _sensor(
                "reactive_energy_exported",
                e,
                attrgetter(f"{e}.reactive_energy_exported"),
                REACTIVE_ENERGY,
                enabled=False,
            ),
        ]
    if neutral:
        sensors += [
            _sensor(
                "neutral_current",
                q,
                attrgetter(f"{q}.neutral_current"),
                CURRENT,
                enabled=False,
            ),
        ]
    if len(phases) == 3:
        sensors += [
            _enum_sensor(
                "phase_sequence",
                m,
                attrgetter(f"{m}.phase_sequence"),
                CarloGavazziPhaseSequence,
            ),
        ]
    for n in phases:
        phase = f"L{n}"
        line = LINES[n]
        line_field = line.lower().replace("-", "_")
        sensors += [
            _sensor(
                f"current_l{n}",
                m,
                attrgetter(f"{m}.current_l{n}"),
                CURRENT,
                translation_key="current_phase",
                phase=phase,
            ),
            _sensor(
                f"active_power_l{n}",
                m,
                attrgetter(f"{m}.active_power_l{n}"),
                POWER,
                translation_key="active_power_phase",
                phase=phase,
            ),
            _sensor(
                f"apparent_power_l{n}",
                m,
                attrgetter(f"{m}.apparent_power_l{n}"),
                APPARENT_POWER,
                translation_key="apparent_power_phase",
                phase=phase,
                enabled=False,
            ),
            _sensor(
                f"reactive_power_l{n}",
                m,
                attrgetter(f"{m}.reactive_power_l{n}"),
                REACTIVE_POWER,
                translation_key="reactive_power_phase",
                phase=phase,
                enabled=False,
            ),
            _sensor(
                f"power_factor_l{n}",
                m,
                attrgetter(f"{m}.power_factor_l{n}"),
                POWER_FACTOR,
                translation_key="power_factor_phase",
                phase=phase,
                enabled=False,
            ),
            _sensor(
                f"voltage_{line_field}",
                m,
                attrgetter(f"{m}.voltage_{line_field}"),
                VOLTAGE,
                translation_key="voltage_line",
                phase=line,
                enabled=False,
            ),
            _sensor(
                f"energy_imported_l{n}",
                e,
                attrgetter(f"{e}.energy_imported_l{n}"),
                ENERGY,
                translation_key="energy_imported_phase",
                phase=phase,
                enabled=False,
            ),
            _sensor(
                f"thd_current_l{n}",
                q,
                attrgetter(f"{q}.thd_current_l{n}"),
                PERCENT,
                translation_key="thd_current_phase",
                phase=phase,
                enabled=False,
            ),
        ]
        if neutral:
            sensors += [
                _sensor(
                    f"voltage_l{n}",
                    m,
                    attrgetter(f"{m}.voltage_l{n}_n"),
                    VOLTAGE,
                    translation_key="voltage_phase",
                    phase=phase,
                ),
                _sensor(
                    f"thd_voltage_l{n}",
                    q,
                    attrgetter(f"{q}.thd_voltage_l{n}_n"),
                    PERCENT,
                    translation_key="thd_voltage_phase",
                    phase=phase,
                    enabled=False,
                ),
            ]
    return sensors


def _victron(meter: VictronEnergyMeter) -> list[VictronMeterSensorDescription]:
    """The sensors a VM-3P75CT or VM-3P5A serves, for its phases and firmware."""
    firmware = meter.firmware_version
    assert firmware is not None
    v107 = firmware.at_least(1, 7)
    v109 = firmware.at_least(1, 9)
    t = "totals"

    sensors = [
        _sensor("active_power", t, attrgetter(f"{t}.active_power"), POWER),
        _sensor("frequency", t, attrgetter(f"{t}.frequency"), FREQUENCY),
        _sensor("energy_imported", t, attrgetter(f"{t}.energy_forward"), ENERGY),
        _sensor("energy_exported", t, attrgetter(f"{t}.energy_reverse"), ENERGY),
        _sensor(
            "pe_n_voltage", t, attrgetter(f"{t}.pe_n_voltage"), VOLTAGE, enabled=False
        ),
        _sensor(
            "error_code",
            t,
            attrgetter(f"{t}.error_code"),
            _Kind(device_class=None, unit=None, state_class=None),
            enabled=False,
            diagnostic=True,
        ),
    ]
    if v107:
        sensors += [
            _sensor(
                "neutral_current",
                t,
                attrgetter(f"{t}.neutral_current"),
                CURRENT,
                enabled=False,
            ),
        ]
    if v109:
        sensors += [
            _sensor("power_factor", t, attrgetter(f"{t}.power_factor"), POWER_FACTOR),
            _enum_sensor(
                "phase_sequence",
                t,
                attrgetter(f"{t}.phase_sequence"),
                VictronPhaseSequence,
            ),
            _enum_sensor(
                "phase_rotation",
                t,
                attrgetter(f"{t}.phase_rotation_alarm"),
                PhaseRotationAlarm,
            ),
        ]
    current_component = (
        "high_range_currents" if meter.high_range_currents is not None else None
    )
    for n in meter.phases:
        phase = f"L{n}"
        p = f"phase_l{n}"
        sensors += [
            _sensor(
                f"voltage_l{n}",
                p,
                attrgetter(f"{p}.voltage"),
                VOLTAGE,
                translation_key="voltage_phase",
                phase=phase,
            ),
            _sensor(
                f"current_l{n}",
                current_component or p,
                methodcaller("current", n),
                CURRENT,
                translation_key="current_phase",
                phase=phase,
            ),
            _sensor(
                f"active_power_l{n}",
                p,
                attrgetter(f"{p}.active_power"),
                POWER,
                translation_key="active_power_phase",
                phase=phase,
            ),
            _sensor(
                f"apparent_power_l{n}",
                p,
                attrgetter(f"{p}.apparent_power"),
                APPARENT_POWER,
                translation_key="apparent_power_phase",
                phase=phase,
                enabled=False,
            ),
            _sensor(
                f"energy_imported_l{n}",
                p,
                attrgetter(f"{p}.energy_forward"),
                ENERGY,
                translation_key="energy_imported_phase",
                phase=phase,
                enabled=False,
            ),
            _sensor(
                f"energy_exported_l{n}",
                p,
                attrgetter(f"{p}.energy_reverse"),
                ENERGY,
                translation_key="energy_exported_phase",
                phase=phase,
                enabled=False,
            ),
        ]
        if meter.detail(n) is not None:
            detail = f"detail_l{n}"
            line = LINES[n]
            sensors += [
                _sensor(
                    f"voltage_{line.lower().replace('-', '_')}",
                    detail,
                    attrgetter(f"{detail}.voltage_line_to_line"),
                    VOLTAGE,
                    translation_key="voltage_line",
                    phase=line,
                    enabled=False,
                ),
            ]
            if v109:
                sensors += [
                    _sensor(
                        f"power_factor_l{n}",
                        detail,
                        attrgetter(f"{detail}.power_factor"),
                        POWER_FACTOR,
                        translation_key="power_factor_phase",
                        phase=phase,
                        enabled=False,
                    ),
                ]
    return sensors


def sensor_descriptions(meter: Meter) -> list[VictronMeterSensorDescription]:
    """The sensors this meter serves."""
    if isinstance(meter, VictronEnergyMeter):
        return _victron(meter)
    return _carlo_gavazzi(meter)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VictronMeterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors of a Victron energy meter."""
    runtime_data = entry.runtime_data
    async_add_entities(
        _sensor_class(description)(runtime_data, description)
        for description in sensor_descriptions(runtime_data.meter)
    )


def _sensor_class(
    description: VictronMeterSensorDescription,
) -> type[VictronMeterSensor]:
    """A total keeps its last value across a restart and an offline meter."""
    if description.state_class is SensorStateClass.TOTAL_INCREASING:
        return VictronMeterTotalSensor
    return VictronMeterSensor


class VictronMeterSensor(VictronMeterEntity, SensorEntity):
    """A sensor on a Victron energy meter."""

    entity_description: VictronMeterSensorDescription

    def __init__(
        self,
        runtime_data: VictronMeterRuntimeData,
        description: VictronMeterSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(runtime_data, description)
        self._meter = runtime_data.meter

    @property
    @override
    def native_value(self) -> StateType:
        value = self.entity_description.value_fn(self._meter)
        if isinstance(value, IntEnum):
            return value.name.lower()
        return value


class VictronMeterTotalSensor(VictronMeterSensor, RestoreSensor):
    """An energy or hour counter.

    Long-term statistics need the value to persist, so the counter keeps its
    last reading while the meter is offline and across a restart.
    """

    _last: float | None = None

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (data := await self.async_get_last_sensor_data()) is None:
            return
        if isinstance(data.native_value, (int, float)):
            self._last = float(data.native_value)

    @property
    @override
    def available(self) -> bool:
        """Stay available with the last reading while the meter is offline."""
        return self._last is not None or super().available

    @property
    @override
    def native_value(self) -> StateType:
        if super().available:
            value = self.entity_description.value_fn(self._meter)
            if isinstance(value, (int, float)):
                self._last = float(value)
        return self._last
