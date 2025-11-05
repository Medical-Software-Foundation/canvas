/**
 * Patient Intake Chat Handler
 * Manages chat interface and session management
 */

(function() {
    'use strict';

    // DOM Elements
    const chatMessages = document.getElementById('chatMessages');
    const chatForm = document.getElementById('chatForm');
    const messageInput = document.getElementById('messageInput');
    const sendButton = chatForm?.querySelector('button[type="submit"]');

    // State
    let sessionId = null;
    let signature = null;
    let isWaitingForResponse = false;

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    /**
     * Initialize the chat interface
     */
    async function init() {
        if (!chatForm || !chatMessages || !messageInput) {
            console.error('Required chat elements not found');
            return;
        }

        setupEventListeners();
        await initializeSession();
        console.log('Chat interface initialized');
    }

    /**
     * Set up event listeners
     */
    function setupEventListeners() {
        // Form submission
        chatForm.addEventListener('submit', handleSubmit);

        // Auto-resize input on mobile
        messageInput.addEventListener('input', adjustInputHeight);

        // Prevent form submission when disabled
        sendButton.addEventListener('click', (e) => {
            if (isWaitingForResponse) {
                e.preventDefault();
            }
        });
    }

    /**
     * Initialize session and WebSocket connection
     */
    async function initializeSession() {
        try {
            // Check for existing session ID and signature in localStorage
            const storedSessionId = localStorage.getItem('intake_session_id');
            const storedSignature = localStorage.getItem('intake_signature');

            if (storedSessionId && storedSignature) {
                // Validate existing session
                const response = await fetch(`/plugin-io/api/intake_agent/intake/session/${storedSessionId}`, {
                    headers: {
                        'Authorization': `Signature ${storedSignature}`
                    }
                });
                if (response.ok) {
                    sessionId = storedSessionId;
                    signature = storedSignature;
                    const sessionData = await response.json();

                    // Restore messages from session
                    if (sessionData.messages && sessionData.messages.length > 0) {
                        sessionData.messages.forEach(msg => {
                            addMessage(msg.role, msg.content, false);
                        });
                    }

                    return;
                }
            }

            // Create new session
            const response = await fetch('/plugin-io/api/intake_agent/intake/session', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error('Failed to create session');
            }

            const data = await response.json();
            sessionId = data.session_id;
            signature = data.signature;
            localStorage.setItem('intake_session_id', sessionId);
            localStorage.setItem('intake_signature', signature);

            console.log('Session created:', sessionId);

            // Load initial greeting
            await loadInitialMessage();

        } catch (error) {
            console.error('Error initializing session:', error);
            addMessage('agent', 'Welcome! I apologize, but I\'m having trouble connecting. Please refresh the page to try again.');
        }
    }

    /**
     * Load the initial message from the agent
     */
    async function loadInitialMessage() {
        try {
            showTypingIndicator();

            // Send a "start" message to trigger the agent's greeting
            const response = await fetch(`/plugin-io/api/intake_agent/intake/message/${sessionId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Signature ${signature}`
                },
                body: JSON.stringify({
                    message: '__START__'
                })
            });

            if (!response.ok) {
                throw new Error('Failed to get initial message');
            }

            const data = await response.json();
            hideTypingIndicator();
            addMessage('agent', data.agent_response);

        } catch (error) {
            console.error('Error loading initial message:', error);
            hideTypingIndicator();
            addMessage('agent', 'Hello! How can I help you today?');
        }
    }

    /**
     * Handle form submission
     */
    async function handleSubmit(event) {
        event.preventDefault();

        if (isWaitingForResponse || !sessionId) {
            return;
        }

        const message = messageInput.value.trim();
        if (!message) {
            return;
        }

        // Add user message to chat
        addMessage('user', message);

        // Clear input
        messageInput.value = '';
        adjustInputHeight();

        // Disable input while waiting for response
        setWaitingState(true);
        showTypingIndicator();

        try {
            const response = await fetch(`/plugin-io/api/intake_agent/intake/message/${sessionId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Signature ${signature}`
                },
                body: JSON.stringify({
                    message: message
                })
            });

            if (!response.ok) {
                throw new Error('Failed to send message');
            }

            // Get agent response from the response
            const data = await response.json();
            hideTypingIndicator();
            addMessage('agent', data.agent_response);
            setWaitingState(false);
            messageInput.focus();

        } catch (error) {
            console.error('Error sending message:', error);
            hideTypingIndicator();
            addMessage('agent', 'I apologize, but I encountered an error. Could you please try again?');
            setWaitingState(false);
            messageInput.focus();
        }
    }

    /**
     * Add a message to the chat
     */
    function addMessage(type, content, shouldScroll = true) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}`;

        const bubbleDiv = document.createElement('div');
        bubbleDiv.className = 'message-bubble';
        bubbleDiv.textContent = content;

        messageDiv.appendChild(bubbleDiv);
        chatMessages.appendChild(messageDiv);

        // Scroll to bottom
        if (shouldScroll) {
            scrollToBottom();
        }
    }

    /**
     * Show typing indicator
     */
    function showTypingIndicator() {
        // Remove existing indicator if present
        hideTypingIndicator();

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message agent';
        messageDiv.id = 'typingIndicator';

        const indicatorDiv = document.createElement('div');
        indicatorDiv.className = 'typing-indicator';

        for (let i = 0; i < 3; i++) {
            const dot = document.createElement('div');
            dot.className = 'typing-dot';
            indicatorDiv.appendChild(dot);
        }

        messageDiv.appendChild(indicatorDiv);
        chatMessages.appendChild(messageDiv);

        scrollToBottom();
    }

    /**
     * Hide typing indicator
     */
    function hideTypingIndicator() {
        const indicator = document.getElementById('typingIndicator');
        if (indicator) {
            indicator.remove();
        }
    }

    /**
     * Set waiting state
     */
    function setWaitingState(waiting) {
        isWaitingForResponse = waiting;
        messageInput.disabled = waiting;
        sendButton.disabled = waiting;

        if (waiting) {
            sendButton.classList.add('loading');
        } else {
            sendButton.classList.remove('loading');
        }
    }

    /**
     * Adjust input height for multiline text
     */
    function adjustInputHeight() {
        // Reset height to auto to get the correct scrollHeight
        messageInput.style.height = 'auto';

        // Set height based on content, with a max height
        const maxHeight = 120;
        const newHeight = Math.min(messageInput.scrollHeight, maxHeight);
        messageInput.style.height = newHeight + 'px';
    }

    /**
     * Scroll chat to bottom
     */
    function scrollToBottom() {
        requestAnimationFrame(() => {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        });
    }

})();
