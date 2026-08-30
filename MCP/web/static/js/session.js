/**
 * MCP/web/static/js/session.js
 * Opsmeld Pure Session State Resolver
 * 
 * HARD RULE: This file contains ZERO UI navigation logic (no switchMainView, no window.location).
 * It resolves session state from the backend and manages token storage.
 */

(function (window) {
    'use strict';

    function getSessionToken() {
        const cookieToken = (document.cookie.match(/(?:^|;\s*)session=([^;]+)/) || [])[1];
        return localStorage.getItem('opsmeld_token') || cookieToken || null;
    }

    function getAuthHeaders() {
        const token = getSessionToken();
        return token ? { 'Authorization': 'Bearer ' + token } : {};
    }

    /**
     * Resolves Opsmeld Session State from GET /api/auth/me.
     * Returns a Promise resolving to pure state object.
     */
    function resolveSessionState() {
        const token = getSessionToken();
        if (!token) {
            return Promise.resolve({
                status: 'NO_SESSION',
                authenticated: false,
                provisioned: false,
                user: null,
                organization: null
            });
        }

        return fetch('/api/auth/me', {
            headers: getAuthHeaders(),
            credentials: 'same-origin'
        })
            .then(res => res.json())
            .then(data => {
                if (!data.authenticated) {
                    localStorage.removeItem('opsmeld_token');
                    return {
                        status: 'NO_SESSION',
                        authenticated: false,
                        provisioned: false,
                        user: null,
                        organization: null
                    };
                }

                if (data.provisioned === false || data.status === 'ACCOUNT_NOT_PROVISIONED') {
                    return {
                        status: 'AUTHENTICATED_UNPROVISIONED',
                        authenticated: true,
                        provisioned: false,
                        user: data.user || { email: 'unprovisioned@opsmeld.com', display_name: 'Unprovisioned User' },
                        organization: null
                    };
                }

                return {
                    status: 'AUTHENTICATED_PROVISIONED',
                    authenticated: true,
                    provisioned: true,
                    user: data.user || { email: data.email, display_name: data.username },
                    organization: data.organization || null,
                    roles: data.roles || [],
                    permissions: data.permissions || [],
                    allowed_companies: data.allowed_companies || []
                };
            })
            .catch(err => {
                console.error('[SessionResolver] Network error:', err);
                return {
                    status: 'NO_SESSION',
                    authenticated: false,
                    provisioned: false,
                    user: null,
                    organization: null,
                    error: err.message
                };
            });
    }

    /**
     * Revokes active Opsmeld session on backend and clears local token state.
     */
    function performAppLogout() {
        localStorage.removeItem('opsmeld_token');
        document.cookie = 'session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax';

        return fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'same-origin'
        })
            .then(() => ({ status: 'NO_SESSION' }))
            .catch(() => ({ status: 'NO_SESSION' }));
    }

    /**
     * Revokes current session to prepare for a fresh authentication attempt with another account.
     */
    function switchAccount() {
        return performAppLogout();
    }

    // Export OpsmeldSession API globally
    window.OpsmeldSession = {
        getToken: getSessionToken,
        getHeaders: getAuthHeaders,
        resolveState: resolveSessionState,
        logout: performAppLogout,
        switchAccount: switchAccount
    };

})(window);
