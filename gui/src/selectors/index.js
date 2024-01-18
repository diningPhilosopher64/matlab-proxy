// Copyright 2020-2024 The MathWorks, Inc.

import { createSelector } from 'reselect';

export const selectTutorialHidden = state => state.tutorialHidden;
export const selectServerStatus = state => state.serverStatus;
export const selectSessionStatus = state => state.sessionStatus;
export const selectMatlabStatus = state => state.matlab.status;
export const selectMatlabVersionOnPath = state => state.matlab.versionOnPath;
export const selectSupportedMatlabVersions = state => state.matlab.supportedVersions;
export const selectEnvConfig = state => state.envConfig;
export const selectWsEnv = state => state.serverStatus.wsEnv;
export const selectSubmittingServerStatus = state => state.serverStatus.isSubmitting;
export const selectHasFetchedServerStatus = state => state.serverStatus.hasFetched;
export const selectIsFetchingServerStatus = state => state.serverStatus.isFetching;
export const selectLicensingInfo = state => state.serverStatus.licensingInfo;
export const selectServerStatusFetchFailCount = state => state.serverStatus.fetchFailCount;
export const selectLoadUrl = state => state.loadUrl;
export const selectError = state => state.error;
export const selectWarnings = state => state.warnings;
export const selectUseMOS = state => state.useMOS === true;
export const selectUseMRE = state => state.useMRE === true;
export const selectAuthEnabled = state => state.authentication.enabled;
export const selectAuthToken = state => state.authentication.token;
export const selectIsAuthenticated = state => state.authentication.status === true;
export const selectIsActiveClient = state => state.sessionStatus.isActiveClient;
export const selectIsConcurrencyEnabled = state => state.sessionStatus.isConcurrencyEnabled; 
export const selectWasEverActive = state => state.sessionStatus.wasEverActive;
export const selectClientId = state => state.sessionStatus.clientId;

export const statusPeriodInMS = 1000;
export const maxRequestFailCount = 60;

export const selectTriggerPosition = createSelector(
    state => state.triggerPosition,
    pos => pos === null ? undefined : pos
);

export const selectHasFetchedEnvConfig = createSelector(
    selectEnvConfig,
    envConfig => envConfig !== null 
);

export const selectIsError = createSelector(
    selectError,
    error => error !== null
);

// If the client is not active then the session is a concurrent session.
export const selectIsConcurrent = createSelector(
    selectIsActiveClient,
    isActiveClient => !isActiveClient
);

export const selectIsConnectionError = createSelector(
    selectServerStatusFetchFailCount,
    selectIsConcurrencyEnabled,
    selectIsConcurrent,
    (fails, isConcurrencyEnabled, isConcurrent) => {
        if (isConcurrencyEnabled && isConcurrent) {
            return fails >= 1
        }
        return fails >= maxRequestFailCount
    }
);

export const selectMatlabUp = createSelector(
    selectMatlabStatus,
    matlabStatus => matlabStatus === 'up'
);

export const selectMatlabStarting = createSelector(
    selectMatlabStatus,
    matlabStatus => matlabStatus === 'starting'
);

export const selectMatlabStopping = createSelector(
    selectMatlabStatus,
    matlabStatus => matlabStatus === 'stopping'
);

export const selectMatlabDown = createSelector(
    selectMatlabStatus,
    matlabStatus => matlabStatus === 'down'
);

export const selectOverlayHidable = createSelector(
    selectMatlabStatus,
    selectIsError,
    selectAuthEnabled,
    selectIsAuthenticated,
    (matlabStatus, isError, authRequired, isAuthenticated) => ((matlabStatus === 'up') && !isError && (!authRequired || isAuthenticated))
);

export const selectOverlayVisibility = createSelector(
    state => state.overlayVisibility,
    selectMatlabUp,
    selectIsError,
    selectAuthEnabled,
    selectIsAuthenticated,
    (visibility, matlabUp, isError, authRequired, isAuthenticated) => (
        (authRequired && !isAuthenticated) || !matlabUp || visibility || isError
    )
);

export const getFetchAbortController = createSelector(
    selectServerStatus,
    serverStatus => serverStatus.fetchAbortController
);

// If the session is concurrent or if there is a connection error then disable the fetching of data such as get_status.
export const selectFetchStatusPeriod = createSelector(
    selectSubmittingServerStatus,
    selectIsFetchingServerStatus,
    selectIsConcurrencyEnabled,
    selectIsConcurrent,
    (isSubmitting, isFetching, isConcurrencyEnabled, isConcurrent) => {
        if (isSubmitting || isFetching || (isConcurrencyEnabled && isConcurrent)) {
            return null;
        }
        return statusPeriodInMS; // milliseconds
    }
);

export const selectLicensingProvided = createSelector(
    selectLicensingInfo,
    licensingInfo => Object.prototype.hasOwnProperty.call(licensingInfo, 'type')
);

export const selectLicensingIsMhlm = createSelector(
    selectLicensingInfo,
    selectLicensingProvided,
    (licensingInfo, licensingProvided) => licensingProvided && licensingInfo.type === 'mhlm'
);

export const selectLicensingMhlmUsername = createSelector(
    selectLicensingInfo,
    selectLicensingIsMhlm,
    (licensingInfo, isMhlm) => isMhlm ? licensingInfo.emailAddress : ''
);

// Selector to check if the license type is mhlm and entitlements property is not empty
export const selectLicensingMhlmHasEntitlements = createSelector(
    selectLicensingIsMhlm,
    selectLicensingInfo,
    (isMhlm, licensingInfo) => isMhlm && licensingInfo.entitlements && licensingInfo.entitlements.length > 0
);

export const selectIsEntitled = createSelector(
    selectLicensingInfo,
    selectLicensingMhlmHasEntitlements,
    (licensingInfo, entitlementIdInfo) => entitlementIdInfo && licensingInfo.entitlementId
);

// TODO Are these overkill? Perhaps just selecting status would be enough
// TODO Could be used for detected intermediate failures, such as server being
// temporarily inaccessible
export const selectMatlabPending = createSelector(
    selectMatlabStatus,
    matlabStatus => matlabStatus === 'starting'
);

export const selectOverlayVisible = createSelector(
    selectOverlayVisibility,
    selectIsError,
    (visibility, isError) => (visibility || isError)
);

export const selectIsInvalidTokenError = createSelector(
    selectAuthEnabled,
    selectIsAuthenticated,
    selectIsError,
    selectError,
    (authEnabled, isAuthenticated, isError, error) => {
        if ((authEnabled && !isAuthenticated) && isError && error.type === "InvalidTokenError") {
            return true
        }
        return false
    }
)

export const selectInformationDetails = createSelector(
    selectMatlabStatus,
    selectIsError,
    selectError,
    selectAuthEnabled,
    selectIsInvalidTokenError,
    (matlabStatus, isError, error, authEnabled, isInvalidTokenError) => {
        // Check for any errors on the front-end 
        // to see if HTTP Requests are timing out.       
        if (isError && error.statusCode === 408) {
            return {
                icon: 'warning',
                alert: 'warning',
                label: 'Unknown',
            }
        }

        if (isError && authEnabled && isInvalidTokenError) {
            return {
                icon: 'warning',
                alert: 'warning',
                label: 'Invalid Token supplied',
            }
        }

        // Check status of MATLAB for errors
        switch (matlabStatus) {
            case 'up':
                return {
                    label: 'Running',
                    icon: 'success',
                    alert: 'success'
                };
            case 'starting':
                return {
                    label: 'Starting. This may take several minutes.',
                    icon: 'info-reverse',
                    alert: 'info',
                    spinner: true
                };

            case 'stopping':
                return {
                    label: 'Stopping',
                    icon: 'info-reverse',
                    alert: 'info',
                    spinner: true
                };
            case 'down':
                const detail = {
                    label: 'Not running',
                    icon: 'info-reverse',
                    alert: 'info'
                };
                if (isError) {
                    detail.icon = 'error';
                    detail.alert = 'danger';
                }
                return detail;
            default:
                throw new Error(`Unknown MATLAB status: "${matlabStatus}".`);
        }

    }
);
