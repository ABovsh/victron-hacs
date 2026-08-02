"""Config flow for victron_ble integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_last_service_info,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from victron_ble.exceptions import AdvertisementKeyMismatchError

from .const import CONF_THROTTLE_SECONDS, DOMAIN, UPDATE_THROTTLE_SECONDS

_LOGGER = logging.getLogger(__name__)

# Victron Instant Readout advertisements are AES-128, so the advertisement key
# is exactly 16 bytes written as 32 hex characters.
KEY_LENGTH_BYTES = 16


class InvalidKey(HomeAssistantError):
    """The advertisement key is not a 16-byte hex string."""


def validate_key(key: str) -> str:
    """Return the normalised advertisement key, or raise InvalidKey.

    Without this the flow happily accepts any string; the device is then created
    and every advertisement fails to decrypt, so the user gets a configured
    device with no entities and nothing in the log explaining why.
    """
    normalised = key.strip().lower().replace(" ", "")
    try:
        raw = bytes.fromhex(normalised)
    except ValueError as err:
        raise InvalidKey("advertisement key is not hexadecimal") from err
    if len(raw) != KEY_LENGTH_BYTES:
        raise InvalidKey(
            f"advertisement key is {len(raw)} bytes, expected {KEY_LENGTH_BYTES}"
        )
    return normalised


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for victron_ble."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle a flow initialized by bluetooth discovery."""
        _LOGGER.debug(discovery_info)
        self.context["discovery_info"] = {
            "name": discovery_info.name,
            "address": discovery_info.address,
        }
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        return await self.async_step_user()

    def _check_key_against_live_advertisement(self, address: str, key: str) -> bool:
        """Return False only if a live advertisement proves the key is wrong.

        Victron puts a key-check byte in every advertisement, so when the device
        is currently in range a wrong-but-well-formed key can be caught here
        instead of silently producing an entity-less device. Absence of an
        advertisement is not evidence of anything, so it passes.
        """
        service_info = async_last_service_info(self.hass, address, connectable=False)
        if service_info is None:
            return True
        # Imported lazily: device.py pulls in the whole victron_ble device tree.
        from .device import VictronBluetoothDeviceData

        try:
            VictronBluetoothDeviceData(key).update(service_info)
        except AdvertisementKeyMismatchError:
            return False
        except Exception:  # noqa: BLE001 - any other parse failure is not a key verdict
            _LOGGER.debug("Could not verify key against advertisement", exc_info=True)
        return True

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """User setup."""
        errors: dict[str, str] = {}
        name = None
        address = None
        discovery_info = self.context.get("discovery_info")
        if discovery_info:
            name = discovery_info["name"]
            address = discovery_info["address"]

        if user_input is not None:
            name = user_input["name"]
            address = user_input["address"]
            try:
                key = validate_key(user_input["key"])
            except InvalidKey:
                errors["key"] = "invalid_key"
            else:
                if not self._check_key_against_live_advertisement(address, key):
                    errors["key"] = "key_mismatch"
                else:
                    await self.async_set_unique_id(address)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=name,
                        data={"name": name, "address": address, "key": key},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=name): str,
                    vol.Required("address", default=address): str,
                    vol.Required("key"): str,
                }
            ),
            errors=errors or None,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Change the advertisement key without deleting the device.

        VictronConnect issues a new key whenever Instant Readout is re-paired.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                key = validate_key(user_input["key"])
            except InvalidKey:
                errors["key"] = "invalid_key"
            else:
                if not self._check_key_against_live_advertisement(
                    entry.data["address"], key
                ):
                    errors["key"] = "key_mismatch"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data={**entry.data, "key": key}
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required("key"): str}),
            errors=errors or None,
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Let the throttle interval be tuned per device."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_THROTTLE_SECONDS, UPDATE_THROTTLE_SECONDS
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_THROTTLE_SECONDS, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=0, max=3600)
                    ),
                }
            ),
        )
