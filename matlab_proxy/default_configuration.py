# Copyright 2020-2026 The MathWorks, Inc.
from enum import Enum
from typing import List

import matlab_proxy


class ConfigKeys(Enum):
    """Enumeration for configuration keys used in the MATLAB proxy setup."""

    DOC_URL = "doc_url"
    EXT_NAME = "extension_name"
    EXT_NAME_DESC = "extension_name_short_description"
    SHOW_SHUTDOWN_BUTTON = "should_show_shutdown_button"
    OAUTH_CLIENT_ID = "oauth_client_id"


# Configure matlab_proxy
config = {
    # Link the documentation url here. This will show up on the website UI
    # where users can create issue's or make enhancement requests
    ConfigKeys.DOC_URL.value: "https://github.com/mathworks/matlab-proxy/",
    # Use a single word for extension_name
    # It will be used as a flag when launching the integration.
    # NOTE: This name must be used when setting the entrypoint for matlab_proxy in setup.py
    # Use '-' or '_' seperated values if more than 1 word is used.
    # Ex: Hello-World, Alice_Bob.
    ConfigKeys.EXT_NAME.value: matlab_proxy.get_default_config_name(),
    # This value will be used in various places on the website UI.
    # Ensure that this is not more than 3 words.
    ConfigKeys.EXT_NAME_DESC.value: "MATLAB Desktop",
    # Show the shutdown button in the UI for matlab-proxy
    ConfigKeys.SHOW_SHUTDOWN_BUTTON.value: True,
    # OAuth 2.0 public client id registered with the MathWorks OAuth server.
    # Its presence enables the OAuth device code sign-in flow (replacing the
    # legacy MHLM iframe). Each integration should declare its own client id so
    # that the consent screen shows the correct product name. This key is
    # intentionally NOT part of get_required_config() so that integrations which
    # have not yet adopted the device code flow gracefully fall back to the MHLM
    # iframe.
    ConfigKeys.OAUTH_CLIENT_ID.value: "mw-cpi-matlab-proxy",
}


def get_required_config() -> List[str]:
    """Get the list of required configuration keys.

    This function returns a list of keys that are required for
    the MATLAB proxy configuration. These keys are used to
    ensure that the configuration dictionary contains all the
    necessary entries.

    Returns:
        list: A list of strings representing the required
        configuration keys.
    """
    required_keys: List[ConfigKeys] = [
        ConfigKeys.DOC_URL,
        ConfigKeys.EXT_NAME,
        ConfigKeys.EXT_NAME_DESC,
    ]
    return [key.value for key in required_keys]
