# Copyright 2026 The MathWorks, Inc.

"""HTTP handlers for configuring licensing and completing device authorization."""

import time

from aiohttp import web

from matlab_proxy.responses import create_status_response, marshal_licensing_info
from matlab_proxy.util import mw, mwi
from matlab_proxy.util.mwi import token_auth
from matlab_proxy.util.mwi.exceptions import EntitlementError, LicensingError

from .base import LicensingType
from .oauth import DeviceAuthStatus

logger = mwi.logger.get()


@token_auth.authenticate_access_decorator
async def set_licensing_info(req):
    """API Endpoint to set licensing information on the server side.

    Args:
        req (HTTPRequest): HTTPRequest Object

    Raises:
        Exception: If Licensing type is neither MHLM nor NLM.
        web.HTTPBadRequest: If any error with Licensing.

    Returns:
        JSONResponse: JSONResponse object containing updated information on the state of MATLAB among other information.
    """
    state = req.app["state"]

    data = await req.json()
    lic_type = data.get("type")

    try:
        if lic_type == LicensingType.NLM:
            await state.set_licensing_nlm(data.get("connectionString"))

        elif lic_type == LicensingType.MHLM:
            # If matlab version could not be determined on startup update
            # the value received from the front-end.
            if not state.settings.matlab_version_determined_on_startup and data.get(
                "matlabVersion"
            ):
                state.settings.matlab_version = data.get("matlabVersion")

            await state.set_licensing_mhlm(
                data.get("token"), data.get("emailAddress"), data.get("sourceId")
            )
            # The user committed to the classic flow. Any device authorization
            # left pending while that experience was hidden is no longer useful,
            # so discard its in-memory secrets instead of retaining them until a
            # future poll notices the code has expired.
            await state.device_flow.clear()

        elif lic_type == LicensingType.EXISTING_LICENSE:
            state.set_licensing_existing_license()

        else:
            raise Exception(
                'License type must be "NLM" or "MHLM" or "ExistingLicense"!'
            )
    except Exception:
        raise web.HTTPBadRequest(text="Error with licensing!")

    # This is true for a user who has only one license associated with their account
    await __start_matlab_if_licensed(state)

    return create_status_response(req.app)


@token_auth.authenticate_access_decorator
async def update_entitlement(req):
    """API endpoint to update selected entitlement to start MATLAB with.

    Args:
        req (HTTPRequest): HTTPRequest Object

    Returns:
        JSONResponse: JSONResponse object containing updated information on the state of MATLAB among other information.
    """
    state = req.app["state"]
    data = await req.json()
    lic_type = data.get("type")

    # Set the entitlement id only if we are not already licensed
    if (
        lic_type in (LicensingType.MHLM, LicensingType.OAUTH)
        and not state.is_licensed()
    ):
        entitlement_id = data.get("entitlement_id")
        logger.debug(f"Received type: {lic_type}, entitlement_id: {entitlement_id}")
        await state.update_user_selected_entitlement_info(entitlement_id)
        await __start_matlab_if_licensed(state)

    return create_status_response(req.app)


async def __start_matlab_if_licensed(state):
    # Start MATLAB if licensing is complete
    if state.is_licensed() and not isinstance(state.error, LicensingError):
        await state.start_matlab(restart_matlab=True)


@token_auth.authenticate_access_decorator
async def device_authorize(req):
    """Initiate the OAuth 2.0 Device Code flow.

    Returns user_code, verification_uri, and polling info to the frontend.
    The device_code is kept server-side (secret) and never sent to the frontend.
    """
    state = req.app["state"]

    # If the MATLAB version could not be determined on startup, the frontend
    # collects it from the user (via a dropdown) BEFORE starting the flow and sends
    # it here - mirroring how MHLM sends matlabVersion with set_licensing_info. We
    # record it now so it is known by the time poll_device_token licenses and starts
    # MATLAB, which is why the device flow needs no separate version-commit step.
    try:
        data = await req.json()
    except Exception:
        data = {}
    if not state.settings.matlab_version_determined_on_startup and data.get(
        "matlabVersion"
    ):
        state.settings.matlab_version = data.get("matlabVersion")

    # PKCE (the code_verifier is used during token exchange) and a fresh DPoP key.
    flow = state.device_flow
    flow.start()

    try:
        device_response = await mw.device_authorize(
            state.settings.oauth_endpoint,
            state.settings.oauth_client_id,
            flow.code_challenge,
            flow.oauth_session_id,
            dpop_key=flow.dpop_key,
        )
        expires_in = flow.record_authorization(device_response)

        # Return only user-facing info.
        return web.json_response(
            {
                "user_code": flow.device_user_code,
                "verification_uri": flow.device_verification_uri,
                "verification_uri_complete": flow.device_verification_uri_complete,
                "expires_in": expires_in,
                "interval": flow.device_code_interval,
            }
        )

    except Exception as e:
        logger.error(f"Device authorization error: {e}")
        return web.json_response(
            {"error": f"Device authorization error: {e!s}"},
            status=502,
        )


@token_auth.authenticate_access_decorator
async def poll_device_token(req):
    """Poll for OAuth tokens using the device code flow with smart caching.

    The frontend polls every 1 second. The backend only hits the OAuth server
    every 'interval' seconds (as specified by the OAuth server).
    """
    state = req.app["state"]
    flow = state.device_flow

    # Capture the secrets before any await, so the exchange uses this flow's values.
    device_code = flow.device_code
    code_verifier = flow.code_verifier

    if not flow.in_progress:
        # No flow in progress (fresh load, or state was cleared after a terminal
        # outcome). This is not an error - it is the normal pre-Start state, so the
        # frontend renders the "Start" screen.
        return web.json_response({"status": "idle"})

    # A flow is in progress but its code has already expired: clear the stale state
    # and report expiry so the frontend can offer a restart.
    if flow.is_expired():
        await flow.clear()
        return web.json_response(
            {"status": "error", "error": "Device code expired"},
            status=410,
        )

    # Smart caching: only poll the OAuth server every `interval` seconds. On
    # intermediate frontend polls, return the cached PENDING status.
    current_time = time.time()
    if not flow.should_check_status(current_time):
        return _pending_response(flow)

    try:
        oauth_host = state.settings.oauth_endpoint
        client_id = state.settings.oauth_client_id

        auth_status = await flow.check_auth_status(oauth_host, client_id)
        status_value = flow.record_status(
            auth_status.get("status", DeviceAuthStatus.PENDING), current_time
        )

        if status_value == DeviceAuthStatus.PENDING:
            return _pending_response(flow)

        elif status_value == DeviceAuthStatus.DENIED:
            await flow.clear()
            return web.json_response(
                {"status": "error", "error": "User denied authorization"},
                status=403,
            )

        elif status_value == DeviceAuthStatus.EXPIRED:
            await flow.clear()
            return web.json_response(
                {"status": "error", "error": "Device code expired"},
                status=410,
            )

        elif flow.is_authorized:
            # User authorized! Exchange the device_code for tokens.
            token_url = f"{oauth_host}/oauth2/v1/oauth/token"

            token_response = await mw.exchange_device_token(
                token_url, device_code, client_id, code_verifier, dpop_key=flow.dpop_key
            )

            await state.set_licensing_from_token_response(token_response)
            await flow.clear()

            await __start_matlab_if_licensed(state)

            return web.json_response(
                {
                    "status": "success",
                    "licensing": marshal_licensing_info(state.licensing),
                }
            )

        else:
            return _pending_response(flow)

    except EntitlementError as e:
        # Authorization succeeded, but this account cannot license the selected
        # MATLAB release. Discard the partially constructed OAuth state and any
        # stale cached entry, then surface the actionable entitlement message.
        state.discard_oauth_licensing()
        await flow.clear()
        return web.json_response(
            {"status": "error", "error": e.message},
            status=403,
        )

    except Exception as e:
        # If we were in an AUTHORIZED state and the exchange failed, the flow must
        # be restarted. For transient errors during the status check, keep polling.
        if flow.is_authorized:
            await flow.clear()
            return web.json_response(
                {
                    "status": "error",
                    "error": f"Token exchange failed: {e!s}. Please try again.",
                },
                status=500,
            )
        logger.trace(f"Transient error during device token poll: {e}")
        return _pending_response(flow)


def _pending_response(flow):
    """Build a pending response that echoes the user-facing fields, so the
    frontend can rehydrate the same code/URL/countdown after a page refresh."""
    return web.json_response(
        {
            "status": "pending",
            "message": "Waiting for user to authorize",
            **flow.display_fields(),
        }
    )


@token_auth.authenticate_access_decorator
async def licensing_info_delete(req):
    """API Endpoint to stop MATLAB and remove licensing details.

    Args:
        req (HTTPRequest): HTTPRequest Object
    Returns:
        JSONResponse: JSONResponse object containing updated information on the state of MATLAB among other information.
    """
    state = req.app["state"]

    # Removing license information implies terminating MATLAB
    await state.stop_matlab()

    # When removing licensing data, if matlab version was fetched from the user, remove it
    # on the server side to have a complete 'reset'.
    if (
        state.licensing.type in (LicensingType.MHLM, LicensingType.OAUTH)
        and not state.settings.matlab_version_determined_on_startup
    ):
        state.settings.matlab_version = None

    # For OAuth, revoke the refresh token server-side (best-effort) before
    # discarding it, then remove only the current client's entry from the shared
    # cache (other integrations' tokens must be preserved), then clear in-memory state.
    if state.licensing.type == LicensingType.OAUTH:
        await state.licensing.revoke(state.settings)
        state.discard_oauth_licensing()
        return create_status_response(req.app)

    # Unset licensing information
    state.unset_licensing()

    # Persist config information
    state.persist_config_data()

    return create_status_response(req.app)
