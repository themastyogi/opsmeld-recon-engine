/**
 * MCP/web/static/js/session.js
 * Opsmeld Pure Session State Resolver & Lifecycle Manager v3.0
 * 
 * HARD RULE: Single canonical owner of session state resolution, token lifecycle, and authenticated navigation.
 */

(function (window) {
    'use strict';

    function getSessionToken() {
        const cookieToken = (document.cookie.match(/(?:^|;\s*)session=([^;]+)/) || [])[1];
        return cookieToken || localStorage.getItem('opsmeld_token') || null;
    }

    function getAuthHeaders() {
        const token = getSessionToken();
        return token ? { 'Authorization': 'Bearer ' + token } : {};
    }

    /**
     * Resolves session state from GET /api/auth/me.
     * Returns Promise resolving to pure state object:
     *   - NO_SESSION: Unauthenticated
     *   - AUTHENTICATED_PROVISIONED: Valid session with access
     *   - AUTHENTICATED_UNPROVISIONED: Authenticated human without Opsmeld tenant entitlement
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

                const mustChange = !!data.must_change_password || (data.user && !!data.user.must_change_password);
                return {
                    status: 'AUTHENTICATED_PROVISIONED',
                    authenticated: true,
                    provisioned: true,
                    must_change_password: mustChange,
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
     * Revokes session on backend, clears local tokens, and navigates to public landing.
     */
    function logout() {
        localStorage.removeItem('opsmeld_token');
        document.cookie = 'session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax';

        return fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'same-origin'
        })
            .then(() => {
                if (typeof window.switchMainView === 'function') {
                    window.switchMainView('public');
                }
                return { status: 'NO_SESSION' };
            })
            .catch(() => {
                if (typeof window.switchMainView === 'function') {
                    window.switchMainView('public');
                }
                return { status: 'NO_SESSION' };
            });
    }

    /**
     * Switches account: Revokes current session, clears tokens, and triggers fresh Entra Device Flow.
     */
    function switchAccount() {
        return logout().then(() => {
            if (window.OpsmeldAuth && typeof window.OpsmeldAuth.startEntraFlow === 'function') {
                window.OpsmeldAuth.startEntraFlow();
            }
        });
    }

    /**
     * Validates session state and opens the Portal workspace (#view-app-shell).
     */
    function continueToPortal() {
        return resolveSessionState().then(state => {
            if (state.status === 'AUTHENTICATED_PROVISIONED') {
                if (state.must_change_password) {
                    if (typeof window.switchMainView === 'function') {
                        window.switchMainView('change-password');
                    }
                } else if (typeof window.switchMainView === 'function') {
                    window.switchMainView('control-tower');
                }
            } else if (state.status === 'AUTHENTICATED_UNPROVISIONED') {
                if (typeof window.switchMainView === 'function') {
                    window.switchMainView('account-not-provisioned');
                }
            } else {
                if (typeof window.switchMainView === 'function') {
                    window.switchMainView('signin');
                }
            }
        });
    }

    // Export OpsmeldSession API globally
    window.OpsmeldSession = {
        getToken: getSessionToken,
        getHeaders: getAuthHeaders,
        resolveState: resolveSessionState,
        logout: logout,
        switchAccount: switchAccount,
        continueToPortal: continueToPortal
    };

})(window);
