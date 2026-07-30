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

        expect(getByText('Checking sign-in status...')).toBeInTheDocument();
    });

    it('should show the Start screen when the mount poll reports idle', async () => {
        fetchMock.get('./poll_device_token', {
            body: { status: 'idle' },
            headers: { 'content-type': 'application/json' }
        });

        const { getByText } = render(<DeviceOAuth />, { initialState });

        await waitFor(() => {
            expect(getByText('Start Device Authorization')).toBeInTheDocument();
        });
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

        const { getByText, findByText } = render(<DeviceOAuth />, { initialState });

        // Wait for the idle Start screen, then start the flow.
        const startButton = await findByText('Start Device Authorization');
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

        const { getByText, findByText } = render(<DeviceOAuth />, { initialState });

        const startButton = await findByText('Start Device Authorization');
        fireEvent.click(startButton);

        // The error message from the backend should be surfaced.
        const errorMessage = await findByText('Failed to reach OAuth server');
        expect(errorMessage).toBeInTheDocument();
        expect(getByText('Authorization Failed')).toBeInTheDocument();

        // Clicking "Try Again" returns to the Start screen.
        fireEvent.click(getByText('Try Again'));
        expect(getByText('Start Device Authorization')).toBeInTheDocument();
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
            expect(getByText('Device Authorization')).toBeInTheDocument();
        });
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

    it('should show the error screen when the mount poll reports an error', async () => {
        fetchMock.get('./poll_device_token', {
            body: { status: 'error', error: 'Device code expired' },
            headers: { 'content-type': 'application/json' }
        });

        const { getByText } = render(<DeviceOAuth />, { initialState });

        await waitFor(() => {
            expect(getByText('Authorization Failed')).toBeInTheDocument();
            expect(getByText('Device code expired')).toBeInTheDocument();
        });
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
