// Copyright 2025-2026 The MathWorks, Inc.

import React from 'react';
import DeviceOAuth from './DeviceOAuth';
import { render } from '../../test/utils/react-test';
import { fireEvent, waitFor } from '@testing-library/react';
import fetchMock from 'fetch-mock';
import state from '../../test/utils/state';

const _ = require('lodash');

describe('DeviceOAuth Component', () => {
    let initialState;

    beforeEach(() => {
        initialState = _.cloneDeep(state);

        // The component navigates via window.location.replace on success. jsdom
        // does not implement navigation, so stub it out to observe the call.
        delete window.location;
        window.location = {
            href: 'http://127.0.0.1/',
            replace: vi.fn()
        };
    });

    afterEach(() => {
        vi.clearAllMocks();
        fetchMock.restore();
    });

    it('should show the checking state on mount before the first poll resolves', () => {
        // Leave the mount poll unresolved so the component stays in 'checking'.
        fetchMock.get('./poll_device_token', new Promise(() => {}));

        const { getByText } = render(<DeviceOAuth />, { initialState });

        expect(getByText('Waiting for sign-in...')).toBeInTheDocument();
    });

    it('should show the Start screen when the mount poll reports idle', async () => {
        fetchMock.get('./poll_device_token', {
            body: { status: 'idle' },
            headers: { 'content-type': 'application/json' }
        });

        const { findByRole } = render(<DeviceOAuth />, { initialState });

        expect(
            await findByRole('button', { name: 'Sign in' })
        ).toBeInTheDocument();
    });

    it('should initiate the device flow and render the code and verification URL on Start', async () => {
        fetchMock.get('./poll_device_token', {
            body: { status: 'idle' },
            headers: { 'content-type': 'application/json' }
        });

        const deviceAuthorizeResponse = {
            user_code: 'ABCD-EFGH',
            verification_uri: 'https://www.mathworks.com/mwlogin',
            verification_uri_complete: 'https://www.mathworks.com/mwlogin?code=ABCD-EFGH',
            expires_in: 600
        };
        fetchMock.post('./device_authorize', {
            body: deviceAuthorizeResponse,
            headers: { 'content-type': 'application/json' }
        });

        const { getByText, findByRole } = render(<DeviceOAuth />, { initialState });

        // Wait for the idle Start screen, then start the flow.
        const startButton = await findByRole('button', { name: 'Sign in' });
        fireEvent.click(startButton);

        await waitFor(() => {
            expect(fetchMock.called('./device_authorize')).toBe(true);
            expect(getByText('ABCD-EFGH')).toBeInTheDocument();
            expect(getByText(deviceAuthorizeResponse.verification_uri_complete)).toBeInTheDocument();
        });
    });

    it('should surface an error and allow retrying when device_authorize fails', async () => {
        fetchMock.get('./poll_device_token', {
            body: { status: 'idle' },
            headers: { 'content-type': 'application/json' }
        });

        fetchMock.post('./device_authorize', {
            status: 500,
            body: { error: 'Failed to reach OAuth server' },
            headers: { 'content-type': 'application/json' }
        });

        const { getByRole, getByText, findByRole, findByText } = render(<DeviceOAuth />, { initialState });

        const startButton = await findByRole('button', { name: 'Sign in' });
        fireEvent.click(startButton);

        // The error message from the backend should be surfaced.
        const errorMessage = await findByText('Failed to reach OAuth server');
        expect(errorMessage).toBeInTheDocument();
        expect(getByText('Authorization Failed')).toBeInTheDocument();

        // The message must render inside the alert-danger container (same
        // treatment as the Information panel) so the error stands out.
        expect(errorMessage.closest('.alert.alert-danger')).not.toBeNull();

        // Clicking "Sign in Again" returns to the Start screen.
        fireEvent.click(getByRole('button', { name: 'Sign in Again' }));
        expect(getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    });

    it('should rehydrate the pending flow from a poll response after a refresh', async () => {
        // Simulates a page refresh mid-flow: the mount poll immediately reports a
        // pending flow, and the component rehydrates the code/URL from it.
        fetchMock.get('./poll_device_token', {
            body: {
                status: 'pending',
                user_code: 'WXYZ-1234',
                verification_uri: 'https://www.mathworks.com/mwlogin',
                verification_uri_complete: 'https://www.mathworks.com/mwlogin?code=WXYZ-1234',
                expires_in: 300
            },
            headers: { 'content-type': 'application/json' }
        });

        const { getByText } = render(<DeviceOAuth />, { initialState });

        await waitFor(() => {
            expect(getByText('WXYZ-1234')).toBeInTheDocument();
            expect(getByText('Finish Signing In')).toBeInTheDocument();
        });
    });

    it('should show the spinner beside the waiting-for-sign-in message while pending', async () => {
        fetchMock.get('./poll_device_token', {
            body: {
                status: 'pending',
                user_code: 'WXYZ-1234',
                verification_uri: 'https://www.mathworks.com/mwlogin',
                expires_in: 300
            },
            headers: { 'content-type': 'application/json' }
        });

        const { findByText, getByText, queryByText } = render(<DeviceOAuth />, { initialState });

        await findByText('WXYZ-1234');
        const waitingMessage = getByText('Waiting for sign-in...');
        expect(waitingMessage.querySelector('.device-oauth-spinner')).not.toBeNull();
        expect(queryByText('Waiting for you to complete authorization in your browser...')).not.toBeInTheDocument();
        expect(queryByText('Checking for authorization...')).not.toBeInTheDocument();
    });

    it('should show the success screen and navigate when the poll reports success', async () => {
        fetchMock.get('./poll_device_token', {
            body: { status: 'success' },
            headers: { 'content-type': 'application/json' }
        });

        const { getByText } = render(<DeviceOAuth />, { initialState });

        await waitFor(() => {
            expect(getByText('Authorization Successful')).toBeInTheDocument();
            expect(window.location.replace).toHaveBeenCalled();
        });
    });

    it('should show the code-expired heading when the mount poll reports device code expiry', async () => {
        fetchMock.get('./poll_device_token', {
            status: 410,
            body: { status: 'error', error: 'The authorization request is no longer valid' },
            headers: { 'content-type': 'application/json' }
        });

        const { getByText } = render(<DeviceOAuth />, { initialState });

        await waitFor(() => {
            expect(getByText('Code expired')).toBeInTheDocument();
            expect(getByText('The authorization request is no longer valid')).toBeInTheDocument();
        });
        expect(() => getByText('Authorization Failed')).toThrow();
    });

    it('should keep the authorization-failed heading for other poll errors', async () => {
        fetchMock.get('./poll_device_token', {
            status: 502,
            body: { status: 'error', error: 'Failed to reach OAuth server' },
            headers: { 'content-type': 'application/json' }
        });

        const { getByText } = render(<DeviceOAuth />, { initialState });

        await waitFor(() => {
            expect(getByText('Authorization Failed')).toBeInTheDocument();
            expect(getByText('Failed to reach OAuth server')).toBeInTheDocument();
        });
        expect(() => getByText('Code expired')).toThrow();
    });

    it('should copy the user code to the clipboard when Copy is clicked', async () => {
        const writeText = vi.fn();
        Object.defineProperty(navigator, 'clipboard', {
            value: { writeText },
            configurable: true
        });

        fetchMock.get('./poll_device_token', {
            body: {
                status: 'pending',
                user_code: 'WXYZ-1234',
                verification_uri: 'https://www.mathworks.com/mwlogin',
                expires_in: 300
            },
            headers: { 'content-type': 'application/json' }
        });

        const { getByText, findByText } = render(<DeviceOAuth />, { initialState });

        const copyButton = await findByText('Copy');
        fireEvent.click(copyButton);

        expect(writeText).toHaveBeenCalledWith('WXYZ-1234');
        // The button label flips to a confirmation once copied.
        await waitFor(() => {
            expect(getByText('Copied!')).toBeInTheDocument();
        });
    });

    it('should prompt for the MATLAB version before starting the flow when it could not be determined', async () => {
        // Version unknown => clicking Start must NOT hit device_authorize yet;
        // it should route to the version dropdown first (mirroring MHLM).
        initialState.matlab.versionOnPath = null;

        fetchMock.get('./poll_device_token', {
            body: { status: 'idle' },
            headers: { 'content-type': 'application/json' }
        });
        fetchMock.post('./device_authorize', {
            body: { user_code: 'ABCD-EFGH', verification_uri: 'https://www.mathworks.com/mwlogin', expires_in: 600 },
            headers: { 'content-type': 'application/json' }
        });

        const { getByText, findByRole } = render(<DeviceOAuth />, { initialState });

        const startButton = await findByRole('button', { name: 'Sign in' });
        fireEvent.click(startButton);

        // The dropdown screen appears; device_authorize has NOT been called yet.
        await waitFor(() => {
            expect(getByText(/version of MATLAB could not be determined/)).toBeInTheDocument();
        });
        expect(fetchMock.called('./device_authorize')).toBe(false);
        // The user code screen is not shown yet either.
        expect(() => getByText('ABCD-EFGH')).toThrow();
    });

    it('should send the selected MATLAB version to device_authorize on Proceed', async () => {
        initialState.matlab.versionOnPath = null;
        initialState.matlab.supportedVersions = ['R2020b', 'R2023b'];

        fetchMock.get('./poll_device_token', {
            body: { status: 'idle' },
            headers: { 'content-type': 'application/json' }
        });
        fetchMock.post('./device_authorize', {
            body: {
                user_code: 'ABCD-EFGH',
                verification_uri: 'https://www.mathworks.com/mwlogin',
                verification_uri_complete: 'https://www.mathworks.com/mwlogin?code=ABCD-EFGH',
                expires_in: 600
            },
            headers: { 'content-type': 'application/json' }
        });

        const { getByText, getByRole, findByRole } = render(<DeviceOAuth />, { initialState });

        fireEvent.click(await findByRole('button', { name: 'Sign in' }));

        // Choose a version on the dropdown screen, then Proceed.
        const dropdown = await waitFor(() => getByRole('combobox'));
        fireEvent.change(dropdown, { target: { value: 'R2020b' } });
        fireEvent.click(getByText('Proceed'));

        // device_authorize is called now, carrying the chosen version, and the user
        // code screen follows.
        await waitFor(() => {
            expect(fetchMock.called('./device_authorize')).toBe(true);
            expect(getByText('ABCD-EFGH')).toBeInTheDocument();
        });
        const [, options] = fetchMock.lastCall('./device_authorize');
        expect(JSON.parse(options.body)).toEqual({ matlabVersion: 'R2020b' });
    });

    it('should not prompt for the version when it was determined on startup', async () => {
        // versionOnPath is set in the default test state, so clicking Start goes
        // straight to device_authorize with an empty body.
        fetchMock.get('./poll_device_token', {
            body: { status: 'idle' },
            headers: { 'content-type': 'application/json' }
        });
        fetchMock.post('./device_authorize', {
            body: { user_code: 'ABCD-EFGH', verification_uri: 'https://www.mathworks.com/mwlogin', expires_in: 600 },
            headers: { 'content-type': 'application/json' }
        });

        const { getByText, findByRole } = render(<DeviceOAuth />, { initialState });

        fireEvent.click(await findByRole('button', { name: 'Sign in' }));

        await waitFor(() => {
            expect(fetchMock.called('./device_authorize')).toBe(true);
            expect(getByText('ABCD-EFGH')).toBeInTheDocument();
        });
        const [, options] = fetchMock.lastCall('./device_authorize');
        expect(JSON.parse(options.body)).toEqual({});
    });

    it('should open the verification URL in a new tab when Open is clicked', async () => {
        const openMock = vi.spyOn(window, 'open').mockImplementation(() => {});

        fetchMock.get('./poll_device_token', {
            body: {
                status: 'pending',
                user_code: 'WXYZ-1234',
                verification_uri: 'https://www.mathworks.com/mwlogin',
                verification_uri_complete: 'https://www.mathworks.com/mwlogin?code=WXYZ-1234',
                expires_in: 300
            },
            headers: { 'content-type': 'application/json' }
        });

        const { findByText } = render(<DeviceOAuth />, { initialState });

        const openButton = await findByText('Open');
        fireEvent.click(openButton);

        expect(openMock).toHaveBeenCalledWith(
            'https://www.mathworks.com/mwlogin?code=WXYZ-1234',
            '_blank',
            'noopener,noreferrer'
        );

        openMock.mockRestore();
    });
});
