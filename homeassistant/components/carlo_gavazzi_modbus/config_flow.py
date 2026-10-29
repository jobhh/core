"""Config flow to configure the Carlo Gavazzi Modbus integration."""

import asyncio
from collections.abc import Mapping
from typing import Any, override

from carlo_gavazzi_energy_meter_modbus import (
    Meter,
    UnsupportedMeterError,
    async_identify,
)
from modbus_connection import ModbusError, ModbusSerialParams
import probatio

from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SerialPortSelector,
    TextSelector,
)

from .const import (
    BAUDRATES,
    CONF_BAUDRATE,
    CONF_UNIT_ID,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    DETECT_TIMEOUT,
    DOMAIN,
    SEARCH_TIMEOUT,
    TYPE_GATEWAY,
    TYPE_SERIAL,
)
from .entity import meter_name
from .helpers import async_setup_meter, create_modbus_params

SECTION_MORE_OPTIONS = "more_options"

# A meter on a bus of its own keeps the factory-default address, so that
# setting is tucked away in a collapsed section.
MORE_OPTIONS = {
    probatio.Required(SECTION_MORE_OPTIONS): section(
        probatio.Schema(
            {
                probatio.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): probatio.All(
                    NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=247, step=1, mode=NumberSelectorMode.BOX
                        )
                    ),
                    probatio.Coerce(int),
                ),
            }
        ),
        {"collapsed": True},
    )
}

# The rates the meters offer, with room to type another for a bus that runs
# at one of its own.
BAUDRATE_FIELD = {
    probatio.Required(CONF_BAUDRATE, default=str(DEFAULT_BAUDRATE)): probatio.All(
        SelectSelector(
            SelectSelectorConfig(
                options=[str(rate) for rate in BAUDRATES],
                mode=SelectSelectorMode.DROPDOWN,
                custom_value=True,
            )
        ),
        probatio.Coerce(int),
        probatio.Range(min=1200),
    ),
}

# Setting up asks for the port first, then for the baud rate, filled in with
# the one the meter answers at.
STEP_SERIAL_PORT = probatio.Schema(
    {probatio.Required(CONF_DEVICE): SerialPortSelector(), **MORE_OPTIONS}
)
STEP_SERIAL_BAUDRATE = probatio.Schema(BAUDRATE_FIELD)

STEP_SERIAL = probatio.Schema(
    {
        probatio.Required(CONF_DEVICE): SerialPortSelector(),
        **BAUDRATE_FIELD,
        **MORE_OPTIONS,
    }
)

STEP_GATEWAY = probatio.Schema(
    {
        probatio.Required(CONF_HOST): TextSelector(),
        probatio.Required(CONF_PORT, default=DEFAULT_PORT): probatio.All(
            NumberSelector(
                NumberSelectorConfig(
                    min=1, max=65535, step=1, mode=NumberSelectorMode.BOX
                )
            ),
            probatio.Coerce(int),
        ),
        **MORE_OPTIONS,
    }
)

SCHEMAS = {TYPE_SERIAL: STEP_SERIAL, TYPE_GATEWAY: STEP_GATEWAY}


def _flatten(connection_type: str, user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten the sectioned form input into config entry data."""
    data = {CONF_TYPE: connection_type, **user_input}
    data[CONF_UNIT_ID] = data.pop(SECTION_MORE_OPTIONS)[CONF_UNIT_ID]

    if connection_type == TYPE_GATEWAY:
        # One connection is shared per host and port, so spelling matters.
        data[CONF_HOST] = data[CONF_HOST].lower()

    return data


def _sectioned(data: Mapping[str, Any]) -> dict[str, Any]:
    """Shape config entry data back into the sectioned form input."""
    sectioned = {
        key: value
        for key, value in data.items()
        if key not in (CONF_TYPE, CONF_UNIT_ID)
    }
    # The baud rate is picked from a list of strings.
    if CONF_BAUDRATE in sectioned:
        sectioned[CONF_BAUDRATE] = str(sectioned[CONF_BAUDRATE])
    sectioned[SECTION_MORE_OPTIONS] = {CONF_UNIT_ID: data[CONF_UNIT_ID]}
    return sectioned


async def _async_answers(
    hass: HomeAssistant, params: ModbusSerialParams, unit_id: int, timeout: float
) -> bool:
    """Return whether a device answers a read of the model code.

    A device that answers with a code no supported meter has still answered;
    the step after reports what it is. A port that another entry polls only
    opens at that entry's rate, which is the bus's rate; any other is refused.
    """
    try:
        async with async_get_temporary_unit(hass, params, unit_id) as unit:
            unit.require_timeout(timeout)
            await async_identify(unit)
    except UnsupportedMeterError:
        return True
    except HomeAssistantError, ModbusError:
        return False
    return True


async def _async_detect_baudrate(
    hass: HomeAssistant, device: str, unit_id: int
) -> int | None:
    """Return the listed baud rate a device answers at on a port, if any.

    The meter keeps its baud rate in a register, which can only be read at
    that rate, so each rate the meters offer is tried.
    """
    for rate in BAUDRATES:
        params = ModbusSerialParams(device=device, baudrate=rate)
        if await _async_answers(hass, params, unit_id, DETECT_TIMEOUT):
            return rate
    return None


def _needs_relink(entry: ConfigEntry, data: Mapping[str, Any]) -> bool:
    """Whether probing these settings clashes with the connection in use.

    Everything on one serial port shares a single connection, which cannot run
    at two baud rates at once. Changing the baud rate of the port an entry is
    polling needs that entry off the bus before the new rate can be probed.

    An entry waiting to retry counts as being on the bus: the retry would set
    it up at its old rate while the probe runs at the new one. Unloading it
    cancels that.
    """
    if entry.state not in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_RETRY):
        return False

    current = create_modbus_params(entry.data)
    new = create_modbus_params(data)

    return new.endpoint == current.endpoint and new != current


class CarloGavazziModbusFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a Carlo Gavazzi Modbus config flow."""

    VERSION = 1

    # What the form's errors name, such as the model code of a device that
    # answers but is not a supported meter.
    _placeholders: dict[str, str]

    # The serial port picked in the first step, and the baud rate the meter
    # answered at there.
    _port: dict[str, Any]
    _detected: int | None

    # Searching every address at every rate, for a meter whose address changed.
    _search: asyncio.Task[tuple[int, int] | None] | None = None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick how the meter's RS485 bus is reached."""
        return self.async_show_menu(
            step_id="user", menu_options=[TYPE_SERIAL, TYPE_GATEWAY]
        )

    async def async_step_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which serial port the meter is on, then look for its baud rate."""
        if user_input is None:
            return self.async_show_form(
                step_id=TYPE_SERIAL, data_schema=STEP_SERIAL_PORT
            )

        self._port = user_input
        self._detected = await _async_detect_baudrate(
            self.hass,
            user_input[CONF_DEVICE],
            user_input[SECTION_MORE_OPTIONS][CONF_UNIT_ID],
        )
        if self._detected is None:
            return await self.async_step_serial_not_found()
        return await self.async_step_serial_baudrate()

    async def async_step_serial_not_found(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to search every address, or to enter the baud rate."""
        return self.async_show_menu(
            step_id="serial_not_found",
            menu_options=["serial_search", "serial_baudrate_unknown"],
            description_placeholders={
                "unit_id": str(self._port[SECTION_MORE_OPTIONS][CONF_UNIT_ID])
            },
        )

    async def async_step_serial_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search every address at every rate, showing how far it got."""
        if self._search is None:
            # Not started eagerly: a port refused at every rate finishes the
            # search at once, and the progress has to be shown first.
            self._search = self.hass.async_create_task(
                self._async_search(), eager_start=False
            )
        if not self._search.done():
            return self.async_show_progress(
                step_id="serial_search",
                progress_action="search",
                progress_task=self._search,
            )

        found = self._search.result()
        self._search = None
        if found is None:
            return self.async_show_progress_done(next_step_id="serial_search_failed")
        self._detected, unit_id = found
        self._port = {**self._port, SECTION_MORE_OPTIONS: {CONF_UNIT_ID: unit_id}}
        return self.async_show_progress_done(next_step_id="serial_baudrate")

    async def async_step_serial_search_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Give up: nothing answered at any address or rate."""
        return self.async_abort(reason="no_meter_found")

    async def _async_search(self) -> tuple[int, int] | None:
        """Return the first rate and address a device answers at.

        The address already tried at every rate is left out. Each rate's link
        is held open across the addresses, at the search's short timeout, so
        trying one is a single request rather than a new connection.
        """
        device = self._port[CONF_DEVICE]
        tried = self._port[SECTION_MORE_OPTIONS][CONF_UNIT_ID]
        addresses = [unit_id for unit_id in range(1, 248) if unit_id != tried]
        total = len(BAUDRATES) * len(addresses)
        done = 0
        for rate in BAUDRATES:
            params = ModbusSerialParams(device=device, baudrate=rate)
            try:
                async with async_get_temporary_unit(self.hass, params, tried) as hold:
                    hold.require_timeout(SEARCH_TIMEOUT)
                    for unit_id in addresses:
                        if await _async_answers(
                            self.hass, params, unit_id, SEARCH_TIMEOUT
                        ):
                            return rate, unit_id
                        done += 1
                        self.async_update_progress(done / total)
            except HomeAssistantError:
                # In use at another rate, which is the bus's.
                done += len(addresses)
        return None

    async def async_step_serial_baudrate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the baud rate, filled in with the one the meter answered at."""
        return await self._async_step_baudrate("serial_baudrate", user_input)

    async def async_step_serial_baudrate_unknown(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the baud rate when the meter answered at none of them."""
        return await self._async_step_baudrate("serial_baudrate_unknown", user_input)

    async def _async_step_baudrate(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Ask for the baud rate, saying how the one filled in was found.

        The form names the address rather than the port: an ESPHome serial
        proxy's port carries its encryption key.
        """
        placeholders = {
            "baudrate": str(self._detected or DEFAULT_BAUDRATE),
            "unit_id": str(self._port[SECTION_MORE_OPTIONS][CONF_UNIT_ID]),
        }
        if user_input is not None:
            return await self._async_step_link(
                TYPE_SERIAL,
                step_id,
                STEP_SERIAL_BAUDRATE,
                {**self._port, **user_input},
                placeholders=placeholders,
            )
        return await self._async_step_link(
            TYPE_SERIAL,
            step_id,
            STEP_SERIAL_BAUDRATE,
            None,
            suggested_values={CONF_BAUDRATE: placeholders["baudrate"]},
            placeholders=placeholders,
        )

    async def async_step_gateway(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a meter behind an RS485-to-TCP gateway in transparent mode."""
        return await self._async_step_link(
            TYPE_GATEWAY, TYPE_GATEWAY, STEP_GATEWAY, user_input
        )

    async def _async_step_link(
        self,
        connection_type: str,
        step_id: str,
        schema: probatio.Schema,
        user_input: dict[str, Any] | None,
        *,
        suggested_values: Mapping[str, Any] | None = None,
        placeholders: Mapping[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Ask for the link settings, then probe the meter behind them."""
        errors: dict[str, str] = {}
        self._placeholders = dict(placeholders or {})

        if user_input is not None:
            data = _flatten(connection_type, user_input)
            errors, meter = await self._async_validate(data)
            if meter is not None:
                await self.async_set_unique_id(meter.serial_number)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=meter_name(meter), data=data)
            suggested_values = user_input

        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested_values),
            errors=errors,
            description_placeholders=self._placeholders,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of how the meter is reached.

        The meter may move to another port, baud rate or address, but it must
        stay the same meter: the probed serial number has to match the entry.
        """
        errors: dict[str, str] = {}
        self._placeholders = {}
        entry = self._get_reconfigure_entry()
        connection_type = entry.data[CONF_TYPE]

        if user_input is not None:
            data = _flatten(connection_type, user_input)

            relinking = False
            if _needs_relink(entry, data):
                # A failed unload leaves the entry loaded; leave it be then and
                # let the probe report whatever it runs into.
                relinking = await self.hass.config_entries.async_unload(entry.entry_id)

            errors, meter = await self._async_validate(data)

            if meter is not None:
                await self.async_set_unique_id(meter.serial_number)

            # Anything other than the meter this entry is for leaves it off the
            # bus, so put it back before reporting what happened. A match falls
            # through: the reload below brings it up on the new settings.
            if relinking and self.unique_id != entry.unique_id:
                await self.hass.config_entries.async_setup(entry.entry_id)

            if meter is not None:
                self._abort_if_unique_id_mismatch(reason="wrong_meter")
                return self.async_update_reload_and_abort(entry, data_updates=data)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMAS[connection_type], user_input or _sectioned(entry.data)
            ),
            errors=errors,
            description_placeholders=self._placeholders,
        )

    async def _async_validate(
        self, data: dict[str, Any]
    ) -> tuple[dict[str, str], Meter | None]:
        """Probe the meter, returning form errors and the set-up meter."""
        try:
            async with async_get_temporary_unit(
                self.hass, create_modbus_params(data), data[CONF_UNIT_ID]
            ) as unit:
                meter = await async_setup_meter(unit)
        except HomeAssistantError, ModbusError:
            # HomeAssistantError: the port is already in use at other line
            # settings, which one connection cannot honour.
            return {"base": "cannot_connect"}, None
        except UnsupportedMeterError as err:
            self._placeholders["code"] = str(err.code)
            return {"base": "unsupported_meter"}, None

        if not meter.serial_number:
            return {"base": "no_serial_number"}, None

        return {}, meter
