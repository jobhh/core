"""Config flow to configure the Carlo Gavazzi Modbus integration."""

from collections.abc import Mapping
from typing import Any, override

from carlo_gavazzi_energy_meter_modbus import EM500Meter, UnsupportedMeterError
from modbus_connection import ModbusError
import probatio

from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_DEVICE, CONF_TYPE
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SerialPortSelector,
)

from .const import (
    CONF_BAUDRATE,
    CONF_UNIT_ID,
    DEFAULT_BAUDRATE,
    DEFAULT_UNIT_ID,
    DOMAIN,
    TYPE_SERIAL,
)
from .entity import meter_name
from .helpers import create_modbus_params

SECTION_MORE_OPTIONS = "more_options"

# A meter on a bus of its own keeps the factory-default address, so that
# setting is tucked away in a collapsed section.
STEP_USER = probatio.Schema(
    {
        probatio.Required(CONF_DEVICE): SerialPortSelector(),
        probatio.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): probatio.All(
            NumberSelector(
                NumberSelectorConfig(min=1200, step=1, mode=NumberSelectorMode.BOX)
            ),
            probatio.Coerce(int),
        ),
        probatio.Required(SECTION_MORE_OPTIONS): section(
            probatio.Schema(
                {
                    probatio.Required(
                        CONF_UNIT_ID, default=DEFAULT_UNIT_ID
                    ): probatio.All(
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
        ),
    }
)


def _flatten(user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten the sectioned form input into config entry data."""
    data = {CONF_TYPE: TYPE_SERIAL, **user_input}
    data[CONF_UNIT_ID] = data.pop(SECTION_MORE_OPTIONS)[CONF_UNIT_ID]
    return data


def _sectioned(data: Mapping[str, Any]) -> dict[str, Any]:
    """Shape config entry data back into the sectioned form input."""
    return {
        CONF_DEVICE: data[CONF_DEVICE],
        CONF_BAUDRATE: data[CONF_BAUDRATE],
        SECTION_MORE_OPTIONS: {CONF_UNIT_ID: data[CONF_UNIT_ID]},
    }


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

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the serial port settings, then probe the meter on it."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _flatten(user_input)
            errors, meter = await self._async_validate(data)
            if meter is not None:
                await self.async_set_unique_id(meter.serial_number)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=meter_name(meter), data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of how the meter is reached.

        The meter may move to another port, baud rate or address, but it must
        stay the same meter: the probed serial number has to match the entry.
        """
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            data = _flatten(user_input)

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
                STEP_USER, user_input or _sectioned(entry.data)
            ),
            errors=errors,
        )

    async def _async_validate(
        self, data: dict[str, Any]
    ) -> tuple[dict[str, str], EM500Meter | None]:
        """Probe the meter, returning form errors and the set-up meter."""
        try:
            async with async_get_temporary_unit(
                self.hass, create_modbus_params(data), data[CONF_UNIT_ID]
            ) as unit:
                meter = EM500Meter(unit)
                await meter.async_ensure_setup()
        except HomeAssistantError, ModbusError:
            # HomeAssistantError: the port is already in use at other line
            # settings, which one connection cannot honour.
            return {"base": "cannot_connect"}, None
        except UnsupportedMeterError:
            return {"base": "unsupported_meter"}, None

        if not meter.serial_number:
            return {"base": "no_serial_number"}, None

        return {}, meter
