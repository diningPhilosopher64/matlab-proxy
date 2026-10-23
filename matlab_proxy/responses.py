# Copyright 2026 The MathWorks, Inc.

"""Public status responses shared by application and licensing routes."""

from aiohttp import web

from matlab_proxy.util.mwi.exceptions import AppError


def marshal_licensing_info(licensing_info):
    """Serialize licensing for the browser without exposing credentials."""
    return licensing_info.to_public_dict() if licensing_info is not None else None


def marshal_error(error):
    """Gather/Marshal error details.

    Args:
        error (Object): Instance of NetworkLicensingError or OnlineLicensingError or MatlabError

    Returns:
        Dict: Containing information about the error.
    """
    if error is None:
        return None
    if isinstance(error, AppError):
        return {
            "message": error.message,
            "logs": error.logs,
            "type": error.__class__.__name__,
        }
    else:
        return {"message": error.__str__, "logs": "", "type": error.__class__.__name__}


def create_status_response(app, loadUrl=None, client_id=None, is_active_client=None):
    """Send a generic status response about the state of server, MATLAB, MATLAB Licensing and the client session status.

    Args:
        app (aiohttp.web.Application): Web Server
        loadUrl (String, optional): Represents the root URL. Defaults to None.
        client_id (String, optional): Represents the generated client_id when concurrency check is enabled and client does not have a client_id. Defaults to None.
        is_active_client (Boolean, optional): Represents whether the current client is the active_client when concurrency check is enabled. Defaults to None.

    Returns:
        JSONResponse: A JSONResponse object containing the generic state of the server, MATLAB, MATLAB Licensing and the client session status.
    """
    state = app["state"]
    status = {
        "matlab": {
            "status": state.get_matlab_state(),
            "busyStatus": state.matlab_busy_state,
            "version": state.settings.matlab_version,
        },
        "licensing": marshal_licensing_info(state.licensing),
        "loadUrl": loadUrl,
        "error": marshal_error(state.error),
        "warnings": state.warnings,
        "wsEnv": state.settings.ws_env,
    }

    if client_id:
        status["clientId"] = client_id
    if is_active_client is not None:
        status["isActiveClient"] = is_active_client

    return web.json_response(status)
