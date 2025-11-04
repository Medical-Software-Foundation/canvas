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
    function handleSubmit(event) {
        // Validate all fields before allowing submission
        if (!validateForm()) {
            event.preventDefault();
            return;
        }

        // If validation passes, allow the form to submit naturally
        // The form will POST to the action URL specified in the form tag
        console.log('Form validation passed, submitting to server...');
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

})();
