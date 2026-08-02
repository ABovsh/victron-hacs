"""Test the victron_ble config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.victron_ble.const import DOMAIN


async def test_form(hass: HomeAssistant, mock_bluetooth: None) -> None:
    """Test we get the form.

    mock_bluetooth keeps the bluetooth integration from opening a real HCI
    socket, which no CI runner (and no dev sandbox) has.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] is None

    with patch(
        "custom_components.victron_ble.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "name": "test_device",
                "address": "test-address",
                "key": "0123456789abcdef0123456789abcdef",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "test_device"
    assert result2["data"] == {
        "name": "test_device",
        "address": "test-address",
        "key": "0123456789abcdef0123456789abcdef",
    }
    assert len(mock_setup_entry.mock_calls) == 1
