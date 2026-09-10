// Copyright 2025-2026 The MathWorks, Inc.

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { useInterval } from 'react-use';
import { requestServerStatus } from '../../actionCreators';
import {
    selectMatlabVersionOnPath,
    selectSupportedMatlabVersions
} from '../../selectors';
import './ExistingLicense.css';
import './DeviceOAuth.css';

// Format a whole number of seconds as m:ss for the expiry countdown.
const formatCountdown = (totalSeconds) => {
    const safe = Math.max(0, totalSeconds);
    const minutes = Math.floor(safe / 60);
    const seconds = safe % 60;
    return `${minutes}:${String(seconds).padStart(2, '0')}`;
};

function DeviceOAuth () {
    const dispatch = useDispatch();
    const matlabVersionOnPath = useSelector(selectMatlabVersionOnPath);
    const supportedMatlabVersions = useSelector(selectSupportedMatlabVersions) || [];
    // Default the dropdown to the newest supported version, matching MHLM.
    const [selectedMatlabVersion, setSelectedMatlabVersion] = useState(
        supportedMatlabVersions[supportedMatlabVersions.length - 1] || ''
    );
    const [deviceInfo, setDeviceInfo] = useState(null);
    // checking, idle, authorizing, pending, success, error.
    // Starts as 'checking' because on mount we ask the server whether a device
    // flow is already in progress (it survives page refreshes, which wipe this
    // component's in-memory state) before deciding what to show.
    const [status, setStatus] = useState('checking');
    const [errorMessage, setErrorMessage] = useState('');
    const [isDeviceCodeExpired, setIsDeviceCodeExpired] = useState(false);
    const [copied, setCopied] = useState(false);
    // Seconds left before the device code expires, shown as a live countdown.
    const [remainingSecs, setRemainingSecs] = useState(null);

    // Track the pending poll timeout and whether the component is still mounted
    // so we never call setState after unmount or leak an orphaned poll loop
    // (e.g. when the user closes the modal or switches tabs mid-flow).
    const pollTimeoutRef = useRef(null);
    const mountedRef = useRef(true);
    // Identifies the active poll loop. startPolling() is called from both the
    // mount effect and the Start button; bumping this on each call lets an older
    // loop detect it has been superseded and stop, so only one loop ever runs.
    const pollGenerationRef = useRef(0);
    // Absolute wall-clock deadline (ms) after which we stop polling, derived
    // from the device code's expires_in. Prevents polling forever if the OAuth
    // server goes silent.
    const deadlineRef = useRef(null);

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
            if (pollTimeoutRef.current) {
                clearTimeout(pollTimeoutRef.current);
                pollTimeoutRef.current = null;
            }
        };
    }, []);

    // Tick the expiry countdown once per second while we are polling, reusing
    // the same react-use interval hook the App uses for periodic work. Passing
    // a null delay pauses the interval when we are not polling. The deadline
    // itself is enforced by the poll loop; this only drives the displayed
    // "Expires in" value.
    useInterval(() => {
        if (deadlineRef.current) {
            setRemainingSecs(Math.max(0, Math.round((deadlineRef.current - Date.now()) / 1000)));
        }
    }, status === 'pending' ? 1000 : null);

    // Apply a poll response and return true when polling should continue. The
    // first time we learn a flow is pending, this hydrates the UI (code, URL,
    // countdown) from the fields the server echoes on every pending poll - which
    // is what lets a page refresh mid-flow resume instead of resetting.
    const applyPollData = useCallback((data, responseStatus) => {
        if (!mountedRef.current) { return false; }

        if (data.status === 'success') {
            setStatus('success');
            dispatch(requestServerStatus());
            window.location.replace(window.location.href);
            return false;
        }

        if (data.status === 'pending') {
            // Rehydrate once. deadlineRef is null until we have it, so this runs
            // after a refresh but not on the POST-initiated path (which already
            // seeded deviceInfo and the deadline).
            if (data.user_code && deadlineRef.current === null) {
                setDeviceInfo(data);
                const expiresInSec = data.expires_in || 600;
                deadlineRef.current = Date.now() + expiresInSec * 1000;
                setRemainingSecs(expiresInSec);
            }
            setStatus('pending');
            return true;
        }

        if (data.status === 'idle') {
            // No flow in progress - show the Start screen. Ignore a stale idle if
            // we have locally started a flow (deadline set), e.g. an in-flight
            // mount poll resolving just after the user clicked Start.
            if (deadlineRef.current === null) {
                setStatus('idle');
            }
            return false;
        }

        if (data.status === 'error') {
            setStatus('error');
            setErrorMessage(data.error || 'Authorization failed');
            // poll_device_token reserves 410 Gone for an expired device code.
            setIsDeviceCodeExpired(responseStatus === 410);
            return false;
        }

        return false;
    }, [dispatch]);

    const startPolling = useCallback(() => {
        // Supersede any existing loop, and cancel its pending timeout, so a Start
        // click during the in-flight mount poll doesn't leave two loops running.
        pollGenerationRef.current += 1;
        const generation = pollGenerationRef.current;
        if (pollTimeoutRef.current) {
            clearTimeout(pollTimeoutRef.current);
            pollTimeoutRef.current = null;
        }

        const poll = async () => {
            if (!mountedRef.current || generation !== pollGenerationRef.current) { return; }

            if (deadlineRef.current && Date.now() > deadlineRef.current) {
                setStatus('error');
                setErrorMessage('The code expired before sign-in was completed.');
                setIsDeviceCodeExpired(true);
                return;
            }

            try {
                const response = await fetch('./poll_device_token');
                const data = await response.json();

                if (generation !== pollGenerationRef.current) { return; }

                // Frontend polls every 1 second; the backend rate-limits the
                // actual calls to the OAuth server.
                if (applyPollData(data, response.status)) {
                    pollTimeoutRef.current = setTimeout(poll, 1000);
                }
            } catch (error) {
                // Network errors - keep polling (until the deadline).
                if (mountedRef.current && generation === pollGenerationRef.current) {
                    pollTimeoutRef.current = setTimeout(poll, 1000);
                }
            }
        };
        // Poll immediately so a refresh rehydrates without a visible delay; the
        // backend's smart caching keeps this from hammering the OAuth server.
        poll();
    }, [applyPollData]);

    // On mount, ask the server whether a device flow is already in progress (it
    // survives page refreshes, which wipe this component's state). If so we
    // rehydrate and resume; if not, the server replies "idle" and we fall to the
    // Start screen.
    useEffect(() => {
        startPolling();
    }, [startPolling]);

    // Kick off the device flow. The MATLAB version is required in subsequent steps
    // on the server side, so if it could not be determined we send the version the
    // user chose in the dropdown along with the request - mirroring how MHLM sends
    // matlabVersion with set_licensing_info. The device_code screen is only shown
    // after this returns, so the version is collected before the user code appears.
    const handleStartDeviceFlow = useCallback(async () => {
        setStatus('authorizing');
        setErrorMessage('');
        setIsDeviceCodeExpired(false);

        try {
            const body = matlabVersionOnPath ? {} : { matlabVersion: selectedMatlabVersion };
            const response = await fetch('./device_authorize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Failed to initiate device authorization');
            }

            const data = await response.json();
            setDeviceInfo(data);
            // Stop polling once the device code expires (default 600s).
            const expiresInSec = data.expires_in || 600;
            deadlineRef.current = Date.now() + expiresInSec * 1000;
            // Seed the countdown so it shows immediately, before the first tick.
            setRemainingSecs(expiresInSec);
            setStatus('pending');
            startPolling();
        } catch (error) {
            setStatus('error');
            setErrorMessage(error.message);
            setIsDeviceCodeExpired(false);
        }
    }, [startPolling, matlabVersionOnPath, selectedMatlabVersion]);

    // The "Start Device Authorization" button. If the MATLAB version could not be
    // determined, first route to the version dropdown and collect it; only once the
    // user submits that do we call the device_authorize endpoint. If the version is
    // known, start the flow immediately.
    const handleStartClick = useCallback(() => {
        if (matlabVersionOnPath) {
            handleStartDeviceFlow();
        } else {
            setStatus('select_matlab_version');
        }
    }, [matlabVersionOnPath, handleStartDeviceFlow]);

    const copyUserCode = () => {
        if (deviceInfo?.user_code) {
            navigator.clipboard.writeText(deviceInfo.user_code);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        }
    };

    const openVerificationUrl = () => {
        const url = deviceInfo?.verification_uri_complete || deviceInfo?.verification_uri;
        if (url) { window.open(url, '_blank', 'noopener,noreferrer'); }
    };

    if (status === 'checking') {
        return (
            <div id="DeviceOAuth">
                <div className="device-oauth-checking">
                    <span className="device-oauth-spinner" aria-hidden="true"></span>
                    Waiting for sign-in...
                </div>
            </div>
        );
    }

    // Plain start screen: shown when the version is already known (idle, or while
    // authorizing after the click). The unknown-version case is handled by the
    // dropdown branch below, so it is excluded here even while authorizing.
    if (status === 'idle' || (status === 'authorizing' && matlabVersionOnPath)) {
        return (
            <div id="DeviceOAuth">
                <form aria-label="Device authorization" onSubmit={(e) => { e.preventDefault(); handleStartClick(); }}>
                    <div className='form-group'>
                        <p>Sign in to your MathWorks Account to start MATLAB. You will receive a security code.</p>
                        <br/>
                        <input
                            type="submit"
                            value={status === 'authorizing' ? 'Starting...' : 'Sign in'}
                            className="btn btn_color_blue"
                            disabled={status === 'authorizing'}
                        />
                    </div>
                </form>
            </div>
        );
    }

    // matlab version is required in subsequent steps on the server side. If it
    // could not be determined, collect it here - before the device flow is started
    // and the user code is shown - then start the flow (sending the chosen version)
    // on submit. The 'authorizing' guard keeps the button showing progress while
    // device_authorize is in flight.
    if (status === 'select_matlab_version' || status === 'authorizing') {
        return (
            <div id="DeviceOAuth">
                <form aria-label="Choose MATLAB version" onSubmit={(e) => { e.preventDefault(); handleStartDeviceFlow(); }}>
                    <div className='form-group'>
                        <p>
                            <b>Note</b>: The version of MATLAB could not be determined. Choose the version of MATLAB you are attempting to start.
                        </p>
                        <br/>
                        <select value={selectedMatlabVersion} onChange={(e) => setSelectedMatlabVersion(e.target.value)} disabled={status === 'authorizing'}>
                            {supportedMatlabVersions.map((matlabVersion, index) => (
                                <option key={index} value={matlabVersion}>
                                    {matlabVersion}
                                </option>
                            ))}
                        </select>

                        <br/><br/>

                        <input type="submit" id="startMatlabBtn" value={status === 'authorizing' ? 'Starting...' : 'Proceed'} className="btn btn_color_blue" disabled={status === 'authorizing'} />
                    </div>
                </form>
            </div>
        );
    }

    if (status === 'pending' && deviceInfo) {
        const verificationUrl = deviceInfo.verification_uri_complete || deviceInfo.verification_uri;
        return (
            <div id="DeviceOAuth">
                <h2 id="device-oauth-heading">Finish Signing In</h2>
                <section className="device-oauth-panel" aria-labelledby="device-oauth-heading">
                    <p className="device-oauth-step">
                        <strong>Step 1:</strong> Open this link
                    </p>
                    <div className="device-oauth-row">
                        <div className="device-oauth-url-box">
                            {/* Web Standards (hyp03) prefer links underlined only on
                                hover. These links inherit the app-global underline
                                from site7.min.css; intentionally not overridden here
                                so the device-code tab's links stay consistent with the
                                other licensing tabs. Any fix belongs at the app level. */}
                            <a href={verificationUrl} target="_blank" rel="noopener noreferrer">
                                {verificationUrl}
                            </a>
                        </div>
                        <button type="button" onClick={openVerificationUrl} className="btn btn_color_blue device-oauth-action">Open</button>
                    </div>

                    <p className="device-oauth-step">
                        <strong>Step 2:</strong> Enter this code
                    </p>
                    <div className="device-oauth-row">
                        <code className="device-oauth-code-box">
                            {deviceInfo.user_code}
                        </code>
                        <button type="button" onClick={copyUserCode} className="btn device-oauth-action">
                            {copied ? 'Copied!' : 'Copy'}
                        </button>
                    </div>

                    <div className="device-oauth-footer" aria-live="polite">
                        <span>Code expires in: {remainingSecs === null ? '--:--' : formatCountdown(remainingSecs)}</span>
                    </div>
                </section>

                <p className="device-oauth-waiting">
                    <span className="device-oauth-spinner" aria-hidden="true"></span>
                    Waiting for sign-in...
                </p>
            </div>
        );
    }

    if (status === 'success') {
        return (
            <div id="DeviceOAuth">
                <h2>Authorization Successful</h2>
                <p>MATLAB will start automatically.</p>
            </div>
        );
    }

    if (status === 'error') {
        const errorHeading = isDeviceCodeExpired
            ? 'Code expired'
            : 'Authorization Failed';

        return (
            <div id="DeviceOAuth">
                <h3>{errorHeading}</h3>
                {/* Surface the failure in the same alert treatment the Information
                    panel uses, so the actual error message stands out instead of
                    reading as plain body text. */}
                <div className="error-container alert alert-danger">
                    <p><strong>Error</strong></p>
                    <div className="error-text"><pre style={{ backgroundColor: 'hsla(0,0%,100%,0)', border: 'none', fontFamily: 'inherit', fontSize: '15px' }}>{errorMessage}</pre></div>
                </div>
                <button type="button" onClick={() => setStatus('idle')} className="btn btn_color_blue device-oauth-try-again">Sign in Again</button>
            </div>
        );
    }

    return null;
}

export default DeviceOAuth;
