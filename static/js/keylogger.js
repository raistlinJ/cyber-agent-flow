/**
 * Browser Keylogger for CyberAgentFlow
 * Captures all keystrokes within the WebUI for interaction pattern analysis.
 * 
 * Features:
 * - Captures all keydown/keyup events in the browser
 * - Batches uploads to reduce network overhead
 * - Correlates with session data via run_id
 * - Pause/resume capability
 * - Excludes sensitive fields (passwords, API keys) - NOT logged at all
 */

(function() {
    'use strict';

    // Configuration
    const CONFIG = {
        flushInterval: 5000,        // Flush buffer every 5 seconds
        flushThreshold: 50,         // Flush when buffer reaches 50 entries
        endpoint: '/api/keylogger/batch',
        enabled: false,
        paused: false
    };

    // State
    let buffer = [];
    let flushTimer = null;
    let currentRunId = null;
    let sessionId = null;

    /**
     * Generate a unique session ID for this browser session
     */
    function generateSessionId() {
        if (!sessionId) {
            sessionId = 'browser_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
        }
        return sessionId;
    }

    /**
     * Get current timestamp in ISO format
     */
    function getTimestamp() {
        return new Date().toISOString();
    }

    /**
     * Check if a field is sensitive (password, API key, etc.)
     * Returns true if the field should be EXCLUDED from logging
     */
    function isSensitiveField(element) {
        const tag = element.tagName ? element.tagName.toLowerCase() : '';
        const type = (element.type || '').toLowerCase();
        const name = (element.name || '').toLowerCase();
        const id = (element.id || '').toLowerCase();
        const className = (element.className || '').toLowerCase();

        // Check for password fields - COMPLETELY EXCLUDED
        if (type === 'password') return true;

        // Check for sensitive field names/IDs
        const sensitivePatterns = [
            'password', 'pass', 'pwd',
            'api_key', 'apikey', 'api-key', 'api_token', 'apitoken',
            'secret', 'token', 'auth', 'credential',
            'private_key', 'privatekey', 'private-key'
        ];

        const checkString = [name, id, className].join(' ');
        for (const pattern of sensitivePatterns) {
            if (checkString.includes(pattern)) return true;
        }

        return false;
    }

    /**
     * Get window information for the current keystroke
     */
    function getWindowInfo() {
        try {
            return {
                url: window.location.href,
                origin: window.location.origin,
                pathname: window.location.pathname,
                title: document.title || 'Untitled',
                tabId: window.tabId || null  // Custom tab ID if set
            };
        } catch (e) {
            return {
                url: 'unknown',
                origin: 'unknown',
                pathname: 'unknown',
                title: 'unknown',
                tabId: null
            };
        }
    }

    /**
     * Normalize key event to structured data
     */
    function normalizeKeyEvent(event, type) {
        const target = event.target;
        const targetType = target.tagName ? target.tagName.toLowerCase() : 'unknown';
        const inputType = target.type || target.getAttribute('type') || 'text';
        
        // Get window information
        const windowInfo = getWindowInfo();
        
        // Check if this is a sensitive field
        const isSensitive = isSensitiveField(target);

        // If sensitive, return a minimal event without the actual key
        if (isSensitive) {
            return {
                timestamp: getTimestamp(),
                type: type,
                key: '[SENSITIVE]',
                code: '[REDACTED]',
                keyCode: 0,
                keyIdentifier: '[REDACTED]',
                modifiers: {
                    ctrl: event.ctrlKey,
                    shift: event.shiftKey,
                    alt: event.altKey,
                    meta: event.metaKey
                },
                window: windowInfo,
                target: {
                    tag: targetType,
                    id: target.id || null,
                    className: target.className || null,
                    name: target.name || null,
                    inputType: inputType,
                    placeholder: null,  // No placeholder for sensitive fields
                    isSensitive: true
                },
                context: null,  // No context for sensitive fields
                sessionId: generateSessionId(),
                runId: currentRunId,
                note: 'Keystroke excluded - sensitive field (password/API key field)'
            };
        }

        // For non-sensitive fields, capture full context
        return {
            timestamp: getTimestamp(),
            type: type,
            key: event.key,
            code: event.code,
            keyCode: event.keyCode,
            keyIdentifier: event.keyIdentifier,
            modifiers: {
                ctrl: event.ctrlKey,
                shift: event.shiftKey,
                alt: event.altKey,
                meta: event.metaKey
            },
            window: windowInfo,
            target: {
                tag: targetType,
                id: target.id || null,
                className: target.className || null,
                name: target.name || null,
                inputType: inputType,
                placeholder: target.placeholder || null,
                isSensitive: false
            },
            context: {
                caretPosition: getCaretPosition(target),
                selectionStart: target.selectionStart,
                selectionEnd: target.selectionEnd
            },
            sessionId: generateSessionId(),
            runId: currentRunId
        };
    }

    /**
     * Get caret position in an input/textarea
     */
    function getCaretPosition(element) {
        try {
            if (element.selectionStart !== undefined) {
                return element.selectionStart;
            }
        } catch (e) {
            // Ignore errors
        }
        return null;
    }

    /**
     * Add keystroke to buffer and trigger flush if needed
     */
    function addToBuffer(keyData) {
        buffer.push(keyData);

        // Flush if threshold reached
        if (buffer.length >= CONFIG.flushThreshold) {
            flushBuffer();
        }
    }

    /**
     * Flush buffer to server
     */
    async function flushBuffer(force = false) {
        if (buffer.length === 0) return;
        if (!force && (!CONFIG.enabled || CONFIG.paused)) return;

        const dataToSend = [...buffer];
        buffer = [];

        try {
            const response = await fetch(CONFIG.endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    keystrokes: dataToSend,
                    runId: currentRunId,
                    sessionId: generateSessionId()
                })
            });

            if (!response.ok) {
                console.warn('[Keylogger] Failed to flush buffer:', response.status);
                // Re-add data to buffer on failure
                buffer = [...dataToSend, ...buffer];
            }
        } catch (error) {
            console.warn('[Keylogger] Error flushing buffer:', error);
            // Re-add data to buffer on failure
            buffer = [...dataToSend, ...buffer];
        }
    }

    /**
     * Start periodic flush timer
     */
    function startFlushTimer() {
        if (flushTimer) return;
        
        flushTimer = setInterval(() => {
            if (CONFIG.enabled && !CONFIG.paused) {
                flushBuffer();
            }
        }, CONFIG.flushInterval);
    }

    /**
     * Stop periodic flush timer
     */
    function stopFlushTimer() {
        if (flushTimer) {
            clearInterval(flushTimer);
            flushTimer = null;
        }
    }

    /**
     * Event handlers
     */
    function handleKeyDown(event) {
        if (!CONFIG.enabled || CONFIG.paused) return;
        const keyData = normalizeKeyEvent(event, 'press');
        addToBuffer(keyData);
    }

    function handleKeyUp(event) {
        if (!CONFIG.enabled || CONFIG.paused) return;
        const keyData = normalizeKeyEvent(event, 'release');
        addToBuffer(keyData);
    }

    function handleKeyPress(event) {
        // Legacy support - modern browsers use keydown/keyup
        if (!CONFIG.enabled || CONFIG.paused) return;
        const keyData = normalizeKeyEvent(event, 'char');
        addToBuffer(keyData);
    }

    /**
     * Start the browser keylogger
     */
    function start(runId = null) {
        if (CONFIG.enabled) {
            console.log('[Keylogger] Already enabled');
            return;
        }

        currentRunId = runId;
        CONFIG.enabled = true;
        CONFIG.paused = false;

        // Add event listeners
        document.addEventListener('keydown', handleKeyDown, true);
        document.addEventListener('keyup', handleKeyUp, true);
        document.addEventListener('keypress', handleKeyPress, true);

        // Start flush timer
        startFlushTimer();

        console.log('[Keylogger] Browser keylogger started');

        // Notify via custom event
        window.dispatchEvent(new CustomEvent('keylogger:started', {
            detail: { runId: currentRunId }
        }));
    }

    /**
     * Stop the browser keylogger
     */
    async function stop() {
        if (!CONFIG.enabled) return;

        CONFIG.paused = false;

        // Stop flush timer
        stopFlushTimer();

        // Flush remaining buffer before disabling
        await flushBuffer(true);

        CONFIG.enabled = false;

        // Remove event listeners
        document.removeEventListener('keydown', handleKeyDown, true);
        document.removeEventListener('keyup', handleKeyUp, true);
        document.removeEventListener('keypress', handleKeyPress, true);

        console.log('[Keylogger] Browser keylogger stopped');

        // Notify via custom event
        window.dispatchEvent(new CustomEvent('keylogger:stopped', {
            detail: {}
        }));
    }

    /**
     * Pause the browser keylogger
     */
    function pause() {
        if (!CONFIG.enabled || CONFIG.paused) return;
        CONFIG.paused = true;
        console.log('[Keylogger] Browser keylogger paused');
        window.dispatchEvent(new CustomEvent('keylogger:paused', { detail: {} }));
    }

    /**
     * Resume the browser keylogger
     */
    function resume() {
        if (!CONFIG.enabled || !CONFIG.paused) return;
        CONFIG.paused = false;
        console.log('[Keylogger] Browser keylogger resumed');
        window.dispatchEvent(new CustomEvent('keylogger:resumed', { detail: {} }));
    }

    /**
     * Toggle pause/resume
     */
    function togglePause() {
        if (CONFIG.paused) {
            resume();
        } else {
            pause();
        }
    }

    /**
     * Update the current run ID
     */
    function updateRunId(runId) {
        currentRunId = runId;
    }

    /**
     * Get current status
     */
    function getStatus() {
        return {
            enabled: CONFIG.enabled,
            paused: CONFIG.paused,
            runId: currentRunId,
            bufferLength: buffer.length,
            sessionId: generateSessionId()
        };
    }

    /**
     * Get buffer contents (for debugging)
     */
    function getBuffer() {
        return [...buffer];
    }

    /**
     * Clear buffer
     */
    function clearBuffer() {
        buffer = [];
    }

    // Expose API
    window.BrowserKeylogger = {
        start,
        stop,
        pause,
        resume,
        togglePause,
        updateRunId,
        getStatus,
        getBuffer,
        clearBuffer
    };

    // Auto-start when DOM is ready if keylogger is enabled in settings
    document.addEventListener('DOMContentLoaded', () => {
        // Check localStorage for keylogger preference
        const keyloggerEnabled = localStorage.getItem('keylogger:enabled') === 'true';
        if (keyloggerEnabled) {
            // Will be started by main.js when session starts
            console.log('[Keylogger] Browser keylogger ready (awaiting session start)');
        }
    });

})();