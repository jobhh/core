#!/usr/bin/env python3

"""Query a Victron VM-3P75CT or VM-3P5A once and print every value.

Everything this script does is a read. The meter accepts nothing else.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from modbus_connection import ModbusError
from modbus_connection.cli_helper import (
    CountingUnit,
    add_connection_args,
    connect_from_args,
    print_component,
)

from victron_energy_meter import UNIT_ID, VictronEnergyMeter
from victron_energy_meter.device import ALL

# The meter speaks Modbus over UDP with the standard MBAP framing.
CONNECTIONS = (("udp", "socket"),)

EXAMPLES = """examples:
  python script/query.py 192.168.1.70 --dump vm-3p75ct.json
"""


async def main() -> int:
    """Read one meter, print it, and optionally save a dump."""
    logging.getLogger().addHandler(logging.NullHandler())

    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_connection_args(parser, connections=CONNECTIONS)
    parser.add_argument(
        "--dump",
        type=Path,
        metavar="FILE",
        help="save the raw registers to FILE, as JSON",
    )
    args = parser.parse_args()

    try:
        connection = await connect_from_args(args)
    except ModbusError as err:
        print(f"Could not connect to {args.target}: {str(err) or type(err).__name__}")
        return 1

    counting = CountingUnit(connection.for_unit(UNIT_ID))
    meter = VictronEnergyMeter(counting)
    try:
        await meter.async_ensure_setup()
        setup_reads = counting.reads
        report = await meter.async_update()
        poll_reads = counting.reads - setup_reads
        raw = await meter.async_read_raw(ALL)
    except ModbusError as err:
        print(f"Could not read the meter: {str(err) or type(err).__name__}")
        return 1
    finally:
        await connection.close()

    model = meter.model
    assert model is not None  # setup succeeded
    print(f"Model          {model.name} ({model.product_id:#06x})")
    print(f"Serial number  {meter.serial_number}")
    print(f"Firmware       {meter.firmware_version}")
    print(f"Phases         {meter.phases}")
    for name in ALL:
        component = getattr(meter, name)
        if component is not None:
            print()
            print_component(component, title=name)
    if report.failed:
        print("\nFailed to read:")
        for name, error in report.failed.items():
            print(f"  {name}: {str(error) or type(error).__name__}")
    print(f"\n{setup_reads} reads to set up, {poll_reads} reads per poll")

    if args.dump is not None:
        dump = {
            "model": {"product_id": int(model.product_id), "name": model.name},
            "firmware": str(meter.firmware_version),
            "raw": raw,
        }
        args.dump.write_text(json.dumps(dump, indent=2) + "\n")
        print(f"Saved the dump to {args.dump}")
    return 0


raise SystemExit(asyncio.run(main()))
