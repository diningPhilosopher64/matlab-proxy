// Copyright 2025 The MathWorks, Inc.

import React, { useState, useCallback } from 'react';
import { useDispatch } from 'react-redux';
import './ExistingLicense.css';

function DeviceOAuth() {
    const dispatch = useDispatch();
    const [deviceInfo, setDeviceInfo] = useState(null);
    const [status, setStatus] = useState('idle'); // idle, authorizing, pending, success, error
    const [errorMessage, setErrorMessage] = useState('');
    const [copied, setCopied] = useState(false);

    const startPolling = useCallback((info) => {
        const poll = async () => {
            try {
                const response = await fetch('./poll_device_token');
                const data = await response.json();

                if (data.status === 'success') {
                    setStatus('success');
                    // Refresh server status to update licensing info
                    dispatch({ type: 'REQUEST_SERVER_STATUS' });
                    // Refresh page to show MATLAB is ready
                    window.location.replace(window.location.href);
                } else if (data.status === 'pending') {
                    // Continue polling every 1 second (backend handles OAuth server interval)
                    setTimeout(poll, 1000);
                } else if (data.status === 'error') {
                    setStatus('error');
                    setErrorMessage(data.error || 'Authorization failed');
                }
            } catch (error) {
                // Network errors - continue polling every 1 second
                setTimeout(poll, 1000);
            }
        };

        // Start first poll after 1 second
        setTimeout(poll, 1000);
    }, [dispatch]);

    const handleStartDeviceFlow = useCallback(async () => {
        setStatus('authorizing');
        setErrorMessage('');

        try {
            const response = await fetch('./device_authorize', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Failed to initiate device authorization');
            }

            const data = await response.json();
            setDeviceInfo(data);
            setStatus('pending');

            // Start polling
            startPolling(data);

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
        if (deviceInfo?.verification_uri_complete) {
            window.open(deviceInfo.verification_uri_complete, '_blank');
        } else if (deviceInfo?.verification_uri) {
            window.open(deviceInfo.verification_uri, '_blank');
        }
    };

    // Format expires_in to minutes and seconds
    const formatTime = (seconds) => {
        if (!seconds) return '10:00';
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    };

    if (status === 'idle') {
        return (
            <div id="DeviceOAuth">
                <form onSubmit={(e) => { e.preventDefault(); handleStartDeviceFlow(); }}>
                    <div className='form-group'>
                        <p>
                            Sign in to your MathWorks Account using the device code flow.
                            This is useful when you cannot open a browser on this device.
                        </p>
                        <br/>
                        <input
                            type="submit"
                            id="submit"
                            value="Start Device Authorization"
                            className="btn btn_color_blue"
                        />
                    </div>
                </form>
            </div>
        );
    }

    if (status === 'authorizing') {
        return (
            <div id="DeviceOAuth">
                <div className="form-group">
                    <p>Initiating device authorization...</p>
                    <div className="loading-spinner"></div>
                </div>
            </div>
        );
    }

    if (status === 'pending' && deviceInfo) {
        return (
            <div id="DeviceOAuth">
                <div className="form-group">
                    <h3>Device Authorization</h3>

                    <div className="device-code-section" style={{
                        background: '#f5f5f5',
                        padding: '20px',
                        borderRadius: '8px',
                        marginBottom: '20px'
                    }}>
                        <p style={{ marginBottom: '15px' }}>
                            <strong>Step 1:</strong> Go to the verification URL and enter the code below
                        </p>

                        <div style={{
                            display: 'flex',
                            gap: '10px',
                            marginBottom: '15px',
                            alignItems: 'center'
                        }}>
                            <div
                                onClick={openVerificationUrl}
                                style={{
                                    flex: 1,
                                    padding: '10px',
                                    background: '#fff',
                                    border: '1px solid #ddd',
                                    borderRadius: '4px',
                                    cursor: 'pointer',
                                    textDecoration: 'underline',
                                    color: '#0076a8'
                                }}
                            >
                                {deviceInfo.verification_uri_complete || deviceInfo.verification_uri}
                            </div>
                            <button
                                onClick={openVerificationUrl}
                                className="btn btn_color_blue"
                                style={{ padding: '10px 20px' }}
                            >
                                Open
                            </button>
                        </div>

                        <p style={{ marginBottom: '10px' }}>
                            <strong>Step 2:</strong> Enter this code
                        </p>

                        <div style={{
                            display: 'flex',
                            gap: '10px',
                            alignItems: 'center',
                            marginBottom: '15px'
                        }}>
                            <div style={{
                                flex: 1,
                                fontSize: '24px',
                                fontWeight: 'bold',
                                letterSpacing: '4px',
                                padding: '15px',
                                background: '#fff',
                                border: '2px solid #0076a8',
                                borderRadius: '4px',
                                textAlign: 'center',
                                fontFamily: 'monospace'
                            }}>
                                {deviceInfo.user_code}
                            </div>
                            <button
                                onClick={copyUserCode}
                                className="btn"
                                style={{
                                    padding: '15px 20px',
                                    background: copied
                                        ? '#4caf50'
                                        : '#f0f0f0'
                                }}
                            >
                                {copied
                                    ? 'Copied!'
                                    : 'Copy'}
                            </button>
                        </div>

                        <div style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            fontSize: '14px',
                            color: '#666'
                        }}>
                            <span>Expires in: {formatTime(deviceInfo.expires_in)}</span>
                            <span>Checking for authorization...</span>
                        </div>
                    </div>

                    <p style={{ fontSize: '14px', color: '#666' }}>
                        Waiting for you to complete authorization in your browser...
                    </p>
                </div>
            </div>
        );
    }

    if (status === 'success') {
        return (
            <div id="DeviceOAuth">
                <div className="form-group">
                    <h3 style={{ color: '#4caf50' }}>Authorization Successful!</h3>
                    <p>
                        You have successfully authenticated. MATLAB will start automatically.
                    </p>
                    <p style={{ marginTop: '15px', fontSize: '14px', color: '#666' }}>
                        You may close this tab and return to MATLAB.
                    </p>
                </div>
            </div>
        );
    }

    if (status === 'error') {
        return (
            <div id="DeviceOAuth">
                <div className="form-group">
                    <h3 style={{ color: '#f44336' }}>Authorization Failed</h3>
                    <p style={{ color: '#f44336', marginBottom: '15px' }}>
                        {errorMessage}
                    </p>
                    <button
                        onClick={() => setStatus('idle')}
                        className="btn btn_color_blue"
                    >
                        Try Again
                    </button>
                </div>
            </div>
        );
    }

    return null;
}

export default DeviceOAuth;