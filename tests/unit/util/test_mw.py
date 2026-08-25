# Copyright 2020-2026 The MathWorks, Inc.

import datetime
import os
import random
import re
import secrets
import urllib.parse
from collections import namedtuple
from datetime import timedelta, timezone
from http import HTTPStatus

import aiohttp
import pytest

from matlab_proxy import settings
from matlab_proxy.util import mw, system
from matlab_proxy.util.mwi import exceptions

"""This file tests methods present in matlab_proxy/util/mw.py
"""


@pytest.fixture(name="mwa_api_data")
def mwa_api_data_fixture():
    """Pytest fixture which returns a namedtuple.

    The namedtuple contains values required for MW authentication

    Returns:
        namedtuple: A named tuple containing mwa, mhlm end-point URLs (with regex patterns), source_id, identity_token, access_token and matlab_release.
    """

    mwa_api_endpoint = "https://login.mathworks.com/authenticationws/service/v4"
    mwa_api_endpoint_pattern = re.compile("^" + mwa_api_endpoint)
    mhlm_api_endpoint = (
        "https://licensing.mathworks.com/mls/service/v1/entitlement/list"
    )
    mhlm_api_endpoint_pattern = re.compile("^" + mhlm_api_endpoint)
    mhlm_context = "jupyter"

    identity_token = secrets.token_urlsafe(324)
    source_id = secrets.token_urlsafe(21)
    access_token = secrets.token_urlsafe(22)
    matlab_release = "R2020b"

    mwa_api_variables = namedtuple(
        "mwa_api_variables",
        [
            "mwa_api_endpoint",
            "mwa_api_endpoint_pattern",
            "mhlm_api_endpoint",
            "mhlm_api_endpoint_pattern",
            "identity_token",
            "source_id",
            "access_token",
            "matlab_release",
            "mhlm_context",
        ],
    )

    variables = mwa_api_variables(
        mwa_api_endpoint,
        mwa_api_endpoint_pattern,
        mhlm_api_endpoint,
        mhlm_api_endpoint_pattern,
        identity_token,
        source_id,
        access_token,
        matlab_release,
        mhlm_context,
    )

    return variables


@pytest.fixture(name="fetch_access_token_valid_json")
def fetch_access_token_valid_json_fixture():
    """Pytest fixture which returns a dict.

    This fixture returns a dict representing a valid json response from mhlm servers.

    Returns:
        dict : A dictionary containing Key-value pairs present in a valid json response from mhlm servers.
    """

    now = datetime.datetime.now(timezone.utc)
    authentication_date = str(now.strftime("%Y-%m-%dT%H:%M:%S.%f%z"))
    expiration_date = str((now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%f%z"))

    login_identifier = "abc@mathworks.com"
    reference_ID = int("".join([str(random.randint(0, 10)) for _ in range(8)]))

    first_name = "abc"
    last_name = "def"
    user_id = int("".join([str(random.randint(0, 10)) for _ in range(13)]))

    access_token_string = int("".join([str(random.randint(0, 10)) for _ in range(272)]))

    json_data = {
        "authenticationDate": authentication_date,
        "expirationDate": expiration_date,
        "id": 0,
        "loginIdentifier": login_identifier,
        "loginIdentifierType": "MWAS",
        "referenceDetail": {
            "referenceId": str(reference_ID),
            "country": "IN",
            "email": login_identifier,
            "firstName": first_name,
            "lastName": last_name,
            "displayName": first_name,
            "sector": "None",
            "userId": "mwa" + str(user_id),
            "profilePicture": "https://www.mathworks.com/",
        },
        "referenceId": str(reference_ID),
        "referenceType": "WEBPROFILEID",
        "source": "desktop-jupyter",
        "accessTokenString": str(access_token_string),
    }

    return json_data


class MockResponse:
    def __init__(self, ok, payload={}, status=HTTPStatus.OK, text="", headers=None):
        self._payload = payload
        self._text = text
        self.ok = ok
        self.status = status
        self.headers = headers if headers is not None else {}

    async def json(self):
        return self._payload

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass


async def test_fetch_access_token(mwa_api_data, fetch_access_token_valid_json, mocker):
    """Test to check mw.fetch_access_token method returns valid json response.

    The mock_response fixture mocks the aiohttp.ClientSession().post() method to return a custom HTTP response.

    Args:
        mwa_api_data (namedtuple): A pytest fixture which returns a namedtuple containing values for MW servers.
        fetch_access_token_valid_json (Dict): A pytest fixture which returns a dict representing a valid json response.
        mocker: Built in pytest fixture which can be used to mock functions.
    """
    json_data = fetch_access_token_valid_json

    payload = dict(accessTokenString=json_data["accessTokenString"])

    mock_resp = MockResponse(payload=payload, ok=True)

    url_pattern = mwa_api_data.mwa_api_endpoint_pattern

    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)
    res = await mw.fetch_access_token(
        mwa_api_data.mwa_api_endpoint,
        mwa_api_data.identity_token,
        mwa_api_data.source_id,
    )

    _, args, _ = mocked.mock_calls[0]
    url = args[0]

    assert re.match(url_pattern, url)
    assert json_data["accessTokenString"] == res["token"]


async def test_fetch_access_token_uses_mwas_by_default(
    mwa_api_data, fetch_access_token_valid_json, mocker
):
    """Test that fetch_access_token requests MWAS token type by default."""
    json_data = fetch_access_token_valid_json
    payload = dict(accessTokenString=json_data["accessTokenString"])
    mock_resp = MockResponse(payload=payload, ok=True)

    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)
    mocker.patch.dict(os.environ, {}, clear=False)
    os.environ.pop("MWI_ENABLE_LONG_RUNNING_SESSION", None)

    await mw.fetch_access_token(
        mwa_api_data.mwa_api_endpoint,
        mwa_api_data.identity_token,
        mwa_api_data.source_id,
    )

    _, _, kwargs = mocked.mock_calls[0]
    form_data = kwargs["data"]
    type_field = form_data._fields[1]
    assert type_field[0]["name"] == "type"
    assert type_field[2] == "MWAS"


async def test_fetch_access_token_uses_mwaj_when_long_running_session_enabled(
    mwa_api_data, fetch_access_token_valid_json, mocker
):
    """Test that fetch_access_token requests MWAJ token type when long-running session is enabled."""
    json_data = fetch_access_token_valid_json
    payload = dict(accessTokenString=json_data["accessTokenString"])
    mock_resp = MockResponse(payload=payload, ok=True)

    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)
    mocker.patch.dict(
        os.environ, {"MWI_ENABLE_LONG_RUNNING_SESSION": "True"}, clear=False
    )

    await mw.fetch_access_token(
        mwa_api_data.mwa_api_endpoint,
        mwa_api_data.identity_token,
        mwa_api_data.source_id,
    )

    _, _, kwargs = mocked.mock_calls[0]
    form_data = kwargs["data"]
    type_field = form_data._fields[1]
    assert type_field[0]["name"] == "type"
    assert type_field[2] == "MWAJ"


async def test_fetch_access_token_licensing_error(mwa_api_data, mocker):
    """Test to check mw.fetch_access_token() method raises a mwi_exceptions.OnlineLicensingError.

    When an invalid response is received from the server, this test checks if mwi_exceptions.OnlineLicensingError is raised.
    Args:
        mocker: Built in pytest fixture which can be used to mock functions.
        mwa_api_data (namedtuple): A pytest fixture which returns a namedtuple containing values for MW authentication
    """

    url_pattern = mwa_api_data.mwa_api_endpoint_pattern

    mock_resp = MockResponse(payload={}, ok=False, status=HTTPStatus.NOT_FOUND)

    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)

    with pytest.raises(exceptions.OnlineLicensingError):
        resp = await mw.fetch_access_token(
            mwa_api_data.mwa_api_endpoint,
            mwa_api_data.identity_token,
            mwa_api_data.source_id,
        )

    _, args, _ = mocked.mock_calls[0]
    url = args[0]
    assert re.match(url_pattern, url)


async def test_fetch_expand_token_licensing_error(mocker, mwa_api_data):
    """Test to check fetch_expand_token raises mwi_exceptions.OnlineLicensing error.

    Args:
        mocker: Built in pytest fixture which can be used to mock functions.
        mwa_api_data (namedtuple): A pytest fixture which returns a namedtuple containing values for MW authentication
    """
    url_pattern = mwa_api_data.mwa_api_endpoint_pattern
    mock_resp = MockResponse(
        payload={}, ok=False, status=HTTPStatus.SERVICE_UNAVAILABLE
    )
    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)

    with pytest.raises(exceptions.OnlineLicensingError):
        resp = await mw.fetch_expand_token(
            mwa_api_data.mwa_api_endpoint,
            mwa_api_data.identity_token,
            mwa_api_data.source_id,
        )

    _, args, _ = mocked.mock_calls[0]
    url = args[0]
    assert re.match(url_pattern, url)


@pytest.fixture(name="fetch_expand_token_valid_json")
def fetch_expand_token_valid_json_fixture():
    """Pytest fixture which returns a dict

    The return value represents a valid json response when mw.fetch_expand_token function is called.

    Returns:
        dict: A dict representing valid json response.
    """
    now = datetime.datetime.now(timezone.utc)
    expiration_date = str((now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%f%z"))
    first_name = "abc"
    display_name = first_name
    last_name = "def"
    reference_ID = int("".join([str(random.randint(0, 10)) for _ in range(8)]))
    user_id = int("".join([str(random.randint(0, 10)) for _ in range(13)]))

    json_data = {
        "expirationDate": str(expiration_date),
        "referenceDetail": {
            "referenceId": str(reference_ID),
            "firstName": first_name,
            "lastName": last_name,
            "displayName": first_name,
            "userId": "mwa" + str(user_id),
        },
    }

    return json_data


async def test_fetch_expand_token(mocker, fetch_expand_token_valid_json, mwa_api_data):
    """Test to check if mw.fetch_expand_token returns a correct json response

    mock_response is used to mock ClientSession.post method to return a HTTP Response containing a valid json response.
    Args:
        mocker: Built in pytest fixture which can be used to mock functions.
        fetch_expand_token_valid_json (namedtuple): Pytest fixture which returns a dict which is returned by the server when no exception is raised.
        mwa_api_data (namedtuple): A namedtuple which contains info related to mwa.
    """
    json_data = fetch_expand_token_valid_json

    url_pattern = mwa_api_data.mwa_api_endpoint_pattern
    referenceDetail = dict(
        firstName=json_data["referenceDetail"]["firstName"],
        lastName=json_data["referenceDetail"]["lastName"],
        displayName=json_data["referenceDetail"]["displayName"],
        userId=json_data["referenceDetail"]["userId"],
        referenceId=json_data["referenceDetail"]["referenceId"],
    )

    payload = dict(
        expirationDate=json_data["expirationDate"], referenceDetail=referenceDetail
    )

    mock_resp = MockResponse(payload=payload, ok=True, status=HTTPStatus.OK)
    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)

    resp = await mw.fetch_expand_token(
        mwa_api_data.mwa_api_endpoint,
        mwa_api_data.identity_token,
        mwa_api_data.source_id,
    )

    _, args, _ = mocked.mock_calls[0]
    url = args[0]

    assert resp is not None and len(resp.keys()) > 0
    assert re.match(url_pattern, url)


async def test_fetch_entitlements_licensing_error(mocker, mwa_api_data):
    """Test to check if fetch_entitlements raises mwi_exceptions.OnlineLicensingError.

    When an invalid response is received, this test checks if mwi_exceptions.OnlineLicenseError is raised.

    Args:
        mocker: Built in pytest fixture which can be used to mock functions.
        mwa_api_data (namedtuple): A namedtuple which contains info related to mwa.
    """
    url_pattern = mwa_api_data.mhlm_api_endpoint_pattern
    mock_resp = MockResponse(
        payload={}, ok=False, status=HTTPStatus.SERVICE_UNAVAILABLE
    )
    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)

    with pytest.raises(exceptions.OnlineLicensingError):
        resp = await mw.fetch_entitlements(
            mwa_api_data.mhlm_api_endpoint,
            mwa_api_data.access_token,
            mwa_api_data.matlab_release,
        )

    _, args, _ = mocked.mock_calls[0]
    url = args[0]
    assert re.match(url_pattern, url)


@pytest.fixture(
    name="invalid_entitlements",
    params=[
        """<?xml version="1.0" encoding="UTF-8"?>
                        <describe_entitlements_response>
                        </describe_entitlements_response>""",
        """<?xml version="1.0" encoding="UTF-8"?>
                        <describe_entitlements_response>
                            <entitlements>
                            </entitlements>
                        </describe_entitlements_response>""",
    ],
    ids=[
        "Invalid Entitlement : No entitlements tag",
        "Invalid Entitlement : Empty entitlements tag",
    ],
)
def invalid_entitlements_fixture(request):
    """A parameterized pytest fixture which returns invalid entitlements.


    Args:
        request : Built-in pytest fixture

    Returns:
        [String]: A string containing invalid Entitlements.
    """
    return request.param


async def test_fetch_entitlements_entitlement_error(
    mocker, mwa_api_data, invalid_entitlements
):
    """Test to check fetch_entitlements raises mwi_exceptions.EntitlementError.


    When invalid entitlements are received as a response, this test checks if mw.fetch_entitlements raises an
    mwi_exceptions.EntitlementError. mock_response mocks aiohttp.ClientSession.post method to send invalid entitlements as a HTTP response.

    Args:

        mocker: Built in pytest fixture which can be used to mock functions.
        mwa_api_data (namedtuple): A namedtuple which contains info related to mwa.
        invalid_entitlements (String): String containing invalid entitlements
    """
    url_pattern = mwa_api_data.mhlm_api_endpoint_pattern

    mock_resp = MockResponse(
        payload={}, ok=True, text=invalid_entitlements, status=HTTPStatus.NOT_FOUND
    )
    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)

    with pytest.raises(exceptions.EntitlementError):
        resp = await mw.fetch_entitlements(
            mwa_api_data.mhlm_api_endpoint,
            mwa_api_data.access_token,
            mwa_api_data.matlab_release,
        )

    _, args, _ = mocked.mock_calls[0]
    url = args[0]
    assert re.match(url_pattern, url)


@pytest.fixture(name="valid_entitlements")
def valid_entitlements_fixture():
    """
    Pytest fixture which returns a string representing valid entitlements
    """
    id = int("".join([str(random.randint(0, 10)) for _ in range(7)]))
    license_number = int("".join([str(random.randint(0, 10)) for _ in range(8)]))

    return """<?xml version="1.0" encoding="UTF-8"?>
                <describe_entitlements_response>
                <entitlements>
                    <entitlement>
                        <id>%d</id>
                        <label>MATLAB</label>
                        <license_number>%d</license_number>
                        </entitlement>
                </entitlements>
                </describe_entitlements_response>""" % (
        id,
        license_number,
    )


async def test_fetch_entitlements(mocker, mwa_api_data, valid_entitlements):
    """Test to check test_fetch_entitlements returns valid response.


    mock_response mocks aiohttpClientSession.post() method  to return valid entitlements as a HTTP response
    Args:
        mocker: Built in pytest fixture which can be used to mock functions.
        mwa_api_data (namedtuple): A namedtuple which contains info related to mwa.
        valid_entitlements (String): String containing valid entitlements as a response.
    """

    url_pattern = mwa_api_data.mhlm_api_endpoint_pattern

    mock_resp = MockResponse(
        payload={}, ok=True, text=valid_entitlements, status=HTTPStatus.OK
    )
    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)

    resp = await mw.fetch_entitlements(
        mwa_api_data.mhlm_api_endpoint,
        mwa_api_data.access_token,
        mwa_api_data.matlab_release,
    )

    _, args, _ = mocked.mock_calls[0]
    url = args[0]

    assert resp is not None and len(resp) > 0
    assert re.match(url_pattern, url)


# ---------------------------------------------------------------------------
# OAuth 2.0 device code flow HTTP client functions
# ---------------------------------------------------------------------------

OAUTH_HOST = "https://signin.mathworks.com"
OAUTH_CLIENT_ID = "mw-cpi-matlab-proxy"


class _FakeDPoPKey:
    """Minimal stand-in for DPoPKey that records the proofs it is asked for."""

    def __init__(self):
        self.calls = []

    def generate_proof(self, method, url):
        self.calls.append((method, url))
        return f"dpop-proof-for-{method}-{url}"


async def test_device_authorize_returns_json(mocker):
    """device_authorize returns the parsed JSON body on a 200 JSON response."""
    device_response = {
        "device_code": "secret-device-code",
        "user_code": "ABCD-EFGH",
        "verification_uri": f"{OAUTH_HOST}/device",
        "expires_in": 600,
        "interval": 5,
    }
    mock_resp = MockResponse(
        ok=True,
        payload=device_response,
        status=HTTPStatus.OK,
        headers={"Content-Type": "application/json"},
    )
    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)
    dpop_key = _FakeDPoPKey()

    result = await mw.device_authorize(
        OAUTH_HOST, OAUTH_CLIENT_ID, "code-challenge", "source-id", dpop_key=dpop_key
    )

    assert result == device_response
    # Endpoint URL and the DPoP proof header must be set.
    _, args, kwargs = mocked.mock_calls[0]
    assert args[0] == f"{OAUTH_HOST}/oauth2/v1/oauth/device/authorize"
    assert kwargs["headers"]["DPoP"] == "dpop-proof-for-POST-" + args[0]
    assert kwargs["allow_redirects"] is False
    assert dpop_key.calls == [("POST", args[0])]


async def test_device_authorize_uses_default_scope_by_default(mocker):
    """device_authorize requests the base scope (no MWAJ) by default."""
    mock_resp = MockResponse(
        ok=True,
        payload={"device_code": "x", "user_code": "y", "verification_uri": "z"},
        status=HTTPStatus.OK,
        headers={"Content-Type": "application/json"},
    )
    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)
    mocker.patch.dict(os.environ, {}, clear=False)
    os.environ.pop("MWI_ENABLE_LONG_RUNNING_SESSION", None)

    await mw.device_authorize(
        OAUTH_HOST, OAUTH_CLIENT_ID, "code-challenge", "source-id"
    )

    _, _, kwargs = mocked.mock_calls[0]
    assert kwargs["json"]["scope"] == "openid profile email"


async def test_device_authorize_requests_mwaj_scope_when_long_running_enabled(mocker):
    """device_authorize appends token_type:mwaj to the scope when long-running
    session support is enabled."""
    mock_resp = MockResponse(
        ok=True,
        payload={"device_code": "x", "user_code": "y", "verification_uri": "z"},
        status=HTTPStatus.OK,
        headers={"Content-Type": "application/json"},
    )
    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)
    mocker.patch.dict(
        os.environ, {"MWI_ENABLE_LONG_RUNNING_SESSION": "True"}, clear=False
    )

    await mw.device_authorize(
        OAUTH_HOST, OAUTH_CLIENT_ID, "code-challenge", "source-id"
    )

    _, _, kwargs = mocked.mock_calls[0]
    assert kwargs["json"]["scope"] == "openid profile email token_type:mwaj"


async def test_device_authorize_rejects_redirect(mocker):
    """A redirect from the device endpoint means device flow is unavailable -> error."""
    mock_resp = MockResponse(
        ok=False,
        status=HTTPStatus.FOUND,  # 302
        headers={"Location": "https://elsewhere.example"},
    )
    mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)

    with pytest.raises(exceptions.OnlineLicensingError):
        await mw.device_authorize(
            OAUTH_HOST, OAUTH_CLIENT_ID, "code-challenge", "source-id"
        )


async def test_device_authorize_rejects_non_200(mocker):
    """A non-200 (and non-redirect) status raises OnlineLicensingError."""
    mock_resp = MockResponse(ok=False, status=HTTPStatus.INTERNAL_SERVER_ERROR)
    mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)

    with pytest.raises(exceptions.OnlineLicensingError):
        await mw.device_authorize(
            OAUTH_HOST, OAUTH_CLIENT_ID, "code-challenge", "source-id"
        )


async def test_device_authorize_rejects_non_json(mocker):
    """A 200 response that is not JSON raises OnlineLicensingError."""
    mock_resp = MockResponse(
        ok=True,
        status=HTTPStatus.OK,
        text="<html>not json</html>",
        headers={"Content-Type": "text/html"},
    )
    mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)

    with pytest.raises(exceptions.OnlineLicensingError):
        await mw.device_authorize(
            OAUTH_HOST, OAUTH_CLIENT_ID, "code-challenge", "source-id"
        )


async def test_check_device_auth_status_returns_status(mocker):
    """check_device_auth_status returns the parsed JSON and hits the authstatus GET endpoint."""
    mock_resp = MockResponse(ok=True, payload={"status": "PENDING"})
    mocked = mocker.patch("aiohttp.ClientSession.get", return_value=mock_resp)

    result = await mw.check_device_auth_status(
        OAUTH_HOST, "secret-device-code", OAUTH_CLIENT_ID
    )

    assert result == {"status": "PENDING"}
    _, args, _ = mocked.mock_calls[0]
    url = args[0]
    assert url.startswith(f"{OAUTH_HOST}/oauth2/v1/oauth/device/authstatus?")
    # device_code and client_id are passed as query params.
    assert "device_code=secret-device-code" in url
    assert f"client_id={OAUTH_CLIENT_ID}" in url


async def test_check_device_auth_status_error(mocker):
    """A non-200 authstatus response raises OnlineLicensingError."""
    mock_resp = MockResponse(
        ok=False, status=HTTPStatus.SERVICE_UNAVAILABLE, text="unavailable"
    )
    mocker.patch("aiohttp.ClientSession.get", return_value=mock_resp)

    with pytest.raises(exceptions.OnlineLicensingError):
        await mw.check_device_auth_status(OAUTH_HOST, "device-code", OAUTH_CLIENT_ID)


async def test_exchange_device_token_returns_tokens(mocker):
    """exchange_device_token returns the token response and sends a DPoP proof."""
    token_response = {
        "mwa_token": {"accessTokenString": "access-abc"},
        "refresh_token": "refresh-xyz",
    }
    mock_resp = MockResponse(ok=True, payload=token_response, status=HTTPStatus.OK)
    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)
    dpop_key = _FakeDPoPKey()
    token_url = f"{OAUTH_HOST}/oauth2/v1/oauth/token"

    result = await mw.exchange_device_token(
        token_url, "device-code", OAUTH_CLIENT_ID, "code-verifier", dpop_key=dpop_key
    )

    assert result == token_response
    _, args, kwargs = mocked.mock_calls[0]
    assert args[0] == token_url
    assert kwargs["headers"]["DPoP"] == f"dpop-proof-for-POST-{token_url}"
    # The body is form-urlencoded; decode it and assert the device_code grant.
    body = dict(urllib.parse.parse_qsl(kwargs["data"]))
    assert body["grant_type"] == mw.DEVICE_CODE_GRANT_TYPE
    assert body["device_code"] == "device-code"
    assert body["code_verifier"] == "code-verifier"


async def test_exchange_device_token_error_surfaces_server_error(mocker):
    """A failed token exchange raises OnlineLicensingError including the server error."""
    mock_resp = MockResponse(
        ok=False,
        payload={"error": "invalid_grant"},
        status=HTTPStatus.BAD_REQUEST,
    )
    mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)

    with pytest.raises(exceptions.OnlineLicensingError, match="invalid_grant"):
        await mw.exchange_device_token(
            f"{OAUTH_HOST}/oauth2/v1/oauth/token",
            "device-code",
            OAUTH_CLIENT_ID,
            "code-verifier",
        )


async def test_refresh_oauth_token_returns_rotated_tokens(mocker):
    """refresh_oauth_token returns the new (rotated) token response with a DPoP proof."""
    rotated = {
        "mwa_token": {"accessTokenString": "new-access"},
        "refresh_token": "new-refresh-rotated",
    }
    mock_resp = MockResponse(ok=True, payload=rotated, status=HTTPStatus.OK)
    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)
    dpop_key = _FakeDPoPKey()
    refresh_url = f"{OAUTH_HOST}/oauth2/v1/oauth/refresh"

    result = await mw.refresh_oauth_token(
        refresh_url, OAUTH_CLIENT_ID, "old-refresh", dpop_key=dpop_key
    )

    assert result == rotated
    _, args, kwargs = mocked.mock_calls[0]
    assert args[0] == refresh_url
    assert kwargs["headers"]["DPoP"] == f"dpop-proof-for-POST-{refresh_url}"
    assert kwargs["json"]["grant_type"] == "refresh_token"
    assert kwargs["json"]["refresh_token"] == "old-refresh"


async def test_refresh_oauth_token_error(mocker):
    """A failed refresh raises OnlineLicensingError including the server error."""
    mock_resp = MockResponse(
        ok=False,
        payload={"error": "invalid_token"},
        status=HTTPStatus.UNAUTHORIZED,
    )
    mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)

    with pytest.raises(exceptions.OnlineLicensingError, match="invalid_token"):
        await mw.refresh_oauth_token(
            f"{OAUTH_HOST}/oauth2/v1/oauth/refresh", OAUTH_CLIENT_ID, "old-refresh"
        )


async def test_revoke_oauth_token_success(mocker):
    """revoke_oauth_token returns True on a 200 and sends a DPoP proof + revoke body."""
    mock_resp = MockResponse(ok=True, payload={}, status=HTTPStatus.OK)
    mocked = mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)
    dpop_key = _FakeDPoPKey()
    revoke_url = f"{OAUTH_HOST}/oauth2/v1/oauth/revoke"

    result = await mw.revoke_oauth_token(
        revoke_url, OAUTH_CLIENT_ID, "refresh-to-revoke", dpop_key=dpop_key
    )

    assert result is True
    _, args, kwargs = mocked.mock_calls[0]
    assert args[0] == revoke_url
    assert kwargs["headers"]["DPoP"] == f"dpop-proof-for-POST-{revoke_url}"
    # RFC 7009 body: the refresh token and its type hint.
    assert kwargs["json"]["token"] == "refresh-to-revoke"
    assert kwargs["json"]["token_type_hint"] == "refresh_token"
    assert kwargs["json"]["client_id"] == OAUTH_CLIENT_ID
    assert dpop_key.calls == [("POST", revoke_url)]


async def test_revoke_oauth_token_non_200_returns_false(mocker):
    """A non-200 revoke response is best-effort: returns False, does not raise."""
    mock_resp = MockResponse(
        ok=False, status=HTTPStatus.INTERNAL_SERVER_ERROR, text="error"
    )
    mocker.patch("aiohttp.ClientSession.post", return_value=mock_resp)

    result = await mw.revoke_oauth_token(
        f"{OAUTH_HOST}/oauth2/v1/oauth/revoke", OAUTH_CLIENT_ID, "refresh-to-revoke"
    )

    assert result is False


async def test_revoke_oauth_token_network_error_returns_false(mocker):
    """A network error during revoke is swallowed (best-effort): returns False."""
    mocker.patch(
        "aiohttp.ClientSession.post",
        side_effect=aiohttp.ClientError("boom"),
    )

    result = await mw.revoke_oauth_token(
        f"{OAUTH_HOST}/oauth2/v1/oauth/revoke", OAUTH_CLIENT_ID, "refresh-to-revoke"
    )

    assert result is False


def test_parse_mhlm_no_error():
    """Test to check mw.parse_mhlm_error() method returns none when no mhlm specific error
    is present in the logs.
    """
    logs = ["Starting MATLAB proxy-app", "Error parsing config, resetting."]

    actual_output = mw.parse_mhlm_error(logs)
    expected_output = None

    assert actual_output == expected_output


def test_parse_mhlm_error():
    """Test to check mw.parse_mhlm_error() returns an mwi_exceptions.OnlineLiceningError.

    When logs contain mhlm specific error information, this test checks if mwi_exceptions.OnlineLicensingError is raised.
    """
    logs = ["License Manager Error", "MHLM Licensing Failed"]
    actual_output = mw.parse_mhlm_error(logs)
    expected_output = exceptions.OnlineLicensingError

    assert isinstance(actual_output, expected_output)


def test_parse_nlm_no_error():
    """Test to check parse_nlm_error returns none when no nlm specific error information is present in logs."""
    logs = []
    conn_str = ""
    expected_output = None

    assert mw.parse_nlm_error(logs, conn_str) == expected_output


def test_parse_nlm_error():
    """Test to check parse_nlm_error() method returns an exception when logs contain an error.

    When logs contain nlm specific errors, this test checks if parse_nlm_error() raises mwi_exceptions.NetworkLicensingError.
    """
    logs = [
        "Starting MATLAB proxy-app",
        "License checkout failed",
        "Error parsing config, resetting.",
        "Diagnostic Information",
    ]

    conn_str = "123@nlm"

    actual_output = mw.parse_nlm_error(logs, conn_str)
    expected_output = exceptions.NetworkLicensingError

    assert isinstance(actual_output, expected_output)


def test_parse_other_error():
    """This test checks if exception.MatlabError is raised when matlab processes returncode is not 0 and logs contain
    matlab specific information
    """
    logs = ["Starting MATLAB proxy-app", "Error parsing config, resetting."]

    expected_output = exceptions.MatlabError
    actual_output = mw.parse_other_error(logs)

    assert isinstance(actual_output, expected_output)


def test_range_matlab_connector_ports():
    """This test checks if the generator mw.range _matlab_connector_ports()
    yields consecutive port numbers.
    """
    port_range = mw.range_matlab_connector_ports()
    first_port = next(port_range)
    second_port = next(port_range)

    assert first_port + 1 == second_port


@pytest.mark.skipif(
    not system.is_linux(),
    reason="Xvfb is only required on linux based operating systems",
)
async def test_create_xvfb_process():
    """Test to check if more than 1 xvfb process can be created with -displayfd flag

    Creates 2 xvfb processes with '-displayfd' flag and  checks if the processes are
    running on unique display ports
    """
    settings_1 = settings.get(dev=True)

    # Return if Xvfb is not available
    if not settings_1["is_xvfb_available"]:
        return

    xvfb_cmd_1, pipe_1 = settings.create_xvfb_cmd()
    xvfb_cmd_2, pipe_2 = settings.create_xvfb_cmd()

    # Create Xvfb processes
    xvfb_1, display_port_1 = await mw.create_xvfb_process(xvfb_cmd_1, pipe_1, {})
    xvfb_2, display_port_2 = await mw.create_xvfb_process(xvfb_cmd_2, pipe_2, {})

    # Verify
    assert xvfb_1 is not None and xvfb_2 is not None
    assert display_port_1 != display_port_2

    # Clean up
    xvfb_1.terminate()
    await xvfb_1.wait()

    xvfb_2.terminate()
    await xvfb_2.wait()
