// Copyright 2020-2026 The MathWorks, Inc.

import React from 'react';
import LicenseGatherer from './index';
import { render } from '../../test/utils/react-test';
import { fireEvent } from '@testing-library/react';
import state from '../../test/utils/state';
import MHLM from './MHLM';
import * as actionCreators from '../../actionCreators';
import fetchMock from 'fetch-mock';


const _ = require('lodash');

describe('LicenseGatherer component', () => {
    let initialState;
    beforeEach(() => {
        initialState = _.cloneDeep(state);
    });

    afterEach(() => {
        vi.clearAllMocks();
        fetchMock.restore();
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

        const mhlmTab = container.querySelector('#onlineLicense-tab');

        expect(mhlmTab).toBeInTheDocument();

        fireEvent.click(mhlmTab);

        const iFrame = container.getElementsByTagName('iframe').item(0);

        expect(iFrame.src).toContain(initialState.serverStatus.wsEnv);
    });

    it('should have rendered mhlm tab by default without crashing', () => {
        const { container } = render(<LicenseGatherer />, { initialState });

        const mhlmTab = container.querySelector('#onlineLicense-tab');

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

    it('should render the three-tab MHLM-only layout when online_auth_method is not device_code', () => {
        // Default state's envConfig has no online_auth_method, which the selector
        // treats as 'mhlm'.
        const { container } = render(<LicenseGatherer />, { initialState });

        expect(container.querySelectorAll('#setup-tabs > li')).toHaveLength(3);
        expect(container.querySelector('#deviceOauth-tab')).not.toBeInTheDocument();
        expect(container.querySelector('#deviceOauth')).not.toBeInTheDocument();

        const mhlmTab = container.querySelector('#onlineLicense-tab');
        expect(mhlmTab).toBeInTheDocument();
        expect(mhlmTab.textContent).toBe('Online License Manager');
        expect(container.querySelector('#MHLM')).toBeInTheDocument();
        expect(container.querySelector('.online-experience-switch')).not.toBeInTheDocument();
    });

    it('should render Device OAuth by default in the three-tab Online License Manager layout', async () => {
        initialState.envConfig.online_auth_method = 'device_code';
        fetchMock.get('./poll_device_token', {
            body: { status: 'idle' },
            headers: { 'content-type': 'application/json' }
        });

        const { container, findByRole } = render(<LicenseGatherer />, { initialState });

        expect(container.querySelectorAll('#setup-tabs > li')).toHaveLength(3);
        expect(container.querySelector('#deviceOauth-tab')).not.toBeInTheDocument();
        expect(container.querySelector('#mhlm-tab')).not.toBeInTheDocument();
        expect(container.querySelector('#onlineLicense-tab').textContent).toBe('Online License Manager');
        expect(container.querySelector('#onlineLicense')).toHaveClass('active');
        expect(container.querySelector('#DeviceOAuth')).toBeInTheDocument();
        expect(container.querySelector('#MHLM')).not.toBeInTheDocument();
        expect(await findByRole('button', { name: 'Switch to old experience' })).toBeInTheDocument();
    });

    it('should switch experiences without reloading and retain the choice across tab changes', async () => {
        initialState.envConfig.online_auth_method = 'device_code';
        fetchMock.get('./poll_device_token', {
            body: { status: 'idle' },
            headers: { 'content-type': 'application/json' }
        });

        const { container, findByRole, getByRole } = render(<LicenseGatherer />, { initialState });

        fireEvent.click(await findByRole('button', { name: 'Switch to old experience' }));

        expect(container.querySelector('#DeviceOAuth')).not.toBeInTheDocument();
        expect(container.querySelector('#MHLM')).toBeInTheDocument();

        fireEvent.click(container.querySelector('#nlm-tab'));
        fireEvent.click(container.querySelector('#onlineLicense-tab'));
        expect(container.querySelector('#MHLM')).toBeInTheDocument();

        fireEvent.load(container.querySelector('#loginframe'));
        fireEvent.click(getByRole('button', { name: 'Switch back to new experience' }));

        expect(container.querySelector('#MHLM')).not.toBeInTheDocument();
        expect(container.querySelector('#DeviceOAuth')).toBeInTheDocument();
    });

    it('should resume an active device flow with the remaining server-side lifetime after switching back', async () => {
        initialState.envConfig.online_auth_method = 'device_code';
        let pollCount = 0;
        fetchMock.get('./poll_device_token', () => {
            pollCount += 1;
            return {
                body: {
                    status: 'pending',
                    user_code: 'ABCD-EFGH',
                    verification_uri: 'https://www.mathworks.com/mwlogin',
                    expires_in: pollCount === 1
                        ? 300
                        : 240
                },
                headers: { 'content-type': 'application/json' }
            };
        });

        const { container, findByRole, findByText } = render(<LicenseGatherer />, { initialState });

        expect(await findByText('Code expires in: 5:00')).toBeInTheDocument();
        fireEvent.click(await findByRole('button', { name: 'Switch to old experience' }));

        fireEvent.load(container.querySelector('#loginframe'));
        fireEvent.click(await findByRole('button', { name: 'Switch back to new experience' }));

        expect(await findByText('Code expires in: 4:00')).toBeInTheDocument();
        expect(pollCount).toBeGreaterThanOrEqual(2);
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
