/**
 * MCP/web/static/js/auth.js
 * Opsmeld Pure Authentication Controller v3.0
 * 
 * HARD RULE: Single canonical owner of authentication flow execution (Entra Device Flow & Password Login).
 * Manages modal visibility, network interaction, polling timer, and delegates view switching to switchMainView.
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

    function openEntraModal() {
        const modalEl = document.getElementById('login-modal');
        const codeEl = document.getElementById('login-user-code');
        const linkEl = document.getElementById('login-link');

        if (codeEl) codeEl.innerText = 'GENERATING CODE...';
        if (linkEl) linkEl.href = '#';
        if (modalEl) modalEl.style.display = 'flex';
    }

    function closeEntraModal() {
        stopPolling();
        const modalEl = document.getElementById('login-modal');
        if (modalEl) modalEl.style.display = 'none';
    }

    /**
     * Starts the Microsoft Entra Device Authorization Flow.
     * Displays Entra modal, initiates device flow on backend, and polls until complete.
     */
    function startEntraFlow() {
        stopPolling();
        openEntraModal();

        const codeEl = document.getElementById('login-user-code');
        const linkEl = document.getElementById('login-link');

        return fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
            credentials: 'same-origin'
        })
            .then(res => res.json())
            .then(data => {
                if (data.user_code) {
                    if (codeEl) codeEl.innerText = data.user_code;
                    if (linkEl) linkEl.href = data.verification_uri || 'https://login.microsoft.com/device';

                    let pollErrors = 0;
                    loginPollTimer = setInterval(() => {
                        fetch('/api/auth/poll', { credentials: 'same-origin' })
                            .then(res => {
                                pollErrors = 0;
                                return res.json();
                            })
                            .then(pollRes => {
                                if (pollRes.status === 'success' && pollRes.token) {
                                    stopPolling();
                                    localStorage.setItem('opsmeld_token', pollRes.token);
                                    closeEntraModal();
                                    if (typeof window.switchMainView === 'function') {
                                        window.switchMainView('control-tower');
                                    }
                                } else if (pollRes.error === 'ACCOUNT_NOT_PROVISIONED' || pollRes.status === 'pending_approval') {
                                    stopPolling();
                                    closeEntraModal();
                                    if (typeof window.switchMainView === 'function') {
                                        window.switchMainView('account-not-provisioned');
                                    }
                                }
                            })
                            .catch(err => {
                                pollErrors++;
                                console.warn('[AuthController] Poll warning:', err);
                                if (pollErrors >= 10) {
                                    stopPolling();
                                }
                            });
                    }, 3000);
                } else {
                    alert('Unable to initiate Microsoft Entra login: ' + (data.error || JSON.stringify(data)));
                    closeEntraModal();
                }
            })
            .catch(err => {
                console.error('[AuthController] Auth login error:', err);
                alert('Authentication service error: ' + err.message);
                closeEntraModal();
            });
    }

    /**
     * Handles password login form submission on the canonical sign-in card.
     */
    function handlePasswordLogin(event) {
        if (event) event.preventDefault();

        const emailEl = document.getElementById('app-login-email');
        const passEl = document.getElementById('app-login-pass');
        const errEl = document.getElementById('app-login-error');

        const email = emailEl ? emailEl.value.trim() : 'admin@opsmeld.com';
        const password = passEl ? passEl.value : 'password123';

        if (errEl) errEl.style.display = 'none';

        return fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email, password: password }),
            credentials: 'same-origin'
        })
            .then(res => res.json())
            .then(data => {
                if (data.token) {
                    localStorage.setItem('opsmeld_token', data.token);
                    if (typeof window.switchMainView === 'function') {
                        window.switchMainView('control-tower');
                    }
                } else if (data.user_code) {
                    startEntraFlow();
                } else {
                    if (errEl) {
                        errEl.textContent = 'Invalid credentials: ' + (data.error || 'Authentication failed');
                        errEl.style.display = 'block';
                    }
                }
            })
            .catch(err => {
                console.error('[AuthController] Password login error:', err);
                if (errEl) {
                    errEl.textContent = 'Sign in error: ' + err.message;
                    errEl.style.display = 'block';
                }
            });
    }

    // Export OpsmeldAuth API globally
    window.OpsmeldAuth = {
        openModal: openEntraModal,
        closeModal: closeEntraModal,
        startEntraFlow: startEntraFlow,
        handlePasswordLogin: handlePasswordLogin,
        stopPolling: stopPolling
    };

})(window);
