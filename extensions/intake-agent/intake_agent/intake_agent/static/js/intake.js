/**
 * Patient Intake Form Handler
 * Manages form validation, submission, and user interactions
 */

(function() {
    'use strict';

    // DOM Elements
    const form = document.getElementById('intakeForm');
    const submitButton = form?.querySelector('button[type="submit"]');

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    function init() {
        if (!form) {
            console.error('Intake form not found');
            return;
        }

        setupEventListeners();
        console.log('Patient intake form initialized');
    }

    /**
     * Set up all event listeners
     */
    function setupEventListeners() {
        // Form submission
        form.addEventListener('submit', handleSubmit);

        // Real-time validation on blur
        const inputs = form.querySelectorAll('.form-input');
        inputs.forEach(input => {
            input.addEventListener('blur', () => validateField(input));
            input.addEventListener('input', () => clearFieldError(input));
        });

        // Phone number formatting
        const phoneInput = document.getElementById('phone');
        if (phoneInput) {
            phoneInput.addEventListener('input', formatPhoneNumber);
        }
    }

    /**
     * Handle form submission
     */
    async function handleSubmit(event) {
        event.preventDefault();

        // Validate all fields
        if (!validateForm()) {
            return;
        }

        // Get form data
        const formData = getFormData();

        console.log('Form submitted with data:', formData);

        // Disable submit button and show loading state
        setLoadingState(true);

        try {
            // TODO: Implement actual form submission to backend
            // For now, just simulate a delay
            await simulateSubmission(formData);

            showMessage('Thank you! Your information has been received.', 'success');

            // Reset form after successful submission
            setTimeout(() => {
                form.reset();
                hideMessage();
            }, 3000);

        } catch (error) {
            console.error('Submission error:', error);
            showMessage('An error occurred. Please try again.', 'error');
        } finally {
            setLoadingState(false);
        }
    }

    /**
     * Validate the entire form
     */
    function validateForm() {
        const inputs = form.querySelectorAll('.form-input[required]');
        let isValid = true;

        inputs.forEach(input => {
            if (!validateField(input)) {
                isValid = false;
            }
        });

        return isValid;
    }

    /**
     * Validate a single field
     */
    function validateField(input) {
        const value = input.value.trim();
        let errorMessage = '';

        if (!value && input.hasAttribute('required')) {
            errorMessage = 'This field is required';
        } else if (input.type === 'email' && value) {
            if (!isValidEmail(value)) {
                errorMessage = 'Please enter a valid email address';
            }
        } else if (input.type === 'tel' && value) {
            if (!isValidPhone(value)) {
                errorMessage = 'Please enter a valid phone number';
            }
        }

        if (errorMessage) {
            setFieldError(input, errorMessage);
            return false;
        } else {
            clearFieldError(input);
            return true;
        }
    }

    /**
     * Validate email format
     */
    function isValidEmail(email) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(email);
    }

    /**
     * Validate phone format
     */
    function isValidPhone(phone) {
        const cleaned = phone.replace(/\D/g, '');
        return cleaned.length === 10;
    }

    /**
     * Format phone number as user types
     */
    function formatPhoneNumber(event) {
        const input = event.target;
        const value = input.value.replace(/\D/g, '');
        let formatted = '';

        if (value.length > 0) {
            formatted = '(' + value.substring(0, 3);
        }
        if (value.length >= 4) {
            formatted += ') ' + value.substring(3, 6);
        }
        if (value.length >= 7) {
            formatted += '-' + value.substring(6, 10);
        }

        input.value = formatted;
    }

    /**
     * Set error state on a field
     */
    function setFieldError(input, message) {
        const formGroup = input.closest('.form-group');
        if (!formGroup) return;

        input.classList.add('error');

        // Remove existing error message
        const existingError = formGroup.querySelector('.field-error');
        if (existingError) {
            existingError.remove();
        }

        // Add new error message
        const errorElement = document.createElement('span');
        errorElement.className = 'field-error';
        errorElement.textContent = message;
        errorElement.style.color = '#C33';
        errorElement.style.fontSize = '0.875rem';
        errorElement.style.marginTop = '0.25rem';
        formGroup.appendChild(errorElement);
    }

    /**
     * Clear error state from a field
     */
    function clearFieldError(input) {
        const formGroup = input.closest('.form-group');
        if (!formGroup) return;

        input.classList.remove('error');

        const errorElement = formGroup.querySelector('.field-error');
        if (errorElement) {
            errorElement.remove();
        }
    }

    /**
     * Get form data as an object
     */
    function getFormData() {
        const formData = new FormData(form);
        const data = {};

        for (const [key, value] of formData.entries()) {
            data[key] = value.trim();
        }

        return data;
    }

    /**
     * Set loading state on the form
     */
    function setLoadingState(isLoading) {
        if (!submitButton) return;

        submitButton.disabled = isLoading;

        if (isLoading) {
            submitButton.classList.add('loading');
            submitButton.textContent = 'Submitting...';
        } else {
            submitButton.classList.remove('loading');
            submitButton.textContent = 'Continue';
        }
    }

    /**
     * Show a message to the user
     */
    function showMessage(text, type = 'info') {
        // Remove existing message
        hideMessage();

        const messageElement = document.createElement('div');
        messageElement.className = `message ${type} show`;
        messageElement.textContent = text;

        const formSection = document.querySelector('.form-section');
        if (formSection) {
            formSection.insertBefore(messageElement, form);
        }
    }

    /**
     * Hide the message
     */
    function hideMessage() {
        const existingMessage = document.querySelector('.message');
        if (existingMessage) {
            existingMessage.remove();
        }
    }

    /**
     * Simulate form submission (placeholder for actual API call)
     */
    function simulateSubmission(data) {
        return new Promise((resolve) => {
            setTimeout(() => {
                console.log('Simulated submission complete:', data);
                resolve();
            }, 1500);
        });
    }

})();
