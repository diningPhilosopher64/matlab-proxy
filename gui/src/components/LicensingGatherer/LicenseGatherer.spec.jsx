// Copyright 2020-2026 The MathWorks, Inc.

import React from 'react';
import LicenseGatherer from './index';
import { render } from '../../test/utils/react-test';
import { fireEvent } from '@testing-library/react';
import state from '../../test/utils/state';
import MHLM from './MHLM';
import * as actionCreators from '../../actionCreators';


const _ = require('lodash');

describe('LicenseGatherer component', () => {
    let initialState;
    beforeEach(() => {
        initialState = _.cloneDeep(state);
    });

    afterEach(() => {
        vi.clearAllMocks();
    });

    it('should render with the default Redux state', () => {
        const { container } = render(<LicenseGatherer />);

        expect(container.querySelector('#setup-dialog')).toBeInTheDocument();
    });

    it('should render without crashing', () => {
        render(<LicenseGatherer />, { initialState });
    });

    it('should render without crashing. Should have a subdomain for mhlmLoginHostName', () => {
        initialState.serverStatus.wsEnv = 'mw-integ';

        const { container } = render(<LicenseGatherer />, { initialState });

        const mhlmTab = container.querySelector('#mhlm-tab');

        expect(mhlmTab).toBeInTheDocument();

        fireEvent.click(mhlmTab);

        const iFrame = container.getElementsByTagName('iframe').item(0);

        expect(iFrame.src).toContain(initialState.serverStatus.wsEnv);
    });

    it('should have rendered mhlm tab by default without crashing', () => {
        const { container } = render(<LicenseGatherer />, { initialState });

        const mhlmTab = container.querySelector('#mhlm-tab');

        expect(mhlmTab).toBeInTheDocument();
        // Click on mhlm Tab
        fireEvent.click(mhlmTab);

        // Check if mhlm iframe is rendered.
        const mhlmTabContent = container.querySelector('#MHLM');
        expect(mhlmTabContent).toBeInTheDocument();
    });

    it('should have rendered mhlm tab with the drop down to choose matlab version and start MATLAB button', () => {
        const mockFetchSetLicensing = vi.spyOn(actionCreators, 'fetchSetLicensing').mockImplementation(() => {
            return () => Promise.resolve();
        });
        // Set matlab version to null for the matlab version drop-down to render
        initialState.matlab.versionOnPath = null;
        initialState.matlab.supportedVersions = ['R2020b', 'R2021a'];
        const fetchedMhlmLicensingInfo = { dummyValue: 'yes' };

        const { container } = render(<MHLM mhlmLicensingInfo={fetchedMhlmLicensingInfo}/>, { initialState });

        const startMatlabBtn = container.querySelector('#startMatlabBtn');

        expect(startMatlabBtn).toBeInTheDocument();

        fireEvent.click(startMatlabBtn);
        mockFetchSetLicensing.mockRestore();
    });

    it('should have rendered nlm tab content without crashing', () => {
        const { container } = render(<LicenseGatherer />, { initialState });

        const nlmTab = container.querySelector('#nlm-tab');
        expect(nlmTab).toBeInTheDocument();

        // Click on nlm Tab
        fireEvent.click(nlmTab);

        // Check if nlm tab is rendered.
        const nlmTabContent = container.querySelector('#NLM');
        expect(nlmTabContent).toBeInTheDocument();
    });

    it('should have rendered existing license tab content without crashing', () => {
        const { container } = render(<LicenseGatherer />, { initialState });

        const existingLicenseTab = container.querySelector('#existingLicense-tab');
        expect(existingLicenseTab).toBeInTheDocument();

        // Click on existingLicense Tab
        fireEvent.click(existingLicenseTab);

        // Check if existingLicense tab is rendered.
        const existingLicenseTabContent = container.querySelector('#existingLicense');
        expect(existingLicenseTabContent).toBeInTheDocument();
    });

    it('should not render the device code (OAuth) tab when online_auth_method is not device_code', () => {
        // Default state's envConfig has no online_auth_method, which the selector
        // treats as 'mhlm'.
        const { container } = render(<LicenseGatherer />, { initialState });

        expect(container.querySelector('#deviceOauth-tab')).not.toBeInTheDocument();
        expect(container.querySelector('#deviceOauth')).not.toBeInTheDocument();

        // The MHLM tab keeps its plain label when the device code tab is absent.
        const mhlmTab = container.querySelector('#mhlm-tab');
        expect(mhlmTab).toBeInTheDocument();
        expect(mhlmTab.textContent).toBe('Online License Manager');
    });

    it('should render the device code (OAuth) tab and make it active by default when online_auth_method is device_code', () => {
        initialState.envConfig.online_auth_method = 'device_code';

        const { container } = render(<LicenseGatherer />, { initialState });

        const deviceOauthTab = container.querySelector('#deviceOauth-tab');
        expect(deviceOauthTab).toBeInTheDocument();

        // The device code panel should be present and active by default.
        const deviceOauthTabContent = container.querySelector('#deviceOauth');
        expect(deviceOauthTabContent).toBeInTheDocument();
        expect(deviceOauthTabContent).toHaveClass('active');

        // When the device code tab is shown, the MHLM tab is relabelled as the
        // browser-based break-glass fallback.
        const mhlmTab = container.querySelector('#mhlm-tab');
        expect(mhlmTab.textContent).toBe('Online License Manager (Classic)');
    });

    it('should switch away from the device code tab to the mhlm tab on click', () => {
        initialState.envConfig.online_auth_method = 'device_code';

        const { container } = render(<LicenseGatherer />, { initialState });

        // Device code tab is active by default.
        expect(container.querySelector('#deviceOauth')).toHaveClass('active');

        const mhlmTab = container.querySelector('#mhlm-tab');
        fireEvent.click(mhlmTab);

        // MHLM tab becomes active and the device code tab is no longer active.
        expect(container.querySelector('#mhlm')).toHaveClass('active');
        expect(container.querySelector('#deviceOauth')).not.toHaveClass('active');
    });

    test.each([
        ['1234', true], ['hostname', true], ['1234hostname', true], ['1234,', true], ['hostname,', true],
        ['1234@hostname', false], ['1234@hostname,4567@hostname', false], ['1234@hostname:4567@hostname', false],
        ['1234@hostname,4567@hostname,456@hostname', false], ['1234@hostname,4567@hostname,456@hostname:789@hostname', false],
        ['789@hostname:1234@hostname,4567@hostname,456@hostname', false], ['789@hostname:1234@hostname,4567@hostname,456@hostname:789@hostname', false]
    ])(
        'Test to check for NLM connection string: %s if the \'disabled\' property of the Submit button is set to %s',
        (NLMConnStr, disabledValue) => {
            const { container } = render(<LicenseGatherer />, { initialState });

            const nlmTab = container.querySelector('#nlm-tab');
            const input = container.querySelector('#nlm-connection-string');
            const submitButton = container.querySelector('#submit');

            expect(nlmTab).toBeInTheDocument();

            // Click on nlm Tab
            fireEvent.click(nlmTab);

            // Check if nlm iframe is rendered.
            const nlmTabContent = container.querySelector('#NLM');
            expect(nlmTabContent).toBeInTheDocument();

            fireEvent.change(input, { target: { value: NLMConnStr } });
            // Check if Submit button is disabled for an invalid nlm connection string
            expect(submitButton.disabled).toBe(disabledValue);
        }
    );
});
