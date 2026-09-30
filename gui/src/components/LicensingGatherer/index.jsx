// Copyright 2020-2026 The MathWorks, Inc.

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

    const [activeTab, setActiveTab] = useState('onlineLicense');
    // Device OAuth is the default experience when the integration supports it.
    // Keep this separate from activeTab so the choice survives visits to the NLM
    // and Existing License tabs for the lifetime of this non-dismissable modal.
    const [onlineExperience, setOnlineExperience] = useState('deviceOauth');
    const activeOnlineExperience = useDeviceCode
        ? onlineExperience
        : 'mhlm';

    const handleOnlineLicenseTabClick = e => {
        e.preventDefault();
        setActiveTab('onlineLicense');
    };

    const handleNlmTabClick = e => {
        e.preventDefault();
        setActiveTab('nlm');
    };
    const handleExistingLicenseTabClick = e => {
        e.preventDefault();
        setActiveTab('existingLicense');
    };
    const handleSwitchToOldExperience = () => setOnlineExperience('mhlm');
    const handleSwitchToNewExperience = () => setOnlineExperience('deviceOauth');
    const switchToNewExperience = useDeviceCode
        ? handleSwitchToNewExperience
        : null;

    const onlineLicenseActive = activeTab === 'onlineLicense'
        ? 'active'
        : '';
    const onlineLicenseAriaExpanded = activeTab === 'onlineLicense'
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
                                <li role="presentation" className={onlineLicenseActive}>
                                    <a
                                        href="#onlineLicense"
                                        id="onlineLicense-tab"
                                        onClick={handleOnlineLicenseTabClick}
                                        role="tab"
                                        aria-controls="onlineLicense"
                                        aria-expanded={onlineLicenseAriaExpanded}>Online License Manager</a>
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
                            <div id="setup-tabs-content" className="tab-content">
                                <div role="tabpanel" className={`tab-pane ${onlineLicenseActive}`} id="onlineLicense" aria-labelledby="onlineLicense-tab">
                                    {activeOnlineExperience === 'deviceOauth'
                                        ? <DeviceOAuth onSwitchToOldExperience={handleSwitchToOldExperience} />
                                        : <MHLM onSwitchToNewExperience={switchToNewExperience} />}
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
                                            MATLAB Licensing information (GitHub)
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
