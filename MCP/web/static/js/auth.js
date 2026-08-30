/**
 * MCP/web/static/js/auth.js
 * Opsmeld Pure Authentication Executor
 * 
 * HARD RULE: Manages Microsoft Entra device flow initiation & polling.
 * Contains ZERO application shell / dashboard navigation logic.
 */

(function (window) {
    'use strict';

    let loginPollTimer = null;

    function stopPolling() {
        if (loginPollTimer) {
            clearInterval(loginPollTimer);
            loginPollTimer = null;
        }
    }

    /**
     * Initiates Microsoft Entra Device Authorization Flow.
     * Returns Promise resolving to flow metadata { status, user_code, verification_uri }.
     */
    function initiateEntraDeviceFlow() {
        stopPolling();
        return fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
            credentials: 'same-origin'
        })
            .then(res => res.json());
    }

    /**
     * Polls GET /api/auth/poll until Microsoft Entra authentication completes or fails.
     * Callbacks:
     *   onSuccess({ token, email, username }): Entra verified & provisioned session created.
     *   onUnprovisioned(): Entra verified but account is NOT provisioned.
     *   onError(errMessage): Polling or authentication error.
     */
    let consecutiveNetworkErrors = 0;
    const MAX_CONSECUTIVE_ERRORS = 5;

    function startEntraPolling(onSuccess, onUnprovisioned, onError) {
        stopPolling();
        consecutiveNetworkErrors = 0;
        loginPollTimer = setInterval(() => {
            fetch('/api/auth/poll', { credentials: 'same-origin' })
                .then(res => {
                    consecutiveNetworkErrors = 0;
                    return res.json();
                })
                .then(pollRes => {
                    if (pollRes.status === 'success' && pollRes.token) {
                        stopPolling();
                        localStorage.setItem('opsmeld_token', pollRes.token);
                        if (typeof onSuccess === 'function') {
                            onSuccess(pollRes);
                        }
                    } else if (pollRes.error === 'ACCOUNT_NOT_PROVISIONED' || pollRes.status === 'pending_approval') {
                        stopPolling();
                        if (typeof onUnprovisioned === 'function') {
                            onUnprovisioned(pollRes);
                        }
                    }
                })
                .catch(err => {
                    consecutiveNetworkErrors++;
                    console.warn(`[AuthExecutor] Poll network warning (${consecutiveNetworkErrors}/${MAX_CONSECUTIVE_ERRORS}):`, err);
                    if (consecutiveNetworkErrors >= MAX_CONSECUTIVE_ERRORS) {
                        stopPolling();
                        if (typeof onError === 'function') {
                            onError(err.message || 'Connection lost. Please check network connection and retry.');
                        }
                    }
                });
        }, 3000);
    }

    // Export OpsmeldAuth API globally
    window.OpsmeldAuth = {
        initiateEntraFlow: initiateEntraDeviceFlow,
        startPolling: startEntraPolling,
        stopPolling: stopPolling
    };

})(window);
