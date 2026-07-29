// Copyright 2020-2025 The MathWorks, Inc.

import React, { useState } from 'react';
import { useSelector } from 'react-redux';
import MHLM from './MHLM';
import NLM from './NLM';
import ExistingLicense from './ExistingLicense';
import DeviceOAuth from './DeviceOAuth';
import { selectOnlineAuthMethod } from '../../selectors';
import './LicensingGatherer.css';

function LicensingGatherer () {
    const onlineAuthMethod = useSelector(selectOnlineAuthMethod);
    const useDeviceCode = onlineAuthMethod === 'device_code';

    // The default online tab is the device code flow when enabled, else MHLM.
    const [activeTab, setActiveTab] = useState(useDeviceCode ? 'deviceOauth' : 'mhlm');

    const handleMhlmTabClick = e => {
        e.preventDefault();
        setActiveTab('mhlm');
    };

    const handleDeviceOauthTabClick = e => {
        e.preventDefault();
        setActiveTab('deviceOauth');
    };

    const handleNlmTabClick = e => {
        e.preventDefault();
        setActiveTab('nlm');
    };
    const handleExistingLicenseTabClick = e => {
        e.preventDefault();
        setActiveTab('existingLicense');
    };

    const mhlmActive = activeTab === 'mhlm'
        ? 'active'
        : '';
    const mhlmAriaExpanded = activeTab === 'mhlm'
        ? 'true'
        : 'false';
    const nlmActive = activeTab === 'nlm'
        ? 'active'
        : '';
    const nlmAriaExpanded = activeTab === 'nlm'
        ? 'true'
        : 'false';
    const existingLicenseActive = activeTab === 'existingLicense'
        ? 'active'
        : '';
    const existingLicenseAriaExpanded = activeTab === 'existingLicense'
        ? 'true'
        : 'false';
    const deviceOauthActive = activeTab === 'deviceOauth'
        ? 'active'
        : '';
    const deviceOauthAriaExpanded = activeTab === 'deviceOauth'
        ? 'true'
        : 'false';
    // When the device code tab is also shown, disambiguate the MHLM tab as the
    // browser-based break-glass option.
    const mhlmTabLabel = useDeviceCode
        ? 'Online License Manager (Browser)'
        : 'Online License Manager';

    return (
        // This licensing modal intentionally has no close/cancel control (cf.
        // dialogs standard dia35): sign-in must complete before the app is
        // usable, so the dialog is non-dismissable by design. Pre-existing
        // behavior shared by all licensing tabs, not specific to device code.
        <div className={`modal show${useDeviceCode ? ' device-oauth-enabled' : ''}`} id="setup-dialog" tabIndex="-1" role="dialog" aria-labelledby="setup-dialog-title">
            <div className="modal-dialog modal-dialog-centered" role="document">
                <div className="modal-content">
                    <div className="modal-body">
                        <div className="tab-container">
                            <ul id="setup-tabs" className="nav nav-tabs" role="tablist">
                                {/* The device code (OAuth) tab is shown only when the
                                    integration supports it; it is the preferred online
                                    sign-in and is active by default. The MHLM tab is
                                    always shown as a break-glass fallback. */}
                                {useDeviceCode && (
                                    <li role="presentation" className={deviceOauthActive}>
                                        <a
                                            href="#deviceOauth"
                                            id="deviceOauth-tab"
                                            onClick={handleDeviceOauthTabClick}
                                            role="tab"
                                            aria-controls="deviceOauth"
                                            aria-expanded={deviceOauthAriaExpanded}>Online License Manager</a>
                                    </li>
                                )}
                                <li role="presentation" className={mhlmActive}>
                                    <a
                                        href="#mhlm"
                                        id="mhlm-tab"
                                        onClick={handleMhlmTabClick}
                                        role="tab"
                                        aria-controls="mhlm"
                                        aria-expanded={mhlmAriaExpanded}>{mhlmTabLabel}</a>
                                </li>
                                <li role="presentation" className={nlmActive}>
                                    <a
                                        href="#nlm"
                                        id="nlm-tab"
                                        onClick={handleNlmTabClick}
                                        role="tab"
                                        aria-controls="nlm"
                                        aria-expanded={nlmAriaExpanded}>Network License Manager</a>
                                </li>
                                <li role="presentation" className={existingLicenseActive}>
                                    <a
                                        href="#existingLicense"
                                        id="existingLicense-tab"
                                        onClick={handleExistingLicenseTabClick}
                                        role="tab"
                                        aria-controls="existingLicense"
                                        aria-expanded={existingLicenseAriaExpanded}>Existing License</a>
                                </li>
                            </ul>
                            {/* The MHLM iframe is slow to load, so it is always rendered
                                (and preloaded) and the active tab is selected with React.
                                The device code (OAuth) panel is rendered only when the
                                integration supports it. NLM and Existing License tabs are
                                always rendered too. */}
                            <div id="setup-tabs-content" className="tab-content">
                                {useDeviceCode && (
                                    <div role="tabpanel" className={`tab-pane ${deviceOauthActive}`} id="deviceOauth" aria-labelledby="deviceOauth-tab">
                                        <DeviceOAuth />
                                    </div>
                                )}
                                <div role="tabpanel" className={`tab-pane ${mhlmActive}`} id="mhlm" aria-labelledby="mhlm-tab">
                                    <MHLM />
                                </div>
                                <div role="tabpanel" className={`tab-pane ${nlmActive}`} id="nlm" aria-labelledby="nlm-tab">
                                    <NLM />
                                </div>
                                <div role="tabpanel" className={`tab-pane ${existingLicenseActive}`} id="existingLicense" aria-labelledby="existingLicense-tab">
                                    <ExistingLicense />
                                </div>
                                <div>
                                    <p id="LicensingGathererNote">
                                        For more details, see&nbsp;
                                        <a
                                            href="https://github.com/mathworks/matlab-proxy/blob/main/MATLAB-Licensing-Info.md"
                                            target="_blank"
                                            rel="noopener noreferrer"
                                        >
                                            MATLAB Licensing information
                                        </a>
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default LicensingGatherer;
