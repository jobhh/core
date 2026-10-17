"""Decoding a Victron energy meter over the mock backend."""

from __future__ import annotations

import pytest
from modbus_connection import IllegalDataAddressError, ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit, ReadEvent

from victron_energy_meter import (
    Capability,
    FirmwareVersion,
    PhaseConfiguration,
    PhaseRotationAlarm,
    PhaseSequence,
    Position,
    ProductId,
    Role,
    UnsupportedFirmwareError,
    UnsupportedMeterError,
    VictronEnergyMeter,
    async_identify,
)

from .conftest import SERIAL, VM_3P75CT, flatten, int16, seed, words

# The register blocks the meter serves. A read must stay inside one.
BLOCKS = ((0x1000, 0x100B), (0x2000, 0x2025), (0x3000, 0x303F), (0x3040, 0x305F))


async def test_setup_identifies_the_meter(meter: VictronEnergyMeter) -> None:
    await meter.async_ensure_setup()

    assert meter.model is not None
    assert meter.model.product_id is ProductId.VM_3P75CT
    assert meter.model.name == "VM-3P75CT"
    assert meter.serial_number == SERIAL
    assert str(meter.firmware_version) == "v1.09"
    assert meter.identity.hardware_version == 3
    assert meter.phases == (1, 2, 3)


async def test_configuration(meter: VictronEnergyMeter) -> None:
    await meter.async_update()
    c = meter.configuration

    assert c.phase_configuration is PhaseConfiguration.THREE_PHASE
    assert c.role is Role.GRID
    assert c.description == "Grid meter"
    assert c.position is Position.AC_INPUT_1
    assert c.system_instance == 1
    assert c.capabilities is not None
    assert Capability.UDP_PQ_SNAPSHOTS in c.capabilities


async def test_totals(meter: VictronEnergyMeter) -> None:
    report = await meter.async_update()
    t = meter.totals

    assert report.complete, report.failed
    assert t.active_power == 1050
    assert t.frequency == 50.01
    assert t.frequency_precise == 50.012
    assert t.pe_n_voltage == 0.12
    assert t.energy_forward == 21345.67
    assert t.energy_reverse == 1234.56
    assert t.error_code == 0
    assert t.neutral_current == 0.45
    assert t.power_factor == 0.625
    assert t.phase_sequence is PhaseSequence.L1_L2_L3
    assert t.phase_rotation_alarm is PhaseRotationAlarm.OK


async def test_phases(meter: VictronEnergyMeter) -> None:
    await meter.async_update()

    l1, l2, l3 = (meter.phase(n) for n in (1, 2, 3))
    assert l1 is not None and l2 is not None and l3 is not None
    assert (l1.voltage, l2.voltage, l3.voltage) == (230.12, 231.2, 229.8)
    assert (meter.current(1), meter.current(2), meter.current(3)) == (5.43, -1.23, 0.57)
    assert (l1.active_power, l2.active_power, l3.active_power) == (1200, -250, 100)
    assert (l1.apparent_power, l2.apparent_power, l3.apparent_power) == (1250, 300, 130)
    assert (l1.energy_forward, l2.energy_forward, l3.energy_forward) == (
        12345.67,
        5000.0,
        4000.0,
    )
    assert l1.energy_reverse == 234.56

    d1, d2, d3 = (meter.detail(n) for n in (1, 2, 3))
    assert d1 is not None and d2 is not None and d3 is not None
    assert (d1.voltage_line_to_line, d2.voltage_line_to_line) == (398.5, 400.1)
    assert d3.voltage_line_to_line == 397.9
    assert (d1.power_factor, d2.power_factor, d3.power_factor) == (0.96, -0.834, 0.767)


async def test_phase_powers_add_up(meter: VictronEnergyMeter) -> None:
    await meter.async_update()

    powers = [phase.active_power for n in (1, 2, 3) if (phase := meter.phase(n))]
    assert None not in powers
    assert sum(p for p in powers if p is not None) == meter.totals.active_power


async def test_reads_stay_inside_one_block(
    meter: VictronEnergyMeter, vm_3p75ct: MockModbusUnit
) -> None:
    await meter.async_update()
    await meter.async_read_raw()

    assert vm_3p75ct.read_events
    for event in vm_3p75ct.read_events:
        assert event.register_type == "holding"
        last = event.address + event.count - 1
        assert any(lo <= event.address and last <= hi for lo, hi in BLOCKS), event


async def test_invalid_values_decode_to_none(
    meter: VictronEnergyMeter, vm_3p75ct: MockModbusUnit
) -> None:
    vm_3p75ct.holding.update(
        flatten(
            {
                0x3000: 0x7FFF,
                0x3002: [0x7FFF, 0xFFFF],
                0x3006: [0xFFFF, 0xFFFF],
                0x303B: 0xFF,
                0x303E: 0,
            }
        )
    )
    await meter.async_update()
    l1 = meter.phase(1)
    assert l1 is not None

    assert l1.voltage is None
    assert l1.active_power is None
    assert l1.energy_forward is None
    assert meter.totals.phase_sequence is None
    assert meter.totals.frequency_precise is None


async def test_vm_3p5a_reads_the_high_range_currents(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    seed(mock_modbus_unit)
    mock_modbus_unit.holding.update(
        flatten(
            {
                0x1000: 0xA1B2,
                0x3001: 0,  # reserved on the VM-3P5A
                0x3058: words(3_250, 2),  # 32.50 A
                0x305A: words(-1_000, 2),  # -10.00 A
                0x305C: words(5, 2),  # 0.05 A
            }
        )
    )
    meter = VictronEnergyMeter(mock_modbus_unit)
    report = await meter.async_update()

    assert report.complete, report.failed
    assert meter.model is not None and meter.model.name == "VM-3P5A"
    assert (meter.current(1), meter.current(2), meter.current(3)) == (32.5, -10.0, 0.05)
    l1 = meter.phase(1)
    assert l1 is not None and l1.current is None  # never read on this model


@pytest.mark.parametrize(
    ("configuration", "phase"),
    [
        (PhaseConfiguration.SINGLE_PHASE_L1, 1),
        (PhaseConfiguration.SINGLE_PHASE_L2, 2),
        (PhaseConfiguration.SINGLE_PHASE_L3, 3),
    ],
)
async def test_single_phase_meter_polls_only_its_phase(
    mock_modbus_unit: MockModbusUnit, configuration: PhaseConfiguration, phase: int
) -> None:
    seed(mock_modbus_unit)
    mock_modbus_unit.holding[0x2000] = configuration
    meter = VictronEnergyMeter(mock_modbus_unit)
    await meter.async_update()

    assert meter.phases == (phase,)
    for other in {1, 2, 3} - {phase}:
        assert meter.phase(other) is None
    measured = meter.phase(phase)
    assert measured is not None and measured.voltage is not None


async def test_split_phase_meter(mock_modbus_unit: MockModbusUnit) -> None:
    seed(mock_modbus_unit)
    mock_modbus_unit.holding[0x2000] = PhaseConfiguration.SPLIT_PHASE
    meter = VictronEnergyMeter(mock_modbus_unit)
    await meter.async_update()

    assert meter.phases == (1, 2)
    assert meter.phase(3) is None


async def test_a_changed_phase_configuration_is_reported(
    meter: VictronEnergyMeter, vm_3p75ct: MockModbusUnit
) -> None:
    await meter.async_update()
    assert meter.configuration_changed is False

    vm_3p75ct.holding[0x2000] = PhaseConfiguration.SINGLE_PHASE_L1
    await meter.async_update_settings()

    assert meter.configuration_changed is True


async def test_firmware_before_v107_skips_newer_registers(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    seed(mock_modbus_unit)
    mock_modbus_unit.holding.update({0x1009: 0x0001, 0x100A: 0x05FF})  # v1.05
    meter = VictronEnergyMeter(mock_modbus_unit)
    report = await meter.async_update()

    assert report.complete
    assert meter.detail(1) is None
    assert meter.totals.neutral_current is None
    assert meter.totals.power_factor is None
    assert meter.totals.phase_rotation_alarm is None
    assert meter.configuration.capabilities is None
    assert meter.totals.energy_forward == 21345.67


async def test_firmware_v107_reads_line_voltage_but_not_power_factor(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    seed(mock_modbus_unit)
    mock_modbus_unit.holding.update({0x1009: 0x0001, 0x100A: 0x07FF})  # v1.07
    meter = VictronEnergyMeter(mock_modbus_unit)
    await meter.async_update()
    d1 = meter.detail(1)

    assert d1 is not None
    assert d1.voltage_line_to_line == 398.5
    assert d1.power_factor is None
    assert meter.totals.neutral_current == 0.45
    assert meter.totals.power_factor is None


async def test_firmware_without_measurements_is_refused(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    seed(mock_modbus_unit)
    mock_modbus_unit.holding.update({0x1009: 0x0001, 0x100A: 0x0301})  # v1.03 beta 1
    meter = VictronEnergyMeter(mock_modbus_unit)
    await meter.async_ensure_setup()  # beta 1 of v1.03 is the first that serves data

    mock_modbus_unit.holding.update({0x1009: 0x0001, 0x100A: 0x0300})
    with pytest.raises(UnsupportedFirmwareError):
        await VictronEnergyMeter(mock_modbus_unit).async_ensure_setup()


async def test_unknown_product_is_rejected(mock_modbus_unit: MockModbusUnit) -> None:
    seed(mock_modbus_unit)
    mock_modbus_unit.holding[0x1000] = 0xA1FF

    with pytest.raises(UnsupportedMeterError) as err:
        await VictronEnergyMeter(mock_modbus_unit).async_ensure_setup()
    assert err.value.product_id == 0xA1FF

    with pytest.raises(UnsupportedMeterError):
        await async_identify(mock_modbus_unit)


async def test_async_identify_costs_one_read(vm_3p75ct: MockModbusUnit) -> None:
    model = await async_identify(vm_3p75ct)

    assert model.product_id is ProductId.VM_3P75CT
    assert vm_3p75ct.read_events == [ReadEvent("holding", 0x1000, 1)]


async def test_a_lost_datagram_surfaces_as_a_timeout(
    meter: VictronEnergyMeter, vm_3p75ct: MockModbusUnit
) -> None:
    await meter.async_ensure_setup()
    vm_3p75ct.fail_requests(ModbusTimeoutError())

    with pytest.raises(ModbusTimeoutError):
        await meter.async_update_readings()

    vm_3p75ct.fail_requests(None)
    assert (await meter.async_update_readings()).complete


async def test_a_refused_block_leaves_the_others_updated(
    meter: VictronEnergyMeter, vm_3p75ct: MockModbusUnit
) -> None:
    await meter.async_ensure_setup()
    vm_3p75ct.fail_read(0x3046, IllegalDataAddressError())

    report = await meter.async_update_readings()

    assert set(report.failed) == {"detail_l1"}
    assert meter.totals.active_power == 1050


def test_firmware_version_formatting_and_order() -> None:
    release = FirmwareVersion.from_words(0x0001, 0x10FF)
    beta = FirmwareVersion.from_words(0x0001, 0x1002)

    assert str(release) == "v1.10"
    assert str(beta) == "v1.10-beta-02"
    assert beta < release
    assert release.at_least(1, 9)
    assert not FirmwareVersion.from_words(0x0001, 0x08FF).at_least(1, 9)


def test_snapshot_is_consistent() -> None:
    # The snapshot's own arithmetic, so the fixtures cannot drift silently.
    assert int16(-1) == 0xFFFF
    assert VM_3P75CT[0x1000] == 0xA1B1
