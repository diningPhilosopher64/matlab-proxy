// Copyright 2020-2025 The MathWorks, Inc.

import React, { useState } from 'react';
import MHLM from './MHLM';
import NLM from './NLM';
import ExistingLicense from './ExistingLicense';
import './LicensingGatherer.css';
import OAuth from './OAuth';
import DeviceOAuth from './DeviceOAuth';

function LicensingGatherer () {
    const [activeTab, setActiveTab] = useState('mhlm');

    const handleMhlmTabClick = e => {
        e.preventDefault();
        setActiveTab('mhlm');
    };

    const handleNlmTabClick = e => {
        e.preventDefault();
        setActiveTab('nlm');
    };
    const handleOAuthTabClick = e => {
        e.preventDefault();
        setActiveTab('oauth');
    };
    const handleDeviceOAuthTabClick = e => {
        e.preventDefault();
        setActiveTab('device_oauth');
    };
    const handleExistingLicenseTabClick = e => {
        e.preventDefault();
        setActiveTab('existingLicense');
    };

    const mhlmActive = activeTab === 'mhlm'
        ? 'active'
        : '';
    const oauthActive = activeTab === 'oauth'
        ? 'active'
        : '';
    const deviceOauthActive = activeTab === 'device_oauth'
        ? 'active'
        : '';
    const oauthAriaExpanded = activeTab === 'oauth'
        ? 'true'
        : 'false';
    const deviceOauthAriaExpanded = activeTab === 'device_oauth'
        ? 'true'
        : 'false';
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

    return (
        <div className="modal show" id="setup-dialog" tabIndex="-1" role="dialog" aria-labelledby="setup-dialog-title">
            <div className="modal-dialog modal-dialog-centered" role="document">
                <div className="modal-content">
                    <div className="modal-body">
                        <div className="tab-container">
                            <ul id="setup-tabs" className="nav nav-tabs" role="tablist">
                                <li role="presentation" className={oauthActive}>
                                    <a
                                        href="#oauth"
                                        id="oauth-tab"
                                        onClick={handleOAuthTabClick}
                                        role="tab"
                                        aria-controls="oauth"
                                        aria-expanded={oauthAriaExpanded}>OAuth</a>
                                </li>
                                <li role="presentation" className={deviceOauthActive}>
                                    <a
                                        href="#device_oauth"
                                        id="device-oauth-tab"
                                        onClick={handleDeviceOAuthTabClick}
                                        role="tab"
                                        aria-controls="device_oauth"
                                        aria-expanded={deviceOauthAriaExpanded}>Device Code</a>
                                </li>
                                <li role="presentation" className={mhlmActive}>
                                    <a
                                        href="#mhlm"
                                        id="mhlm-tab"
                                        onClick={handleMhlmTabClick}
                                        role="tab"
                                        aria-controls="mhlm"
                                        aria-expanded={mhlmAriaExpanded}>Online License Manager</a>
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
                            {/* Because the MHLM tab contains an iframe which is slow to load, always render both tabs and select the active one with React */}
                            <div id="setup-tabs-content" className="tab-content">
                                <div role="tabpanel" className={`tab-pane ${oauthActive}`} id="oauth" aria-labelledby="oauth-tab">
                                    <OAuth />
                                </div>
                                <div role="tabpanel" className={`tab-pane ${deviceOauthActive}`} id="device_oauth" aria-labelledby="device-oauth-tab">
                                    <DeviceOAuth />
                                </div>
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
