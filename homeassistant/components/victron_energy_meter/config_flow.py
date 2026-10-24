"""Config flow for the Victron Energy Meter integration."""

from collections.abc import Mapping
from typing import Any, override

from carlo_gavazzi_energy_meter_modbus import (
    UnsupportedMeterError as CarloGavazziUnsupported,
)
from modbus_connection import ModbusError
import probatio
from victron_energy_meter_modbus import (
    UnsupportedFirmwareError,
    UnsupportedMeterError as VictronUnsupported,
)

from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT, CONF_TYPE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SerialPortSelector,
    TextSelector,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_BAUDRATE,
    CONF_UNIT_ID,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    DOMAIN,
    LinkType,
)
from .helpers import Meter, async_setup_meter, create_modbus_params, meter_name, unit_id

UNIT_ID_SELECTOR = probatio.All(
    NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX, min=1, max=247)),
    probatio.Coerce(int),
)

SCHEMAS: dict[LinkType, probatio.Schema] = {
    LinkType.NETWORK: probatio.Schema({probatio.Required(CONF_HOST): TextSelector()}),
    LinkType.SERIAL: probatio.Schema(
        {
            probatio.Required(CONF_DEVICE): SerialPortSelector(),
            probatio.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): probatio.All(
                NumberSelector(
                    NumberSelectorConfig(mode=NumberSelectorMode.BOX, min=1200)
                ),
                probatio.Coerce(int),
            ),
            probatio.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): UNIT_ID_SELECTOR,
        }
    ),
    LinkType.GATEWAY: probatio.Schema(
        {
            probatio.Required(CONF_HOST): TextSelector(),
            probatio.Required(CONF_PORT, default=DEFAULT_PORT): probatio.All(
                NumberSelector(
                    NumberSelectorConfig(mode=NumberSelectorMode.BOX, min=1, max=65535)
                ),
                probatio.Coerce(int),
            ),
            probatio.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): UNIT_ID_SELECTOR,
        }
    ),
}


class VictronEnergyMeterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Victron energy meter."""

    VERSION = 1

    _discovered: dict[str, Any]
    _discovered_name: str

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick how the meter is reached."""
        return self.async_show_menu(step_id="user", menu_options=list(LinkType))

    async def async_step_network(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a VM-3P75CT or VM-3P5A on the network."""
        return await self._async_step_link(LinkType.NETWORK, user_input)

    async def async_step_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a Carlo Gavazzi meter on a serial port or ESPHome serial proxy."""
        return await self._async_step_link(LinkType.SERIAL, user_input)

    async def async_step_gateway(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a Carlo Gavazzi meter behind an RS485-to-TCP gateway."""
        return await self._async_step_link(LinkType.GATEWAY, user_input)

    async def _async_step_link(
        self, link: LinkType, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Ask for the link settings, then probe the meter behind them."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_TYPE: link, **user_input}
            meter, errors, placeholders = await self._async_probe(data)
            if meter is not None:
                await self.async_set_unique_id(meter.serial_number)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=meter_name(meter), data=data)

        return self.async_show_form(
            step_id=link,
            data_schema=self.add_suggested_values_to_schema(
                SCHEMAS[link], user_input or {}
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    @override
    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a Victron meter announcing itself over mDNS."""
        data = {CONF_TYPE: LinkType.NETWORK, CONF_HOST: discovery_info.host}
        meter, errors, _ = await self._async_probe(data)
        if meter is None:
            return self.async_abort(reason=errors["base"])

        await self.async_set_unique_id(meter.serial_number)
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.host})
        self._discovered = data
        self._discovered_name = meter_name(meter)
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered meter."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_name, data=self._discovered
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": self._discovered_name,
                "host": self._discovered[CONF_HOST],
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change how an existing meter is reached."""
        entry = self._get_reconfigure_entry()
        link = LinkType(entry.data[CONF_TYPE])
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_TYPE: link, **user_input}
            meter, errors, placeholders = await self._async_probe(data)
            if meter is not None:
                await self.async_set_unique_id(meter.serial_number)
                self._abort_if_unique_id_mismatch(reason="wrong_meter")
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMAS[link], user_input or entry.data
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _async_probe(
        self, data: Mapping[str, Any]
    ) -> tuple[Meter | None, dict[str, str], dict[str, str]]:
        """Identify the meter, or return the error to show instead."""
        params = create_modbus_params(data)
        try:
            async with async_get_temporary_unit(
                self.hass, params, unit_id(data)
            ) as unit:
                meter = await async_setup_meter(data, unit)
        except (ModbusError, HomeAssistantError) as err:
            return (
                None,
                {"base": "cannot_connect"},
                {"error": str(err) or type(err).__name__},
            )
        except CarloGavazziUnsupported, VictronUnsupported:
            return None, {"base": "unsupported_meter"}, {}
        except UnsupportedFirmwareError:
            return None, {"base": "unsupported_firmware"}, {}
        if not meter.serial_number:
            return None, {"base": "no_serial_number"}, {}
        return meter, {}, {}
