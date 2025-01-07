// Copyright 2020-2024 The MathWorks, Inc.

import React, { useState, useEffect, useMemo, useRef } from "react";
import { useSelector, useDispatch } from "react-redux";
import { MatlabVersionInput } from "./MatlabVersionInput";
import PropTypes from "prop-types";
import {
    selectLicensingMhlmUsername,
    selectWsEnv,
    selectMatlabVersionOnPath,
} from "../../selectors";
import {
    fetchSetLicensing
} from "../../actionCreators";

// Send a generated nonce to the login iframe
function setLoginNonce (username) {
    const clientNonce = (Math.random() + "").substr(2);
    const noncePayload = {
        "event": "init",
        "clientTransactionId": clientNonce,
        "transactionId": "",
        "release": "",
        "platform": "",
        "clientString": "desktop-jupyter",
        "clientID": "",
        "locale": "",
        "profileTier": "",
        "showCreateAccount": false,
        "showRememberMe": false,
        "showLicenseField": false,
        "licenseNo": "",
        "cachedUsername": username,
        "cachedRememberMe": false
    };

    const loginFrame = document.getElementById("loginframe").contentWindow;
    loginFrame.postMessage(JSON.stringify(noncePayload), "*");
}

function initLogin (clientNonce, serverNonce, sourceId) {
    const initPayload = {
        "event": "load",
        "clientTransactionId": clientNonce,
        "transactionId": serverNonce,
        "release": "",
        "platform": "web",
        "clientString": "desktop-jupyter",
        "clientId": "",
        sourceId,
        "profileTier": "MINIMUM",
        "showCreateAccount": false,
        "showRememberMe": false,
        "showLicenseField": false,
        "entitlementId": "",
        "showPrivacyPolicy": true,
        "contextualText": "",
        "legalText": "",
        "cachedIdentifier": "",
        "cachedRememberMe": "",
        "token": "",
        "unauthorized": false
    };

    const loginFrame = document.getElementById("loginframe").contentWindow;
    loginFrame.postMessage(JSON.stringify(initPayload), "*");
}

// Adding a child prop with null as default for improved testability.
function MHLM ({ mhlmLicensingInfo = null }) {
    const dispatch = useDispatch();
    const username = useSelector(selectLicensingMhlmUsername);
    const wsEnv = useSelector(selectWsEnv);
    const matlabVersionOnPath = useSelector(selectMatlabVersionOnPath);

    const [iFrameLoaded, setIFrameLoaded] = useState(false);
    // useState variable to store response from mhlm after authentication
    const [fetchedMhlmLicensingInfo, setFetchedMhlmLicensingInfo] = useState(mhlmLicensingInfo);

    const mhlmLoginHostname = useMemo(
        () => {
            let subdomain = "login";
            if (wsEnv.includes("integ")) {
                subdomain = `${subdomain}-${wsEnv}`;
            }
            return `https://${subdomain}.mathworks.com`;
        },
        [wsEnv]
    );

    // Create random sourceId string
    const sourceId = useState(
        Math.random().toString(36).substring(2, 15) +
        Math.random().toString(36).substring(2, 15)
    )[0];

    useEffect(() => {
        const handler = event => {
            // Only process events that are related to the iframe setup
            if (event.origin === mhlmLoginHostname) {
                const data = JSON.parse(event.data);
                if (data.event === "nonce") {
                    initLogin(
                        data.clientTransactionId,
                        data.transactionId,
                        sourceId
                    );
                } else if (data.event === "login") {
                    const mhlmLicensingInfo = {
                        "type": "mhlm",
                        "token": data.token,
                        "profileId": data.profileId,
                        "emailAddress": data.emailAddress,
                        sourceId
                    };
                    // matlab version is required in subsequent steps on the server side.
                    // If matlab version is available, persist licensing on the server side.
                    // Else, store response from mhlm and render drop down to choose matlab version.
                    if (matlabVersionOnPath) {
                        dispatch(fetchSetLicensing({ ...mhlmLicensingInfo, "matlabVersion": matlabVersionOnPath }));
                    } else {
                        setFetchedMhlmLicensingInfo(mhlmLicensingInfo);
                    }
                }
            }
        };

        window.addEventListener("message", handler);

        // Clean up
        return () => {
            window.removeEventListener("message", handler);
        };
    }, [dispatch, sourceId, mhlmLoginHostname, fetchedMhlmLicensingInfo, matlabVersionOnPath]);

    useEffect(() => {
        if (iFrameLoaded === true) {
            setLoginNonce(username);
        }
    }, [iFrameLoaded, username]);

    const handleIFrameLoaded = () => setIFrameLoaded(true);

    const embeddedLoginUrl = `${mhlmLoginHostname}/embedded-login/v2/login.html`;
    const mhlmIframe = (
        <div id="MHLM">
            <iframe
                id="loginframe"
                title="MathWorks Embedded Login"
                type="text/html"
                height="380"
                width="100%"
                frameBorder="0"
                src={embeddedLoginUrl}
                onLoad={handleIFrameLoaded}
            >
                Sorry your browser does not support inline frames.
            </iframe>
        </div>
    );

    const setLicensingInfo = (userProvidedMatlabVersion) => {
        dispatch(fetchSetLicensing({ ...fetchedMhlmLicensingInfo, "matlabVersion": userProvidedMatlabVersion }));
    };

    // Render MHLM iFrame if not authenticated and matlab version couldn't be determined
    if (fetchedMhlmLicensingInfo && !matlabVersionOnPath) {
        return <MatlabVersionInput callback={setLicensingInfo}/>;
    } else {
        return mhlmIframe;
    }
}
MHLM.propTypes = {
    "mhlmLicensingInfo": PropTypes.object
};
export default MHLM;
