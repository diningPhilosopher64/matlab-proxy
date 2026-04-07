import asyncio
import urllib
from pprint import pprint

import aiohttp


async def fetch_access_token_using_refresh_token():
    refresh_token = "Myw1eWVicjBhcDZtNmFvenc5aXI0c2FmaHhvdGtka3o5OXZtNnBicjJhaHVqOTF0ZmQsdE5nODUzTnRvQ2ZQV3ZXbktHYVhacGdiRXJ5dEk3b1RLS3ZzMHNKUXh1Tzd3dGdFL0VHQUg2MllSN3prdDR2VnN6TmR2aDBSWGE4WWIwQlVkNk5pNElheXBzMmpTQ09yOG9OZ2pMVXltTkplTEVEcnZGYklFL0xoc3VTaHV5bzJDejh4UXQwZG8rTlVYS2w5SytvQ3gzcVB1YWNrMGFqQ3lXaXhxMU5ISnhodDg5cThJSXFLdDFxMjliekFielVjblZoOCtLVjlzUT09"
    client_id = "matlab-proxy-client"
    client_secret = "14328de4-fdab-4126-8acd-c7c2e479f6e0"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    url = "https://signin-integ1.mathworks.com/oauth2/v1/oauth/token"

    async with aiohttp.ClientSession() as client:
        form_data = urllib.parse.urlencode(payload)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with client.post(url, data=form_data, headers=headers) as resp:
            if resp.status != 200:
                raise Exception(
                    f"Failed to use refresh token to fetch new access token. Status: {resp.status} for url: {url}, payload: {payload}"
                )

            token_response = await resp.json()
            pprint(token_response)

async def fetch_access_token_using_identity_token():
    refresh_token = "Mywyb2xoZ211b3lkeHoyZGJ4NHczdDFneGp4Y2U2bzh0MHB1bTc1NnliM3BmaXd2M3IsaFI4eUtEbmJKKzFBVDFkQnpJM2dQdFhVR1FGNUFpZWhiRTNNVjBTSjZtUTNXZnBlMHowTEEyYnY5QkZBaVBtdUNwcTEyNWZVTTI3Y09PbG1namIxTElOV2tDMVh5eGxlLzdDYkxyeUN6RGJmbUtXK3REU1BrNG9CUUI2V1lOMWcveUlYaFZlTUlhYmtJc2R2dmxRTDg2K1l5eVNYbHlpMHAxT0hSaVdnb010SFpYYzNOK0p5RzRrdVprTGdaVnM1UDlFeTUwSk1LUT09"
    client_id = "matlab-proxy-client"
    client_secret = "65089389-6041-4b1c-99b2-015490fe2f8a"
    
    url = "https://login-integ1.mathworks.com/authenticationws/service/v4"

    async with aiohttp.ClientSession(trust_env=True) as client_session:
        async with client_session.post(
            f"{url}/tokens/access",
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "accept": "application/json",
                "X_MW_WS_callerId": "desktop-jupyter",
            },
            data=aiohttp.FormData(
                {
                    "tokenString": refresh_token,
                    "type": "MWAS",
                    "sourceId": client_id,
                }
            ),
        ) as res:
            if not res.ok:
                raise Exception(
                    f"Failed to fetch access token. Status: {res.status} for url: {url}"
                )

            token_response = await res.json()
            pprint(token_response)
            

    


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(fetch_access_token_using_identity_token())