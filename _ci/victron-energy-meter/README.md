# victron-energy-meter

Read Victron Energy's own energy meters over Modbus, as typed Python objects.

The library covers the **VM-3P75CT** (current transformers) and the
**VM-3P5A** (direct connection). These meters speak Modbus over UDP on port
502, as unit 1, and announce themselves over mDNS as
`_victron-energy-meter._udp`.

For the Carlo Gavazzi meters Victron also sells (EM540, ET112, ET340, EM24),
see [carlo-gavazzi-modbus](https://github.com/jobhh/carlo-gavazzi-modbus).

It is built on
[modbus-connection](https://github.com/home-assistant-libs/modbus-connection).
The library never opens a connection. You hand it a `ModbusUnit`, and it reads
registers through that unit.

## Install

```bash
pip install victron-energy-meter
```

## Example

```python
import asyncio

from modbus_connection import ModbusUdpParams
from modbus_connection.tmodbus import ModbusConnection

from victron_energy_meter import PORT, UNIT_ID, VictronEnergyMeter


async def main() -> None:
    connection = ModbusConnection(ModbusUdpParams(host="192.168.1.70", port=PORT))
    try:
        meter = VictronEnergyMeter(connection.for_unit(UNIT_ID))
        await meter.async_update()

        print(meter.model.name, meter.serial_number, meter.firmware_version)
        print("Power:", meter.totals.active_power, "W")
        print("Imported:", meter.totals.energy_forward, "kWh")
        for n in meter.phases:
            print(f"L{n}:", meter.phase(n).voltage, "V", meter.current(n), "A")
    finally:
        await connection.close()


asyncio.run(main())
```

## What it reads

| Attribute | Contents |
| --- | --- |
| `identity` | Product id, serial number, firmware and hardware version. Read once, at setup. |
| `configuration` | Phase configuration, role, description, position, system instance, capabilities. |
| `totals` | Total power, frequency, PE-N voltage, imported and exported energy, error code, neutral current, power factor, phase sequence, phase rotation alarm. |
| `phase(n)` | Voltage, current (VM-3P75CT), active and apparent power, imported and exported energy. |
| `detail(n)` | Line-to-line voltage and power factor. |
| `current(n)` | The phase current in A, from the register this model reports it in. |

Only the phases the meter is configured for are read. Setup also checks the
firmware: the line-to-line voltage and neutral current need v1.07, and the
power factor, phase sequence, alarms and capabilities need v1.09. Firmware
older than v1.03 reports no measurements and is refused.

`configuration_changed` turns true when the phase configuration changes after
setup. Build a new `VictronEnergyMeter` then.

## Notes on the meter

- Values are big endian, high word first.
- The meter refuses a read that crosses from one register block into the next.
  The library reads each block on its own.
- UDP can drop a request. A lost request surfaces as `ModbusTimeoutError`.
- The register map follows the Modbus appendix of the VM-3P5A manual, checked
  against Victron's open-source GX driver
  ([dbus-modbus-client](https://github.com/victronenergy/dbus-modbus-client)).
  The two disagree on the neutral current: the manual gives 0.01 A, the driver
  divides by 10. This library follows the manual until a real meter settles it.

## Checking a real meter

```bash
uv run script/query.py 192.168.1.70 --dump vm-3p75ct.json
```

The script only reads. It prints every value and can save the raw registers.

## Develop

```bash
uv sync
uv run pytest
uv run ruff format --check . && uv run ruff check . && uv run mypy
```

## License

Apache License 2.0. This project is not affiliated with Victron Energy.
