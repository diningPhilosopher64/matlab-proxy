// Copyright 2025-2026 The MathWorks, Inc.

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { useInterval } from 'react-use';
import { requestServerStatus } from '../../actionCreators';
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
    const [deviceInfo, setDeviceInfo] = useState(null);
    // checking, idle, authorizing, pending, success, error.
    // Starts as 'checking' because on mount we ask the server whether a device
    // flow is already in progress (it survives page refreshes, which wipe this
    // component's in-memory state) before deciding what to show.
    const [status, setStatus] = useState('checking');
    const [errorMessage, setErrorMessage] = useState('');
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
    const applyPollData = useCallback((data) => {
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
                setErrorMessage('Device code expired. Please try again.');
                return;
            }

            try {
                const response = await fetch('./poll_device_token');
                const data = await response.json();

                if (generation !== pollGenerationRef.current) { return; }

                // Frontend polls every 1 second; the backend rate-limits the
                // actual calls to the OAuth server.
                if (applyPollData(data)) {
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

    const handleStartDeviceFlow = useCallback(async () => {
        setStatus('authorizing');
        setErrorMessage('');

        try {
            const response = await fetch('./device_authorize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
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
        }
    }, [startPolling]);

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
                    Checking sign-in status...
                </div>
            </div>
        );
    }

    if (status === 'idle' || status === 'authorizing') {
        return (
            <div id="DeviceOAuth">
                <form aria-label="Device authorization" onSubmit={(e) => { e.preventDefault(); handleStartDeviceFlow(); }}>
                    <div className='form-group'>
                        <p>Sign in to your MathWorks Account using the device code flow.</p>
                        <br/>
                        <input
                            type="submit"
                            value={status === 'authorizing' ? 'Starting...' : 'Start Device Authorization'}
                            className="btn btn_color_blue"
                            disabled={status === 'authorizing'}
                        />
                    </div>
                </form>
            </div>
        );
    }

    if (status === 'pending' && deviceInfo) {
        const verificationUrl = deviceInfo.verification_uri_complete || deviceInfo.verification_uri;
        return (
            <div id="DeviceOAuth">
                <h2 id="device-oauth-heading">Device Authorization</h2>
                <section className="device-oauth-panel" aria-labelledby="device-oauth-heading">
                    <p className="device-oauth-step">
                        <strong>Step 1:</strong> Go to the verification URL and enter the code below
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
                        <span>Expires in: {remainingSecs === null ? '--:--' : formatCountdown(remainingSecs)}</span>
                        <span className="device-oauth-checking">
                            <span className="device-oauth-spinner" aria-hidden="true"></span>
                            Checking for authorization...
                        </span>
                    </div>
                </section>

                <p className="device-oauth-waiting">Waiting for you to complete authorization in your browser...</p>
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
        return (
            <div id="DeviceOAuth">
                <h2>Authorization Failed</h2>
                <p>{errorMessage}</p>
                <button type="button" onClick={() => setStatus('idle')} className="btn btn_color_blue">Try Again</button>
            </div>
        );
    }

    return null;
}

export default DeviceOAuth;
