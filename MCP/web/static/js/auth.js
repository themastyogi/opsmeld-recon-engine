/**
 * MCP/web/static/js/auth.js
 * Opsmeld Pure Authentication Controller v3.1
 * 
 * Manages Microsoft Entra authorization flow execution, modal visibility, and polling timers.
 * Scoped password login for admin-provisioned accounts is managed by handleEmailPasswordLogin in index.html.
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
     * Starts the official Microsoft Entra Web Authorization Flow.
     * Navigates directly to login.microsoftonline.com for interactive user login (email input & Authenticator app prompt).
     */
    function startEntraFlow() {
        stopPolling();
        window.location.href = '/api/auth/entra/authorize';
    }

    // Export OpsmeldAuth API globally
    window.OpsmeldAuth = {
        openModal: openEntraModal,
        closeModal: closeEntraModal,
        startEntraFlow: startEntraFlow,
        stopPolling: stopPolling
    };

})(window);
