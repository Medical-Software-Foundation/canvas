"""SimpleAPI for admin and patient views."""
import json
import re
from http import HTTPStatus
from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api

from patient_notify.services.config import CampaignConfig, load_config, patch_config, save_config


_CUSTOM_VAR_KEY_RE = re.compile(r"^[a-zA-Z0-9_]+$")
_SEND_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class NotificationAPI(StaffSessionAuthMixin, SimpleAPI):
    """API endpoints for admin configuration and notification history."""

    PREFIX = ""

    @api.get("/admin")
    def get_admin_page(self) -> list[Response | Effect]:
        """Serve admin configuration page."""
        html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Patient Notifications Admin</title>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Lato:400,700,400italic,700italic&subset=latin">
    <style>
        :root {
            --color-text: rgba(0, 0, 0, 0.87);
            --color-text-active: rgba(0, 0, 0, 0.95);
            --color-text-muted: #767676;
            --color-primary: #22BA45;
            --color-secondary: #2185D0;
            --color-danger: #BD0B00;
            --color-warning: #ED4A0B;
            --color-accent-brown: #935330;
            --color-bg: #F5F5F5;
            --color-border: #E9E9E9;
            --color-surface: #FFFFFF;
            --color-error-bg: #fff6f6;
            --color-error-border: #e0b4b4;
            --color-error-text: #9f3a38;
            --font-family: lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            --font-size-base: 16px;
            --font-size-label: .92857143em;
            --font-size-input: 1em;
            --line-height-base: 1.4285em;
            --line-height-label: 1em;
            --font-weight-bold: 700;
            --space-mini: 4px;
            --space-tiny: 8px;
            --space-small: 12px;
            --space-medium: 16px;
            --space-large: 20px;
            --space-huge: 24px;
            --radius: .28571429rem;
            --border-width: 1px;
            --border-color: var(--color-border);
            --transition-fast: 200ms;
            --transition-base: 250ms;
            --input-padding: .67857143em 1em;
            --input-line-height: 1.21428571em;
            --input-border: 1px solid rgba(34, 36, 38, 0.15);
            --input-focus-border: #85b7d9;
            --input-placeholder: rgba(191, 191, 191, 0.87);
            --input-focus-placeholder: rgba(115, 115, 115, 0.87);
            --input-transition: 0.1s ease;
            --btn-padding: .67857143em 1.5em;
            --btn-padding-sm: .58928571em 1.125em;
            --btn-font-size: 1rem;
            --btn-font-size-sm: .92857143rem;
            --btn-padding-xs: .5em .85714286em;
            --btn-font-size-xs: .78571429rem;
            --row-positive-bg: #fcfff5;
            --row-positive-text: #2c662d;
            --row-warning-bg: #fffaf3;
            --row-warning-text: #573a08;
            --row-negative-bg: #fff6f6;
            --row-negative-text: #9f3a38;
            --row-active-bg: #e0e0e0;
            --table-header-bg: #f9fafb;
            --table-border: rgba(34, 36, 38, 0.1);
            --checkbox-size: 15px;
            --checkbox-border: 1px solid #d4d4d5;
            --checkbox-radius: .21428571rem;
            --checkbox-hover-border: rgba(34, 36, 38, 0.35);
            --checkbox-focus-border: #96c8da;
            --checkbox-check-color: var(--color-text-active);
            --checkbox-label-offset: 1.85714em;
            --tab-padding: .85714286em 1.14285714em;
            --tab-font-size: 1em;
            --tab-line-height: 1em;
            --tab-color: var(--color-text);
            --tab-active-color: var(--color-text-active);
            --tab-active-weight: 700;
            --tab-border: 2px solid rgba(34, 36, 38, 0.15);
            --tab-active-border: 2px solid rgb(27, 28, 29);
            --tab-margin-bottom: var(--space-medium);
            --tab-badge-font-size: .71428571em;
            --tab-badge-padding: .21428571em .5625em;
            --tab-badge-color: #767676;
            --tab-badge-border: 1px solid #767676;
            --tab-badge-radius: .28571429rem;
            --tab-badge-margin-left: .71428571em;
            --radio-size: 13px;
            --radio-border: 1px solid #d4d4d5;
            --radio-hover-border: rgba(34, 36, 38, 0.35);
            --radio-focus-border: #96c8da;
            --radio-dot-color: var(--color-text);
            --radio-dot-scale: scale(.53846154);
            --radio-label-offset: 1.85714em;
            --dropdown-padding: .67857143em 2.1em .67857143em 1em;
            --dropdown-border: 1px solid rgba(34, 36, 38, 0.15);
            --dropdown-focus-border: #96c8da;
            --dropdown-shadow: 0 2px 3px 0 rgba(34, 36, 38, 0.15);
            --dropdown-arrow-right: 1em;
            --dropdown-arrow-color: rgba(0, 0, 0, 0.8);
            --dropdown-menu-max-height: 16.02857143em;
            --dropdown-item-padding: .78571429em 1.14285714em;
            --dropdown-item-separator: 1px solid #fafafa;
            --dropdown-item-hover-bg: rgba(0, 0, 0, 0.05);
            --dropdown-item-selected-bg: rgba(0, 0, 0, 0.05);
            --dropdown-item-selected-color: var(--color-text-active);
            --tooltip-bg: var(--color-surface);
            --tooltip-color: var(--color-text);
            --tooltip-border: 1px solid #d4d4d5;
            --tooltip-padding: .833em 1em;
            --tooltip-shadow: 0 2px 4px 0 rgba(34, 36, 38, 0.12), 0 2px 10px 0 rgba(34, 36, 38, 0.15);
            --tooltip-arrow-size: .71428571em;
            --divider-border: 1px solid rgba(34, 36, 38, 0.15);
            --divider-margin: 1rem 0;
            --skeleton-bg: #e9e9e9;
            --skeleton-shine: #f5f5f5;
            --accordion-title-padding: 7px 0;
            --accordion-title-color: var(--color-text);
            --accordion-content-padding: 7px 0;
            --accordion-icon-size: 1.125em;
            --accordion-icon-transition: transform 0.1s ease;
            --accordion-styled-title-padding: .75em 1em;
            --accordion-styled-title-color: rgba(0, 0, 0, 0.4);
            --accordion-styled-title-active-color: var(--color-text);
            --accordion-styled-title-border: 1px solid rgba(34, 36, 38, 0.15);
            --accordion-styled-content-padding: .5em 1em 1.5em;
            --accordion-styled-shadow: 0 1px 2px 0 rgba(34, 36, 38, 0.15), 0 0 0 1px rgba(34, 36, 38, 0.15);
            --card-bg: var(--color-surface);
            --card-shadow: 0 1px 3px 0 #d4d4d5, 0 0 0 1px #d4d4d5;
            --card-hover-shadow: 0 1px 3px 0 #bcbdbd, 0 0 0 1px #d4d4d5;
            --card-padding: var(--space-medium);
            --spinner-size: 24px;
            --toggle-width: 3.5rem;
            --toggle-height: 1.5rem;
            --toggle-thumb-size: 1.5rem;
            --toggle-checked-offset: 2.15rem;
            --toggle-track-inactive: rgba(0, 0, 0, 0.05);
            --toggle-track-inactive-hover: rgba(0, 0, 0, 0.15);
            --toggle-track-active: var(--color-secondary);
            --toggle-thumb-shadow: 0 1px 2px 0 rgba(34, 36, 38, 0.15), 0 0 0 1px rgba(34, 36, 38, 0.15) inset;
        }
        body {
            font-family: var(--font-family);
            font-size: var(--font-size-base);
            line-height: var(--line-height-base);
            margin: 0;
            padding: 0;
            background: var(--color-bg);
            color: var(--color-text);
        }
        .container {
            min-height: 100vh;
            background: var(--color-surface);
            display: flex;
            flex-direction: column;
        }
        .tab-menu {
            display: flex;
            border-bottom: var(--tab-border);
            position: sticky;
            top: 0;
            background: var(--color-surface);
            z-index: 20;
        }
        .tab-item {
            position: relative;
            display: inline-flex;
            align-items: center;
            gap: var(--space-tiny);
            padding: var(--tab-padding);
            font-size: var(--tab-font-size);
            font-weight: var(--tab-active-weight);
            font-family: var(--font-family);
            line-height: var(--tab-line-height);
            color: transparent;
            cursor: pointer;
            border: none;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            white-space: nowrap;
            flex-shrink: 0;
            background: transparent;
            min-height: 0;
            border-radius: 0;
        }
        .tab-label {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--tab-color);
            font-weight: 400;
            transition: color 0.1s ease;
        }
        .tab-item:hover .tab-label {
            color: var(--tab-active-color);
        }
        .tab-item.active {
            border-bottom: var(--tab-active-border);
        }
        .tab-item.active .tab-label {
            font-weight: var(--tab-active-weight);
            color: var(--tab-active-color);
        }
        .tab-panel {
            display: none;
            padding: var(--space-huge) var(--space-huge) 0;
        }
        .tab-panel.active {
            display: flex;
            flex-direction: column;
            flex: 1;
        }
        .campaign-card {
            width: 100%;
            margin-bottom: var(--space-small);
        }
        .campaign-header {
            display: flex;
            align-items: center;
            padding: 0;
            cursor: pointer;
            transition: color 0.1s ease;
            color: var(--accordion-title-color);
        }
        .campaign-header:hover {
            color: var(--color-text-active);
        }
        .campaign-title {
            font-size: 1.125em;
            font-weight: var(--font-weight-bold);
            line-height: 1em;
        }
        .campaign-header .channel-toggle {
            flex: 1;
        }
        .campaign-body {
            padding: var(--accordion-content-padding);
            padding-left: calc(7px + var(--space-tiny));
        }
        .campaign-body > :last-child {
            margin-bottom: 0;
        }
        .campaign-header.static {
            cursor: default;
        }
        .accordion-icon {
            display: inline-block;
            width: 0;
            height: 0;
            border-top: 6px solid transparent;
            border-bottom: 6px solid transparent;
            border-left: 7px solid currentColor;
            flex-shrink: 0;
            transition: var(--accordion-icon-transition);
        }
        .accordion-icon.expanded {
            transform: rotate(90deg);
        }
        .accordion-actions {
            margin-left: auto;
            display: flex;
            align-items: center;
            gap: var(--space-tiny);
            position: relative;
        }
        .active-toggle, .override-toggle {
            padding: var(--space-mini) var(--space-small);
            border-radius: var(--radius);
            transition: background var(--transition-fast), box-shadow var(--transition-fast);
        }
        .active-toggle:hover, .override-toggle:hover {
            background: var(--color-bg);
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .form-group {
            margin-bottom: var(--space-small);
        }
        .form-group:last-child {
            margin-bottom: 0;
        }
        label {
            display: block;
            margin: 0 0 .28571429rem 0;
            color: rgba(0, 0, 0, .87);
            font-size: var(--font-size-label);
            font-weight: var(--font-weight-bold);
            text-transform: none;
        }
        input[type="text"], textarea, select {
            width: 100%;
            padding: var(--input-padding);
            font-size: 1em;
            font-family: var(--font-family);
            line-height: var(--input-line-height);
            color: rgba(0, 0, 0, 0.87);
            background: var(--color-surface);
            border: var(--input-border);
            border-radius: var(--radius);
            transition: border-color var(--input-transition), box-shadow var(--input-transition);
            box-shadow: none;
            outline: 0;
            box-sizing: border-box;
        }
        input[type="text"]:focus, textarea:focus, select:focus {
            border-color: var(--input-focus-border);
            background: var(--color-surface);
            color: rgba(0, 0, 0, 0.8);
            box-shadow: none;
            outline: none;
        }
        input::placeholder, textarea::placeholder {
            color: var(--input-placeholder);
        }
        input:focus::placeholder, textarea:focus::placeholder {
            color: var(--input-focus-placeholder);
        }
        input[type="text"]:disabled, textarea:disabled, select:disabled {
            background: var(--color-bg);
            cursor: not-allowed;
        }
        textarea {
            min-height: 80px;
            resize: vertical;
        }
        .template-label-row {
            display: flex;
            align-items: center;
            gap: var(--space-tiny);
            position: relative;
            margin-bottom: 4px;
        }
        .template-label-row label {
            margin-bottom: 0;
            flex: 1;
        }
        .var-dropdown {
            display: none;
            position: absolute;
            top: calc(100% + 4px);
            right: 0;
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: var(--radius);
            box-shadow: 0 4px 16px rgba(0,0,0,0.12);
            z-index: 10;
            min-width: 220px;
            max-height: 300px;
            padding: var(--space-mini);
            overflow-y: auto;
        }
        .var-dropdown.open {
            display: block;
        }
        .var-group-label {
            padding: 4px 8px 2px;
            font-size: var(--font-size-label);
            font-weight: 700;
            color: var(--color-text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .var-group-label:not(:first-child) {
            margin-top: 4px;
        }
        .var-option {
            padding: 4px 8px;
            cursor: pointer;
            font-size: var(--font-size-label);
            font-family: monospace;
            color: var(--color-text);
            border-radius: var(--radius);
            margin: 1px 0;
        }
        .var-option:hover {
            background: rgba(33, 133, 208, 0.1);
            color: var(--color-secondary);
        }
        .channel-card {
            margin-bottom: var(--space-small);
        }
        .channel-card:last-child {
            margin-bottom: 0;
        }
        .channel-header {
            display: flex;
            align-items: center;
            gap: var(--space-tiny);
        }
        .channel-toggle {
            display: flex !important;
            align-items: center;
            gap: var(--space-tiny);
            font-weight: var(--font-weight-bold) !important;
            font-size: var(--font-size-label);
            margin-bottom: 0 !important;
            padding: var(--accordion-title-padding);
            flex: 1;
        }
        .channel-body {
            padding: 0;
        }
        .slash-menu {
            display: none;
            position: fixed;
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: var(--radius);
            box-shadow: 0 4px 16px rgba(0,0,0,0.15);
            max-height: 260px;
            overflow-y: auto;
            z-index: 9999;
            min-width: 200px;
            padding: 4px;
        }
        .slash-menu .var-option:hover {
            background: transparent;
            color: var(--color-text);
        }
        .slash-menu .var-option.highlighted {
            background: rgba(33, 133, 208, 0.1);
            color: var(--color-secondary);
        }
        .slash-menu-empty {
            padding: 8px 12px;
            color: var(--color-text-muted);
            font-size: var(--font-size-label);
        }
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: var(--space-tiny);
            padding: var(--btn-padding);
            font-size: var(--btn-font-size);
            font-weight: var(--font-weight-bold);
            font-family: var(--font-family);
            line-height: var(--input-line-height);
            border: 1px solid transparent;
            border-radius: var(--radius);
            cursor: pointer;
            transition: background-color var(--transition-fast), opacity var(--transition-fast);
            min-height: 1em;
        }
        .btn:focus-visible {
            outline: 2px solid var(--color-secondary);
            outline-offset: 2px;
        }
        .btn-sm {
            padding: var(--btn-padding-sm);
            font-size: var(--btn-font-size-sm);
            min-height: 36px;
        }
        .btn-xs {
            padding: var(--btn-padding-xs);
            font-size: var(--btn-font-size-xs);
            font-weight: 400;
            min-height: 0;
        }
        .btn-primary { background: var(--color-primary); color: #fff; }
        .btn-primary:hover { opacity: 0.9; }
        .btn-secondary { background: var(--color-secondary); color: #fff; }
        .btn-secondary:hover { opacity: 0.9; }
        .btn-default {
            background: #e0e1e2;
            color: rgba(0, 0, 0, 0.6);
        }
        .btn-default:hover {
            background: #cacbcd;
            color: rgba(0, 0, 0, 0.8);
        }
        .btn-danger { background: var(--color-danger); color: #fff; }
        .btn-danger:hover { opacity: 0.9; }
        .btn-danger:hover {
            filter: brightness(0.9);
        }
        .btn:disabled, .btn[disabled] {
            opacity: 0.45;
            cursor: default;
            pointer-events: none;
        }
        .save-bar {
            position: sticky;
            bottom: 0;
            margin: 0 -24px;
            padding: var(--space-large) var(--space-huge) var(--space-medium);
            background: var(--color-surface);
            z-index: 10;
        }
        .save-bar.stuck {
            box-shadow: 0 -4px 12px rgba(0,0,0,0.08);
        }
        .table {
            width: 100%;
            border-collapse: collapse;
            font-size: 1em;
            color: var(--color-text);
        }
        .table th {
            padding: 0.5rem 1rem;
            vertical-align: middle;
            text-align: left;
            font-weight: var(--font-weight-bold);
            background: var(--color-surface);
            border-bottom: 2px solid var(--color-border);
        }
        .table td {
            padding: 0.5rem 1rem;
            vertical-align: middle;
            text-align: left;
        }
        .table tr { border-bottom: 1px solid var(--color-border); }
        .table thead tr { border-bottom: none; }
        .table-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
        .table tbody tr:hover { background: rgba(0, 0, 50, 0.025); }
        .patient-link {
            color: var(--color-secondary);
            text-decoration: none;
            font-weight: 700;
        }
        .patient-link:hover {
            text-decoration: underline;
        }
        .error-text {
            color: var(--color-danger);
            font-size: var(--font-size-label);
        }
        .empty-state {
            text-align: center;
            padding: var(--space-huge) var(--space-large);
            color: var(--color-text-muted);
        }
        .global-settings {
            background: var(--color-bg);
            padding: 16px;
            border-radius: var(--radius);
            margin-bottom: var(--space-huge);
        }
        .interval-list {
            display: flex;
            gap: var(--space-tiny);
            flex-wrap: wrap;
            margin-top: var(--space-tiny);
            align-items: center;
        }
        .interval-tag {
            background: rgba(33, 133, 208, 0.1);
            padding: var(--space-mini) var(--space-small);
            border-radius: var(--radius);
            display: flex;
            align-items: center;
            gap: var(--space-mini);
            font-size: var(--font-size-label);
        }
        .interval-remove {
            cursor: pointer;
            color: var(--color-secondary);
            font-weight: bold;
        }
        .add-interval {
            display: flex;
            gap: var(--space-tiny);
            margin-top: var(--space-tiny);
        }
        .add-interval input[type="text"],
        .add-interval input[type="number"] {
            flex: 1;
            padding: var(--space-tiny);
            border: 1px solid var(--color-border);
            border-radius: var(--radius);
            font-family: inherit;
            font-size: var(--font-size-label);
            box-sizing: border-box;
            transition: border-color var(--transition-fast);
        }
        .add-interval input[type="text"].valid,
        .add-interval input[type="number"].valid {
            border-color: var(--color-primary);
        }
        .add-interval input[type="text"].invalid,
        .add-interval input[type="number"].invalid {
            border-color: var(--color-danger);
        }
        .interval-hint {
            margin-top: var(--space-tiny);
            font-size: var(--font-size-label);
            color: var(--color-text-muted);
        }
        .interval-hint code {
            background: var(--color-bg);
            border: 1px solid var(--color-border);
            border-radius: var(--radius);
            padding: 1px 5px;
            font-family: monospace;
            font-size: var(--font-size-label);
            color: var(--color-text);
        }
        .modal-backdrop {
            display: none;
            position: fixed;
            inset: 0;
            background-color: rgba(0, 0, 0, 0.5);
            z-index: 1000;
        }
        .modal-backdrop.active { display: block; }
        .modal-scroll {
            display: none;
            position: fixed;
            inset: 0;
            overflow-y: auto;
            z-index: 1001;
            padding: 2rem;
        }
        .modal-scroll.active { display: block; }
        .modal {
            position: relative;
            background: var(--color-surface);
            border: none;
            border-radius: var(--radius);
            box-shadow: 1px 3px 3px 0 rgba(0, 0, 0, 0.2), 1px 3px 15px 2px rgba(0, 0, 0, 0.2);
            margin: 0 auto;
        }
        .modal-small { width: 35rem; max-width: calc(100vw - 4rem); }
        .modal-medium { width: 52.5rem; max-width: calc(100vw - 4rem); }
        .modal-header {
            padding: 1.25rem 1.5rem;
            font-size: 1.42857143rem;
            font-weight: var(--font-weight-bold);
            line-height: 1.28571429em;
            color: rgba(0, 0, 0, 0.85);
            border-bottom: 1px solid rgba(34, 36, 38, 0.15);
        }
        .modal-content {
            padding: 1.5rem;
            font-size: 1em;
            line-height: 1.4;
        }
        .patient-info-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px 24px;
            margin-bottom: 20px;
        }
        .patient-info-grid .info-item {
            font-size: var(--font-size-label);
        }
        .patient-info-grid .info-label {
            color: var(--color-text-muted);
            font-size: var(--font-size-label);
            margin-bottom: 2px;
        }
        .modal-actions {
            padding: 1rem;
            background: #f9fafb;
            border-top: 1px solid rgba(34, 36, 38, 0.15);
            border-radius: 0 0 var(--radius) var(--radius);
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 4px;
        }
        .patient-modal-links {
            display: flex;
            gap: var(--space-small);
            margin-bottom: var(--space-huge);
        }
        .patient-modal-links a {
            display: inline-block;
            padding: var(--space-tiny) var(--space-medium);
            border-radius: var(--radius);
            text-decoration: none;
            font-size: var(--font-size-label);
            font-weight: 700;
        }
        .patient-status-warn {
            background: rgba(189, 11, 0, 0.08);
            border: 1px solid rgba(189, 11, 0, 0.25);
            border-radius: var(--radius);
            padding: 8px 12px;
            margin-bottom: 16px;
            font-size: var(--font-size-label);
            color: var(--color-danger);
        }
        .modal-subtitle {
            color: var(--color-text-muted);
            font-size: var(--font-size-label);
            margin: 0;
        }
        .next-appt {
            background: rgba(33, 133, 208, 0.1);
            border-radius: var(--radius);
            padding: 8px 12px;
            margin-bottom: 16px;
            font-size: var(--font-size-label);
            color: var(--color-secondary);
        }
        #banner_area {
            scroll-margin-top: 64px;
        }
        .banner {
            position: relative;
            min-height: 1em;
            margin: 1em 0;
            background: #f8f8f9;
            padding: 1em 1.5em;
            line-height: 1.4285em;
            color: rgba(0, 0, 0, 0.87);
            border-radius: var(--radius);
            font-size: 1em;
            transition: opacity 0.1s ease;
        }
        .banner-header { font-weight: var(--font-weight-bold); font-size: 1.14285714em; }
        .banner-header + p { margin-top: .25em; }
        .banner p { opacity: 0.85; }
        .banner-error { background-color: #fff6f6; color: #9f3a38; box-shadow: 0 0 0 1px #e0b4b4 inset; }
        .banner-warning { background-color: #fffaf3; color: #573a08; box-shadow: 0 0 0 1px #c9ba9b inset; }
        .banner-info { background-color: #f8ffff; color: #276f86; box-shadow: 0 0 0 1px #a9d5de inset; }
        .banner-dismissible { padding-right: 2.5em; }
        .banner-dismiss {
            position: absolute;
            top: 1em;
            right: 1em;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: none;
            border: none;
            cursor: pointer;
            padding: 0;
            min-height: 0;
            opacity: 0.5;
            color: inherit;
        }
        .banner-dismiss:hover { opacity: 1; }
        .search-input-wrapper {
            position: relative;
        }
        .search-dropdown {
            display: none;
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: var(--color-bg);
            border: 1px solid var(--color-border);
            border-top: none;
            z-index: 20;
            max-height: 200px;
            overflow-y: auto;
        }
        .search-dropdown.open { display: block; }
        .search-option {
            padding: 8px 12px;
            cursor: pointer;
            font-size: var(--font-size-label);
        }
        .search-option:hover { background: rgba(33, 133, 208, 0.1); }
        .search-option .search-role {
            font-size: var(--font-size-label);
            color: var(--color-text-muted);
            margin-left: 6px;
        }
        .search-no-results {
            padding: 8px 12px;
            color: var(--color-text-muted);
            font-size: var(--font-size-label);
        }
        .section-heading {
            font-size: 1.1875em;
            font-weight: 700;
            margin-top: 0;
            margin-bottom: 4px;
        }
        .section-desc {
            color: var(--color-text-muted);
            font-size: var(--font-size-label);
            margin-top: 0;
            margin-bottom: 16px;
        }
        .group-heading {
            font-size: 1em;
            font-weight: 700;
            color: var(--color-text);
            margin-top: 20px;
            margin-bottom: 4px;
        }
        .group-desc {
            color: var(--color-text-muted);
            font-size: var(--font-size-label);
            margin-top: 0;
            margin-bottom: 12px;
        }
        .campaign-row {
            border-bottom: 1px solid var(--color-border);
            padding: var(--space-small) 0;
        }
        .campaign-row:last-child {
            border-bottom: none;
            margin-bottom: -10px;
        }
        .campaign-row-header {
            display: flex;
            align-items: center;
            cursor: pointer;
            padding: 0;
            margin: 0 -20px;
            border-radius: var(--radius);
            transition: background var(--transition-fast);
        }
        .campaign-row-header .channel-toggle {
            flex: 1;
            padding: var(--space-small) var(--space-large);
        }
        .campaign-row-header:hover {
            background: var(--color-bg);
        }
        .campaign-row-title {
            font-weight: 700;
            font-size: var(--font-size-label);
        }
        .override-toggle-group {
            display: flex;
            align-items: center;
            gap: var(--space-tiny);
        }
        .override-hint {
            font-size: var(--font-size-label);
            color: var(--color-text-muted);
            padding: 4px 0 2px;
        }
        .override-fields {
            padding: 12px 0 4px;
        }
        .time-picker-wrap {
            position: relative;
            display: inline-flex;
        }
        .time-picker-box {
            display: flex;
            align-items: center;
            border: 1px solid var(--color-border);
            border-radius: var(--radius);
            padding: 0 8px;
            background: var(--color-surface);
            cursor: pointer;
            height: 36px;
            gap: 0;
            transition: border-color var(--transition-fast);
        }
        .time-picker-box:hover {
            border-color: var(--color-text-muted);
        }
        .time-picker-box:focus-within {
            border-color: var(--color-secondary);
            box-shadow: 0 0 0 2px rgba(33, 133, 208, 0.15);
        }
        .time-picker-box input {
            border: none;
            outline: none;
            width: 22px;
            text-align: center;
            font-size: var(--font-size-label);
            padding: 0;
            background: transparent;
            font-family: inherit;
        }
        .time-picker-box .tp-colon {
            font-weight: var(--font-weight-bold);
            font-size: var(--font-size-label);
            color: var(--color-text);
            user-select: none;
        }
        .time-picker-box .tp-icon {
            margin-left: 8px;
            color: var(--color-text-muted);
            font-size: 1em;
            display: flex;
            align-items: center;
        }
        .tp-dropdown {
            display: none;
            position: absolute;
            top: 100%;
            left: 0;
            margin-top: 4px;
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: var(--radius);
            box-shadow: 0 4px 12px rgba(0,0,0,0.12);
            z-index: 50;
            flex-direction: row;
        }
        .tp-dropdown.open {
            display: flex;
        }
        .tp-col {
            width: 64px;
            height: 200px;
            overflow-y: auto;
            border-right: 1px solid var(--color-border);
        }
        .tp-col:last-child {
            border-right: none;
        }
        .tp-col-item {
            padding: var(--space-mini) 0;
            text-align: center;
            font-size: var(--font-size-label);
            cursor: pointer;
            color: var(--color-text);
        }
        .tp-col-item:hover {
            background: var(--color-bg);
        }
        .tp-col-item.selected {
            background: var(--color-secondary);
            color: var(--color-surface);
            font-weight: var(--font-weight-bold);
        }
        .toggle-wrap {
            display: flex;
            align-items: center;
            gap: var(--space-tiny);
            min-height: 44px;
            cursor: pointer;
        }
        .toggle {
            position: relative;
            flex-shrink: 0;
            width: var(--toggle-width);
            height: var(--toggle-height);
            background: var(--toggle-track-inactive);
            border-radius: 500rem;
            border: none;
            cursor: pointer;
            padding: 0;
        }
        .toggle::after {
            content: "";
            position: absolute;
            top: 0;
            left: -0.05rem;
            width: var(--toggle-thumb-size);
            height: var(--toggle-thumb-size);
            background: #fff linear-gradient(transparent, rgba(0, 0, 0, 0.05));
            border-radius: 500rem;
            box-shadow: var(--toggle-thumb-shadow);
            transition: left 0.3s ease;
        }
        .toggle[aria-checked="true"] { background: var(--toggle-track-active); }
        .toggle[aria-checked="true"]::after { left: var(--toggle-checked-offset); }
        .toggle:hover, .toggle-wrap:hover .toggle { background: var(--toggle-track-inactive-hover); }
        .toggle[aria-checked="true"]:hover, .toggle-wrap:hover .toggle[aria-checked="true"] { background: var(--toggle-track-active); }
        .vs-status-label {
            font-size: var(--font-size-label);
            color: var(--color-text-muted);
            font-style: italic;
            white-space: nowrap;
        }
        .vs-status-label.customized {
            color: var(--color-secondary);
            font-style: normal;
            font-weight: var(--font-weight-bold);
        }
        .campaign-count {
            font-size: var(--font-size-label);
            color: var(--color-text-muted);
            white-space: nowrap;
        }
        .badge {
            display: inline-block;
            line-height: 1;
            vertical-align: baseline;
            margin: 0 .14285714em;
            background-color: #e8e8e8;
            padding: .5833em .833em;
            color: rgba(0, 0, 0, 0.6);
            font-weight: var(--font-weight-bold);
            border: 0 solid transparent;
            border-radius: var(--radius);
            font-size: .85714286rem;
            white-space: nowrap;
        }
        .badge-mini { font-size: .64285714rem; }
        .badge-green { background: #21ba45; color: #fff; }
        .badge-red { background: #db2828; color: #fff; }
        .badge-blue { background: #2185d0; color: #fff; }
        .badge-orange { background: #f2711c; color: #fff; }
        .badge-grey { background: #767676; color: #fff; }
        .badge-basic { background: none #fff; border: 1px solid rgba(34, 36, 38, 0.15); color: rgba(0, 0, 0, 0.87); }
        .vs-campaign-row {
        }
        .vs-campaign-row-header {
            display: flex;
            align-items: center;
            gap: var(--space-tiny);
            padding: var(--accordion-title-padding);
            cursor: pointer;
            transition: color 0.1s ease;
            color: var(--accordion-title-color);
        }
        .vs-campaign-row-header:hover {
            color: var(--color-text-active);
        }
        .vs-campaign-name {
            font-weight: var(--font-weight-bold);
            font-size: 1.125em;
            line-height: 1em;
        }
        .vs-campaign-status {
            margin-left: auto;
            display: flex;
            align-items: center;
            gap: var(--space-small);
        }
        .vs-row-channels {
            display: flex;
            gap: var(--space-tiny);
            font-size: var(--font-size-label);
        }
        .vs-row-channels span {
            color: var(--color-text-muted);
        }
        .vs-row-channels span.ch-on {
            color: var(--color-primary);
            font-weight: var(--font-weight-bold);
        }
        .vs-customize-area {
            display: none;
            padding: var(--accordion-content-padding);
            padding-left: calc(7px + var(--space-tiny));
        }
        .vs-customize-area.open {
            display: block;
        }
        .vs-customize-hint {
            font-size: var(--font-size-label);
            color: var(--color-text-muted);
            margin: 0 0 12px;
        }
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }
        .modal-content-compact {
            font-size: var(--font-size-label);
            line-height: 1.5;
        }
        .modal-content-compact p { margin: 0; }
        .history-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: var(--space-medium);
        }
        .history-filter {
            display: inline-flex;
            align-items: center;
            gap: var(--space-tiny);
            cursor: pointer;
            font-size: var(--font-size-label);
            color: var(--color-text-muted);
        }
    </style>
</head>
<body>
    <canvas-tooltip></canvas-tooltip>
    <div id="slash-menu" class="slash-menu"></div>
    <div class="container">
        <div class="tab-menu">
            <button class="tab-item active" role="tab" aria-selected="true" data-tab="campaigns" onclick="switchTab('campaigns')">Campaigns<span class="tab-label">Campaigns</span></button>
            <button class="tab-item" role="tab" aria-selected="false" data-tab="visit-settings" onclick="switchTab('visit-settings')">Visit Settings<span class="tab-label">Visit Settings</span></button>
            <button class="tab-item" role="tab" aria-selected="false" data-tab="variables" onclick="switchTab('variables')">Variables<span class="tab-label">Variables</span></button>
            <button class="tab-item" role="tab" aria-selected="false" data-tab="history" onclick="switchTab('history')">History<span class="tab-label">History</span></button>
            <button class="tab-item" role="tab" aria-selected="false" data-tab="info" onclick="switchTab('info')">Info<span class="tab-label">Info</span></button>
        </div>

        <div id="banner_area" style="padding:0 var(--space-huge);"></div>

        <div id="campaigns" class="tab-panel active">
            <div class="section-header">
                <div>
                    <h2 class="section-heading">Campaigns</h2>
                    <p class="section-desc">Define default message templates for each campaign. Enable or disable campaigns per visit type in the Visit Settings tab.</p>
                </div>
                <button class="btn btn-default btn-sm" id="campaigns_fold_btn" onclick="toggleFoldCampaigns()">Unfold all</button>
            </div>


            <h3 class="group-heading">Event Alerts</h3>
            <p class="group-desc">Sent once when a specific event occurs.</p>
            <div id="global_alerts_container"></div>

            <h3 class="group-heading" style="margin-top:var(--space-huge);">Scheduled Notifications</h3>
            <p class="group-desc">Sent on a schedule before the appointment.</p>
            <div id="global_scheduled_container"></div>

            <div class="save-bar">
                <button class="btn btn-secondary" id="save_campaigns" onclick="saveCampaignsTab()" disabled>Save</button>
                <button class="btn btn-default" id="discard_campaigns" onclick="discardTab('campaigns')" disabled>Discard</button>
            </div>
        </div>

        <div id="visit-settings" class="tab-panel">
            <div class="section-header">
                <div>
                    <h2 class="section-heading">Visit Settings</h2>
                    <p class="section-desc">Configure per visit type settings for each campaign.</p>
                </div>
                <button class="btn btn-default btn-sm" id="collapse_all_btn" onclick="toggleFoldAll()">Unfold all</button>
            </div>

            <div id="visit_types_container"></div>
            <div class="save-bar">
                <button class="btn btn-secondary" id="save_visit-settings" onclick="saveVisitSettingsTab()" disabled>Save</button>
                <button class="btn btn-default" id="discard_visit-settings" onclick="discardTab('visit-settings')" disabled>Discard</button>
                <button class="btn btn-default" id="reset_all_vs" onclick="resetAllToGlobal()" style="margin-left:auto;" disabled>Reset All to Global Defaults</button>
            </div>
        </div>

        <div id="variables" class="tab-panel" style="padding-bottom:24px;">
            <h2 class="section-heading">Custom Variables</h2>
            <p class="section-desc">Define custom template variables that can be used in any campaign template. Variables save immediately on add or remove.</p>
            <div id="custom_variables_container">
                <table id="custom_variables_table" style="width:100%;border-collapse:collapse;">
                    <thead>
                        <tr>
                            <th style="text-align:left;padding:var(--space-tiny);border-bottom:2px solid var(--color-border);font-size:var(--font-size-input);font-weight:var(--font-weight-bold);">Variable Name</th>
                            <th style="text-align:left;padding:var(--space-tiny);border-bottom:2px solid var(--color-border);font-size:var(--font-size-input);font-weight:var(--font-weight-bold);">Value</th>
                            <th style="text-align:left;padding:var(--space-tiny);border-bottom:2px solid var(--color-border);width:1%;white-space:nowrap;"></th>
                        </tr>
                    </thead>
                    <tbody id="custom_variables_body"></tbody>
                    <tfoot>
                        <tr>
                            <td style="padding:var(--space-tiny);vertical-align:top;">
                                <input type="text" id="new_cv_key" placeholder="variable_name" onkeydown="handleCvKeydown(event, 'key')">
                                <div id="new_cv_key_error" style="color:var(--color-danger);font-size:var(--font-size-label);margin-top:var(--space-mini);display:none;"></div>
                            </td>
                            <td style="padding:var(--space-tiny);vertical-align:top;">
                                <input type="text" id="new_cv_value" placeholder="replacement text" onkeydown="handleCvKeydown(event, 'value')">
                                <div id="new_cv_value_error" style="color:var(--color-danger);font-size:var(--font-size-label);margin-top:var(--space-mini);display:none;"></div>
                                <div style="color:var(--color-text-muted);font-size:var(--font-size-label);margin-top:var(--space-mini);">Plain text that replaces <code>{{variable_name}}</code> in messages</div>
                            </td>
                            <td style="padding:var(--space-tiny);vertical-align:top;text-align:right;">
                                <button class="btn btn-secondary btn-sm" onclick="addCustomVariable()">Add</button>
                            </td>
                        </tr>
                    </tfoot>
                </table>
            </div>
        </div>

        <div id="info" class="tab-panel" style="padding-bottom:24px;">
            <div id="integration_status" class="global-settings" style="margin-bottom:var(--space-medium);border:1px solid var(--color-border);border-radius:var(--radius);max-width:600px;">
                <h3 style="margin-top: 0;">Integration Status</h3>
                <div id="integration_loading" style="color:var(--color-text-muted);">Checking configuration...</div>
                <div id="integration_details" style="display:none;">
                    <div style="display:flex;gap:24px;flex-wrap:wrap;">
                        <div>Twilio SMS: <span id="twilio_status_icon">checking</span></div>
                        <div>SendGrid Email: <span id="sendgrid_status_icon">checking</span></div>
                    </div>
                    <div id="integration_fallback_note" style="margin-top:var(--space-tiny);padding:var(--space-tiny);background:rgba(237, 74, 11, 0.08);border-radius:var(--radius);font-size:var(--font-size-label);display:none;">
                        Direct delivery not configured. Notifications will be skipped until API keys are set.
                    </div>
                </div>
            </div>
        </div>

        <div id="history" class="tab-panel" style="padding-bottom:24px;">
            <div class="history-header">
                <h2 class="section-heading" style="margin:0;">Notification History</h2>
                <div class="toggle-wrap history-filter" onclick="var t=this.querySelector('.toggle'); if(event.target!==t) t.click();">
                    <span>Show only failed</span>
                    <button class="toggle" role="switch" aria-checked="false" id="history_filter_failed" aria-label="Show only failed" onclick="this.setAttribute('aria-checked', this.getAttribute('aria-checked') === 'true' ? 'false' : 'true'); renderHistoryTable()"></button>
                </div>
            </div>
            <div class="table-scroll">
                <table class="table" style="min-width:700px;">
                    <thead>
                        <tr>
                            <th>Date</th>
                            <th>Patient</th>
                            <th>Campaign</th>
                            <th>Channel</th>
                            <th>Status</th>
                            <th>Details</th>
                            <th style="width:80px;"></th>
                        </tr>
                    </thead>
                    <tbody id="history_body">
                    </tbody>
                </table>
            </div>
            <div id="history_empty" class="empty-state" style="display:none;">
                No notifications sent yet.
            </div>
        </div>
    </div>

    <div class="modal-backdrop" id="patient_modal-backdrop"></div>
    <div class="modal-scroll" id="patient_modal-scroll" onclick="closeScroll(event, 'patient_modal')">
        <div class="modal modal-medium" id="patient_modal">
            <div class="modal-header" id="modal_patient_name">Loading...</div>
            <div class="modal-content">
                <div id="modal_loading" style="text-align:center;padding:var(--space-large);color:var(--color-text-muted);">Loading patient details...</div>
                <div id="modal_content_inner" style="display:none;">
                    <div class="patient-info-grid" id="modal_patient_info"></div>
                    <div class="patient-modal-links" id="modal_actions"></div>
                    <h4 style="margin-top:0;margin-bottom:var(--space-small);">Notification History</h4>
                    <div id="modal_history"></div>
                </div>
            </div>
            <div class="modal-actions">
                <button class="btn btn-default" onclick="closeModal('patient_modal')">Close</button>
            </div>
        </div>
    </div>

    <div class="modal-backdrop" id="cv_remove_modal-backdrop"></div>
    <div class="modal-scroll" id="cv_remove_modal-scroll" onclick="closeScroll(event, 'cv_remove_modal')">
        <div class="modal modal-small" id="cv_remove_modal">
            <div class="modal-header">Remove Variable</div>
            <div class="modal-content modal-content-compact">
                <p id="cv_remove_message"></p>
            </div>
            <div class="modal-actions">
                <button class="btn btn-default" onclick="closeModal('cv_remove_modal')">Cancel</button>
                <button class="btn btn-danger" id="cv_remove_confirm_btn">Remove</button>
            </div>
        </div>
    </div>

    <div class="modal-backdrop" id="retry_modal-backdrop"></div>
    <div class="modal-scroll" id="retry_modal-scroll" onclick="closeScroll(event, 'retry_modal')">
        <div class="modal modal-small" id="retry_modal">
            <div class="modal-header">Retry Notification</div>
            <div class="modal-content modal-content-compact">
                <p id="retry_message"></p>
            </div>
            <div class="modal-actions">
                <button class="btn btn-default" onclick="closeModal('retry_modal')">Cancel</button>
                <button class="btn btn-secondary" id="retry_confirm_btn">Retry</button>
            </div>
        </div>
    </div>

    <div class="modal-backdrop" id="unsaved_modal-backdrop"></div>
    <div class="modal-scroll" id="unsaved_modal-scroll" onclick="closeScroll(event, 'unsaved_modal')">
        <div class="modal modal-small" id="unsaved_modal">
            <div class="modal-header">Unsaved Changes</div>
            <div class="modal-content modal-content-compact">
                <p>You have unsaved changes. What would you like to do?</p>
            </div>
            <div class="modal-actions">
                <button class="btn btn-default" onclick="closeModal('unsaved_modal')">Cancel</button>
                <button class="btn btn-danger" onclick="unsavedModalDiscard()">Discard</button>
                <button class="btn btn-secondary" id="unsaved_modal_save" onclick="unsavedModalSave()">Save</button>
            </div>
        </div>
    </div>

    <script>
        // Canvas tooltip web component, extracted from canvas-plugin-ui bundle.
        // Activates a global tooltip system. Any element with data-canvas-tooltip
        // shows a Canvas-styled tooltip on hover and focus.
        (function() {
            if (customElements.get('canvas-tooltip')) return;

            var ANCHOR_GAP = 10;
            var ANCHOR_EDGE = 8;
            var ANCHOR_ARROW_HALF = 7;
            var ANCHOR_ARROW_CORNER_INSET = 6;

            var _cuidCounter = 0;
            function cuid(prefix) {
                _cuidCounter += 1;
                return (prefix || 'cui') + '_' + Date.now().toString(36) + '_' + _cuidCounter.toString(36);
            }

            class CanvasTooltip extends HTMLElement {
                constructor() {
                    super();
                    this.attachShadow({ mode: 'open' });
                    this.shadowRoot.innerHTML = '<style>:host { display: none; }</style>';
                    this._tooltip = null;
                    this._inner = null;
                    this._arrow = null;
                    this._currentTrigger = null;
                    this._showTimeout = null;
                    this._tooltipId = cuid('tip');
                    this._priorDescribedBy = new WeakMap();
                    this._boundEnter = this._onEnter.bind(this);
                    this._boundLeave = this._onLeave.bind(this);
                    this._boundFocus = this._onEnter.bind(this);
                    this._boundBlur = this._onLeave.bind(this);
                    this._boundScroll = this._onScroll.bind(this);
                    this._trackedElements = new Set();
                }

                connectedCallback() {
                    this._createTooltip();
                    this._bindAll();
                    var self = this;
                    this._observer = new MutationObserver(function(mutations) {
                        self._handleMutations(mutations);
                    });
                    this._observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-canvas-tooltip'] });
                    document.addEventListener('scroll', this._boundScroll, true);
                    this._boundKey = function(e) {
                        if (e.key === 'Escape' && self._currentTrigger) {
                            self._clearPending();
                            self._currentTrigger = null;
                            self._hide();
                        }
                    };
                    document.addEventListener('keydown', this._boundKey, true);
                }

                disconnectedCallback() {
                    if (this._observer) {
                        this._observer.disconnect();
                        this._observer = null;
                    }
                    document.removeEventListener('scroll', this._boundScroll, true);
                    if (this._boundKey) document.removeEventListener('keydown', this._boundKey, true);
                    this._unbindAll();
                    if (this._tooltip && this._tooltip.parentNode) {
                        this._tooltip.parentNode.removeChild(this._tooltip);
                    }
                    this._tooltip = null;
                }

                _bindAll() {
                    var elements = document.querySelectorAll('[data-canvas-tooltip]');
                    elements.forEach(function(el) {
                        this._trackElement(el);
                    }, this);
                }

                _trackElement(el) {
                    if (this._trackedElements.has(el)) return;
                    el.addEventListener('mouseenter', this._boundEnter);
                    el.addEventListener('mouseleave', this._boundLeave);
                    el.addEventListener('focusin', this._boundFocus);
                    el.addEventListener('focusout', this._boundBlur);
                    this._trackedElements.add(el);
                }

                _untrackElement(el) {
                    if (!this._trackedElements.has(el)) return;
                    el.removeEventListener('mouseenter', this._boundEnter);
                    el.removeEventListener('mouseleave', this._boundLeave);
                    el.removeEventListener('focusin', this._boundFocus);
                    el.removeEventListener('focusout', this._boundBlur);
                    this._trackedElements.delete(el);
                }

                _handleMutations(mutations) {
                    for (var i = 0; i < mutations.length; i++) {
                        var m = mutations[i];
                        if (m.type === 'childList') {
                            for (var j = 0; j < m.removedNodes.length; j++) {
                                this._cleanupSubtree(m.removedNodes[j]);
                            }
                        } else if (m.type === 'attributes' && m.attributeName === 'data-canvas-tooltip') {
                            var target = m.target;
                            if (target.hasAttribute('data-canvas-tooltip')) {
                                this._trackElement(target);
                            } else {
                                this._untrackElement(target);
                            }
                        }
                    }
                    this._bindAll();
                }

                _cleanupSubtree(node) {
                    if (!node || node.nodeType !== 1) return;
                    if (this._trackedElements.has(node)) this._untrackElement(node);
                    var nested = node.querySelectorAll ? node.querySelectorAll('[data-canvas-tooltip]') : [];
                    for (var i = 0; i < nested.length; i++) {
                        if (this._trackedElements.has(nested[i])) this._untrackElement(nested[i]);
                    }
                }

                _unbindAll() {
                    var self = this;
                    this._trackedElements.forEach(function(el) {
                        el.removeEventListener('mouseenter', self._boundEnter);
                        el.removeEventListener('mouseleave', self._boundLeave);
                        el.removeEventListener('focusin', self._boundFocus);
                        el.removeEventListener('focusout', self._boundBlur);
                    });
                    this._trackedElements.clear();
                }

                _createTooltip() {
                    if (this._tooltip) return;

                    var style = document.createElement('style');
                    style.textContent = `
                        .canvas-tooltip-container {
                            position: fixed;
                            z-index: 1900;
                            pointer-events: none;
                            display: none;
                            max-width: 250px;
                            filter: drop-shadow(0 2px 4px rgba(34, 36, 38, 0.12)) drop-shadow(0 2px 10px rgba(34, 36, 38, 0.15));
                        }
                        .canvas-tooltip-container.visible { display: block; }
                        .canvas-tooltip-inner {
                            position: relative;
                            z-index: 1;
                            background: #fff;
                            border: 1px solid #d4d4d5;
                            border-radius: .28571429rem;
                            padding: .833em 1em;
                            font-family: lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                            font-size: 1rem;
                            font-weight: 400;
                            line-height: 1.4285em;
                            color: rgba(0, 0, 0, 0.87);
                            word-wrap: break-word;
                        }
                        .canvas-tooltip-container.inverted { filter: none; }
                        .canvas-tooltip-container.inverted .canvas-tooltip-inner {
                            background: #1b1c1d;
                            color: #fff;
                            border: none;
                        }
                        .canvas-tooltip-arrow { position: absolute; z-index: 0; line-height: 0; }
                        .canvas-tooltip-arrow svg { display: block; fill: #d4d4d5; stroke: none; }
                        .canvas-tooltip-arrow-cover { position: absolute; z-index: 2; line-height: 0; }
                        .canvas-tooltip-arrow-cover svg { display: block; fill: #fff; stroke: none; }
                        .canvas-tooltip-container.inverted .canvas-tooltip-arrow svg { fill: #1b1c1d; }
                        .canvas-tooltip-container.inverted .canvas-tooltip-arrow-cover svg { fill: #1b1c1d; }
                        .canvas-tooltip-container.pos-top .canvas-tooltip-arrow { bottom: -5px; left: 50%; margin-left: -7px; }
                        .canvas-tooltip-container.pos-top .canvas-tooltip-arrow-cover { bottom: -4px; left: 50%; margin-left: -7px; }
                        .canvas-tooltip-container.pos-bottom .canvas-tooltip-arrow { top: -5px; left: 50%; margin-left: -7px; }
                        .canvas-tooltip-container.pos-bottom .canvas-tooltip-arrow-cover { top: -4px; left: 50%; margin-left: -7px; }
                        .canvas-tooltip-container.pos-left .canvas-tooltip-arrow { right: -5px; top: 50%; margin-top: -7px; }
                        .canvas-tooltip-container.pos-left .canvas-tooltip-arrow-cover { right: -4px; top: 50%; margin-top: -7px; }
                        .canvas-tooltip-container.pos-right .canvas-tooltip-arrow { left: -5px; top: 50%; margin-top: -7px; }
                        .canvas-tooltip-container.pos-right .canvas-tooltip-arrow-cover { left: -4px; top: 50%; margin-top: -7px; }
                    `;

                    var container = document.createElement('div');
                    container.className = 'canvas-tooltip-container';
                    container.setAttribute('role', 'tooltip');
                    container.setAttribute('aria-hidden', 'true');
                    container.id = this._tooltipId;

                    var inner = document.createElement('div');
                    inner.className = 'canvas-tooltip-inner';

                    var arrow = document.createElement('div');
                    arrow.className = 'canvas-tooltip-arrow';

                    var arrowCover = document.createElement('div');
                    arrowCover.className = 'canvas-tooltip-arrow-cover';

                    container.appendChild(arrow);
                    container.appendChild(inner);
                    container.appendChild(arrowCover);

                    document.head.appendChild(style);
                    document.body.appendChild(container);
                    this._tooltip = container;
                    this._inner = inner;
                    this._arrow = arrow;
                    this._arrowCover = arrowCover;
                }

                _onEnter(e) {
                    var trigger = e.currentTarget;
                    var text = trigger.getAttribute('data-canvas-tooltip');
                    if (!text) return;
                    this._clearPending();
                    this._currentTrigger = trigger;
                    var delay = parseInt(trigger.getAttribute('data-canvas-tooltip-delay') || '0', 10);
                    var self = this;
                    if (delay > 0) {
                        this._showTimeout = setTimeout(function() {
                            if (self._currentTrigger === trigger) self._show(trigger);
                        }, delay);
                    } else {
                        this._show(trigger);
                    }
                }

                _onLeave(e) {
                    this._clearPending();
                    this._currentTrigger = null;
                    this._hide();
                }

                _onScroll() {
                    if (this._currentTrigger) {
                        this._clearPending();
                        this._currentTrigger = null;
                        this._hide();
                    }
                }

                _clearPending() {
                    if (this._showTimeout) {
                        clearTimeout(this._showTimeout);
                        this._showTimeout = null;
                    }
                }

                _show(trigger) {
                    if (!this._tooltip) return;
                    var text = trigger.getAttribute('data-canvas-tooltip');
                    if (!text) return;

                    var position = trigger.getAttribute('data-canvas-tooltip-position') || 'top';
                    var inverted = trigger.hasAttribute('data-canvas-tooltip-inverted');

                    this._inner.textContent = text;
                    this._setArrow(position);
                    this._tooltip.className = 'canvas-tooltip-container' + (inverted ? ' inverted' : '') + ' pos-' + position;
                    this._tooltip.setAttribute('aria-hidden', 'false');
                    this._tooltip.style.left = '-9999px';
                    this._tooltip.style.top = '-9999px';
                    this._tooltip.classList.add('visible');

                    this._priorDescribedBy.set(trigger, trigger.getAttribute('aria-describedby'));
                    var existing = trigger.getAttribute('aria-describedby');
                    var ids = existing ? existing.split(/\\s+/).filter(Boolean) : [];
                    if (ids.indexOf(this._tooltipId) === -1) ids.push(this._tooltipId);
                    trigger.setAttribute('aria-describedby', ids.join(' '));

                    var self = this;
                    requestAnimationFrame(function() {
                        var triggerRect = trigger.getBoundingClientRect();
                        var tipRect = self._tooltip.getBoundingClientRect();
                        var coords = self._calcPosition(position, triggerRect, tipRect);
                        if (coords.flipped) {
                            self._setArrow(coords.position);
                            self._tooltip.className = 'canvas-tooltip-container visible' + (inverted ? ' inverted' : '') + ' pos-' + coords.position;
                        }
                        self._tooltip.style.left = coords.left + 'px';
                        self._tooltip.style.top = coords.top + 'px';
                        self._applyArrowOffset(coords);
                    });
                }

                _setArrow(position) {
                    var svgs = {
                        top: '<svg width="14" height="7" viewBox="0 0 14 7"><path d="M0 0 L7 7 L14 0" vector-effect="non-scaling-stroke"/></svg>',
                        bottom: '<svg width="14" height="7" viewBox="0 0 14 7"><path d="M0 7 L7 0 L14 7" vector-effect="non-scaling-stroke"/></svg>',
                        left: '<svg width="7" height="14" viewBox="0 0 7 14"><path d="M0 0 L7 7 L0 14" vector-effect="non-scaling-stroke"/></svg>',
                        right: '<svg width="7" height="14" viewBox="0 0 7 14"><path d="M7 0 L0 7 L7 14" vector-effect="non-scaling-stroke"/></svg>'
                    };
                    this._arrow.innerHTML = svgs[position] || svgs.top;
                    this._arrowCover.innerHTML = svgs[position] || svgs.top;
                }

                _applyArrowOffset(coords) {
                    this._arrow.style.left = '';
                    this._arrow.style.top = '';
                    this._arrow.style.marginLeft = '';
                    this._arrow.style.marginTop = '';
                    this._arrowCover.style.left = '';
                    this._arrowCover.style.top = '';
                    this._arrowCover.style.marginLeft = '';
                    this._arrowCover.style.marginTop = '';
                    if (coords.arrowX != null) {
                        this._arrow.style.left = coords.arrowX + 'px';
                        this._arrow.style.marginLeft = '0';
                        this._arrowCover.style.left = coords.arrowX + 'px';
                        this._arrowCover.style.marginLeft = '0';
                    } else if (coords.arrowY != null) {
                        this._arrow.style.top = coords.arrowY + 'px';
                        this._arrow.style.marginTop = '0';
                        this._arrowCover.style.top = coords.arrowY + 'px';
                        this._arrowCover.style.marginTop = '0';
                    }
                }

                _hide() {
                    if (!this._tooltip) return;
                    this._tooltip.classList.remove('visible');
                    this._tooltip.setAttribute('aria-hidden', 'true');
                    this._restoreDescribedBy();
                }

                _restoreDescribedBy() {
                    var self = this;
                    this._trackedElements.forEach(function(el) {
                        var existing = el.getAttribute('aria-describedby');
                        if (!existing) return;
                        var ids = existing.split(/\\s+/).filter(function(id) { return id && id !== self._tooltipId; });
                        if (ids.length) el.setAttribute('aria-describedby', ids.join(' '));
                        else {
                            var prior = self._priorDescribedBy.get(el);
                            if (prior) el.setAttribute('aria-describedby', prior);
                            else el.removeAttribute('aria-describedby');
                        }
                        self._priorDescribedBy.delete(el);
                    });
                }

                _calcPosition(position, triggerRect, tipRect) {
                    var gap = ANCHOR_GAP;
                    var edge = ANCHOR_EDGE;
                    var arrowHalf = ANCHOR_ARROW_HALF;
                    var arrowInset = ANCHOR_ARROW_CORNER_INSET;
                    var left, top;
                    var flipped = false;
                    switch (position) {
                        case 'top':
                            left = triggerRect.left + (triggerRect.width - tipRect.width) / 2;
                            top = triggerRect.top - tipRect.height - gap;
                            if (top < 0) { top = triggerRect.bottom + gap; position = 'bottom'; flipped = true; }
                            break;
                        case 'bottom':
                            left = triggerRect.left + (triggerRect.width - tipRect.width) / 2;
                            top = triggerRect.bottom + gap;
                            if (top + tipRect.height > window.innerHeight) { top = triggerRect.top - tipRect.height - gap; position = 'top'; flipped = true; }
                            break;
                        case 'left':
                            left = triggerRect.left - tipRect.width - gap;
                            top = triggerRect.top + (triggerRect.height - tipRect.height) / 2;
                            if (left < 0) { left = triggerRect.right + gap; position = 'right'; flipped = true; }
                            break;
                        case 'right':
                            left = triggerRect.right + gap;
                            top = triggerRect.top + (triggerRect.height - tipRect.height) / 2;
                            if (left + tipRect.width > window.innerWidth) { left = triggerRect.left - tipRect.width - gap; position = 'left'; flipped = true; }
                            break;
                    }
                    if (left + tipRect.width > window.innerWidth - edge) {
                        left = window.innerWidth - tipRect.width - edge;
                    }
                    if (left < edge) left = edge;
                    if (top + tipRect.height > window.innerHeight - edge) {
                        top = window.innerHeight - tipRect.height - edge;
                    }
                    if (top < edge) top = edge;
                    var arrowX = null;
                    var arrowY = null;
                    if (position === 'top' || position === 'bottom') {
                        var triggerCenterX = triggerRect.left + triggerRect.width / 2;
                        var idealX = triggerCenterX - left - arrowHalf;
                        var minX = arrowInset;
                        var maxX = tipRect.width - arrowInset - arrowHalf * 2;
                        if (maxX < minX) maxX = minX;
                        if (idealX < minX) idealX = minX;
                        if (idealX > maxX) idealX = maxX;
                        arrowX = idealX;
                    } else {
                        var triggerCenterY = triggerRect.top + triggerRect.height / 2;
                        var idealY = triggerCenterY - top - arrowHalf;
                        var minY = arrowInset;
                        var maxY = tipRect.height - arrowInset - arrowHalf * 2;
                        if (maxY < minY) maxY = minY;
                        if (idealY < minY) idealY = minY;
                        if (idealY > maxY) idealY = maxY;
                        arrowY = idealY;
                    }
                    return { left: left, top: top, position: position, flipped: flipped, arrowX: arrowX, arrowY: arrowY };
                }
            }

            customElements.define('canvas-tooltip', CanvasTooltip);
        })();

        // canvas-checkbox web component, extracted from canvas-plugin-ui bundle.
        (function() {
            if (customElements.get('canvas-checkbox')) return;
            var _cbCounter = 0;
            function cbUid(p) { _cbCounter += 1; return (p||'cb') + '_' + Date.now().toString(36) + '_' + _cbCounter.toString(36); }
            var ARIA_ATTRS = ['required','aria-invalid','disabled','aria-describedby','aria-labelledby','aria-controls','aria-expanded','aria-activedescendant'];
            function AriaProxy(Base) {
                var attrs = ARIA_ATTRS;
                return class extends Base {
                    static get observedAttributes() {
                        var inh = Base.observedAttributes || [], merged = inh.slice();
                        for (var i = 0; i < attrs.length; i++) if (merged.indexOf(attrs[i]) === -1) merged.push(attrs[i]);
                        return merged;
                    }
                    attributeChangedCallback(n, o, v) {
                        if (typeof super.attributeChangedCallback === 'function') super.attributeChangedCallback(n, o, v);
                        if (attrs.indexOf(n) === -1) return;
                        var t = typeof this._ariaProxyTarget === 'function' ? this._ariaProxyTarget() : null;
                        if (!t) return;
                        if (v == null) t.removeAttribute(n); else t.setAttribute(n, v);
                    }
                    _syncAriaProxy() {
                        var t = typeof this._ariaProxyTarget === 'function' ? this._ariaProxyTarget() : null;
                        if (!t) return;
                        for (var i = 0; i < attrs.length; i++) {
                            var n = attrs[i];
                            if (this.hasAttribute(n)) t.setAttribute(n, this.getAttribute(n)); else t.removeAttribute(n);
                        }
                    }
                };
            }
            class CanvasCheckbox extends AriaProxy(HTMLElement) {
                static get observedAttributes() {
                    var base = ['label','checked','disabled','name','value'], inh = super.observedAttributes || [];
                    for (var i = 0; i < inh.length; i++) if (base.indexOf(inh[i]) === -1) base.push(inh[i]);
                    return base;
                }
                static formAssociated = true;
                constructor() {
                    super();
                    this._internals = this.attachInternals();
                    this.attachShadow({ mode: 'open', delegatesFocus: true });
                    this.shadowRoot.innerHTML =
                        '<style>' +
                        ':host{display:inline-flex;align-items:center;min-height:var(--canvas-checkbox-min-height,auto);cursor:pointer;font-size:1rem;line-height:1;font-family:lato,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}' +
                        ':host([disabled]){cursor:not-allowed;opacity:0.45}' +
                        'input{position:absolute;opacity:0;width:17px;height:17px;cursor:pointer;z-index:3;margin:0}' +
                        ':host([disabled]) input{cursor:not-allowed}' +
                        '.box{position:relative;flex-shrink:0;width:17px;height:17px;background:#fff;border:1px solid rgba(34,36,38,.15);border-radius:.21428571rem;transition:border .1s ease,background .1s ease;box-sizing:border-box}' +
                        '.box::after{content:"";position:absolute;top:1px;left:4px;width:3.5px;height:8px;border:solid rgba(0,0,0,.95);border-width:0 3px 3px 0;transform:rotate(45deg);opacity:0;transition:opacity .1s ease}' +
                        'input:checked~.box{border-color:rgba(34,36,38,.35)}' +
                        'input:checked~.box::after{opacity:1}' +
                        ':host(:hover) .box{border-color:rgba(34,36,38,.35)}' +
                        'input:focus~.box,:host(:hover) input:focus~.box{border-color:#85b7d9}' +
                        '.label-text{padding-left:8px;color:rgba(0,0,0,.87)}' +
                        '</style>' +
                        '<input type="checkbox" part="input"><span class="box"></span><span class="label-text" part="label"></span>';
                    this._input = this.shadowRoot.querySelector('input');
                    this._labelText = this.shadowRoot.querySelector('.label-text');
                    this._inputId = cbUid('cb'); this._labelId = cbUid('cb-lbl');
                    this._input.id = this._inputId; this._labelText.id = this._labelId;
                    this._input.setAttribute('aria-labelledby', this._labelId);
                    this._boundOnChange = this._onChange.bind(this);
                    this._boundOnClick = this._onClick.bind(this);
                }
                _ariaProxyTarget() { return this._input; }
                _syncLabelledBy() {
                    var lb = this.getAttribute('aria-labelledby');
                    this._input.setAttribute('aria-labelledby', lb ? this._labelId + ' ' + lb : this._labelId);
                }
                connectedCallback() {
                    this._input.addEventListener('change', this._boundOnChange);
                    this.addEventListener('click', this._boundOnClick);
                    this._syncAll(); this._syncAriaProxy(); this._syncLabelledBy();
                }
                disconnectedCallback() {
                    this._input.removeEventListener('change', this._boundOnChange);
                    this.removeEventListener('click', this._boundOnClick);
                }
                attributeChangedCallback(name, oldVal, newVal) {
                    if (typeof super.attributeChangedCallback === 'function') super.attributeChangedCallback(name, oldVal, newVal);
                    if (name === 'aria-labelledby') { this._syncLabelledBy(); return; }
                    if (!this._input) return;
                    if (name === 'label') this._labelText.textContent = this.getAttribute('label') || '';
                    else if (name === 'checked') { this._input.checked = this.hasAttribute('checked'); this._syncFormValue(); }
                    else if (name === 'disabled') this._input.disabled = this.hasAttribute('disabled');
                    else if (name === 'name') this._input.name = this.getAttribute('name') || '';
                    else if (name === 'value') { this._input.value = this.getAttribute('value') || 'on'; this._syncFormValue(); }
                }
                get checked() { return this._input.checked; }
                set checked(v) {
                    if (v) this.setAttribute('checked', ''); else this.removeAttribute('checked');
                    this._input.checked = !!v; this._syncFormValue();
                }
                get value() { return this.getAttribute('value') || 'on'; }
                get name() { return this.getAttribute('name'); }
                _syncAll() {
                    this._labelText.textContent = this.getAttribute('label') || '';
                    this._input.name = this.getAttribute('name') || '';
                    this._input.value = this.getAttribute('value') || 'on';
                    this._input.checked = this.hasAttribute('checked');
                    this._input.disabled = this.hasAttribute('disabled');
                    this._syncFormValue();
                }
                _syncFormValue() {
                    this._internals.setFormValue(this._input.checked ? (this.getAttribute('value') || 'on') : null);
                }
                _onClick(e) {
                    if (this.hasAttribute('disabled')) return;
                    if (e.composedPath()[0] === this._input) return;
                    this._input.checked = !this._input.checked;
                    this._input.dispatchEvent(new Event('change', { bubbles: true }));
                }
                _onChange(e) {
                    e.stopPropagation();
                    if (this._input.checked) this.setAttribute('checked', ''); else this.removeAttribute('checked');
                    this._syncFormValue();
                    this.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
                }
            }
            customElements.define('canvas-checkbox', CanvasCheckbox);
        })();

        var noteTypes = [];
        var savedNoteTypeCampaigns = {};
        var globalHistoryData = [];
        var globalIntervals = {reminder: [], telehealth: []};
        var vtIntervals = {};
        var customVariablesList = [];
        var dismissSvg = '<svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
        var bannerDismissTimer = null;

        function showBanner(msg, type) {
            var area = document.getElementById('banner_area');
            if (bannerDismissTimer) {
                clearTimeout(bannerDismissTimer);
                bannerDismissTimer = null;
            }
            area.innerHTML = '';
            var cls = type === 'error' ? 'banner-error' : 'banner-warning';
            var div = document.createElement('div');
            div.className = 'banner ' + cls + ' banner-dismissible';
            div.innerHTML = '<button class="banner-dismiss" aria-label="Dismiss">' + dismissSvg + '</button>' + escapeHtml(msg);
            area.appendChild(div);
            area.scrollIntoView({behavior: 'smooth', block: 'nearest'});
            bannerDismissTimer = setTimeout(function() {
                var b = area.querySelector('.banner');
                if (b) {
                    b.style.opacity = '0';
                    setTimeout(function() { b.remove(); }, 100);
                }
                bannerDismissTimer = null;
            }, 5000);
        }

        function clearBanners() {
            if (bannerDismissTimer) {
                clearTimeout(bannerDismissTimer);
                bannerDismissTimer = null;
            }
            var area = document.getElementById('banner_area');
            if (area) area.innerHTML = '';
        }

        document.addEventListener('click', function(e) {
            var dismiss = e.target.closest('.banner-dismiss');
            if (dismiss) {
                var banner = dismiss.closest('.banner');
                banner.style.opacity = '0';
                setTimeout(function() { banner.remove(); }, 100);
                if (bannerDismissTimer) {
                    clearTimeout(bannerDismissTimer);
                    bannerDismissTimer = null;
                }
            }
        });

        function escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }

        function openModal(id) {
            document.getElementById(id + '-backdrop').classList.add('active');
            document.getElementById(id + '-scroll').classList.add('active');
            document.documentElement.style.overflow = 'hidden';
            document.body.style.overflow = 'hidden';
        }
        function closeModal(id) {
            document.getElementById(id + '-backdrop').classList.remove('active');
            document.getElementById(id + '-scroll').classList.remove('active');
            document.documentElement.style.overflow = '';
            document.body.style.overflow = '';
        }
        function closeScroll(event, id) {
            if (event.target === event.currentTarget) closeModal(id);
        }

        function toggleAriaChecked(el) {
            el.setAttribute('aria-checked', el.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
        }

        function isToggleChecked(el) {
            if (!el) return false;
            if (el.tagName === 'CANVAS-CHECKBOX') return el.checked;
            if (el.tagName === 'INPUT' && el.type === 'checkbox') return el.checked;
            return el.getAttribute('aria-checked') === 'true';
        }

        function setToggleChecked(el, value) {
            if (!el) return;
            if (el.tagName === 'CANVAS-CHECKBOX') { el.checked = !!value; return; }
            if (el.tagName === 'INPUT' && el.type === 'checkbox') { el.checked = !!value; return; }
            el.setAttribute('aria-checked', value ? 'true' : 'false');
        }

        function fieldPrefix(campaignKey) {
            return campaignKey === 'reminders' ? 'reminder' : campaignKey;
        }

        var TEMPLATE_VARIABLES = [
            {group: 'Patient', vars: ['patient_first_name', 'patient_last_name', 'patient_preferred_name', 'patient_full_name']},
            {group: 'Appointment', vars: ['appointment_date', 'appointment_time', 'appointment_type', 'provider_name', 'provider_credentials', 'minutes_until', 'telehealth_link']},
            {group: 'Location', vars: ['location_name', 'location_full_name', 'location_short_name', 'location_address', 'location_phone']},
            {group: 'Organization', vars: ['organization_name', 'organization_full_name', 'organization_short_name', 'organization_address', 'organization_phone']}
        ];

        function getAllVariableGroups() {
            var groups = TEMPLATE_VARIABLES.slice();
            if (customVariablesList.length > 0) {
                groups.push({group: 'Custom', vars: customVariablesList.map(function(cv) { return cv.key; })});
            }
            return groups;
        }

        function buildVarDropdownHtml() {
            var html = '';
            getAllVariableGroups().forEach(function(g) {
                html += '<div class="var-group-label">' + escapeHtml(g.group) + '</div>';
                g.vars.forEach(function(v) {
                    html += '<div class="var-option" onclick="insertVariable(this, \\'' + v + '\\')">' + escapeHtml('{{' + v + '}}') + '</div>';
                });
            });
            return html;
        }

        function toggleVarDropdown(btn) {
            var card = btn.closest('.channel-card');
            var dropdown = card.querySelector('.var-dropdown');
            var isOpen = dropdown.classList.contains('open');
            document.querySelectorAll('.var-dropdown.open').forEach(function(d) { d.classList.remove('open'); });
            if (!isOpen) {
                if (!dropdown.innerHTML) dropdown.innerHTML = buildVarDropdownHtml();
                dropdown.classList.add('open');
            }
        }

        function insertVariable(optionEl, varName) {
            var card = optionEl.closest('.channel-card');
            var textarea = card.querySelector('textarea');
            var tag = '{{' + varName + '}}';
            var start = textarea.selectionStart;
            var end = textarea.selectionEnd;
            var val = textarea.value;
            textarea.value = val.substring(0, start) + tag + val.substring(end);
            textarea.focus();
            var newPos = start + tag.length;
            textarea.setSelectionRange(newPos, newPos);
            card.querySelector('.var-dropdown').classList.remove('open');
        }

        document.addEventListener('click', function(e) {
            if (!e.target.closest('.channel-card')) {
                document.querySelectorAll('.var-dropdown.open').forEach(function(d) { d.classList.remove('open'); });
            }
            if (!e.target.closest('#slash-menu') && !(slashMenu.active && e.target === slashMenu.textarea)) {
                hideSlashMenu();
            }
        });

        // Slash command menu
        var slashMenu = { active: false, textarea: null, startPos: -1 };
        var slashMenuEl = document.getElementById('slash-menu');
        var slashMirrorDiv = null;

        function getCaretCoordinates(textarea, position) {
            if (!slashMirrorDiv) {
                slashMirrorDiv = document.createElement('div');
                slashMirrorDiv.style.position = 'absolute';
                slashMirrorDiv.style.left = '-9999px';
                slashMirrorDiv.style.top = '-9999px';
                slashMirrorDiv.style.visibility = 'hidden';
                document.body.appendChild(slashMirrorDiv);
            }
            var computed = window.getComputedStyle(textarea);
            ['font','padding','border','lineHeight','letterSpacing','whiteSpace','wordWrap','width','overflowWrap','paddingLeft','paddingRight','paddingTop','paddingBottom','borderLeftWidth','borderRightWidth','borderTopWidth','borderBottomWidth','boxSizing','fontFamily','fontSize','fontWeight'].forEach(function(p) { slashMirrorDiv.style[p] = computed[p]; });
            slashMirrorDiv.style.overflow = 'hidden';
            slashMirrorDiv.style.whiteSpace = 'pre-wrap';
            slashMirrorDiv.style.wordWrap = 'break-word';
            var text = textarea.value.substring(0, position);
            slashMirrorDiv.textContent = text;
            var span = document.createElement('span');
            span.textContent = '\\u200b';
            slashMirrorDiv.appendChild(span);
            return { top: span.offsetTop - textarea.scrollTop, left: span.offsetLeft };
        }

        function showSlashMenu(textarea, position) {
            slashMenu.active = true;
            slashMenu.textarea = textarea;
            slashMenu.startPos = position;
            var coords = getCaretCoordinates(textarea, position);
            var rect = textarea.getBoundingClientRect();
            var computed = window.getComputedStyle(textarea);
            var lineHeight = parseInt(computed.lineHeight) || parseInt(computed.fontSize) * 1.2;
            var top = rect.top + coords.top + lineHeight + window.scrollY;
            var left = rect.left + coords.left + window.scrollX;
            slashMenuEl.innerHTML = buildSlashMenuHtml('');
            slashMenuEl.style.display = 'block';
            var menuRect = slashMenuEl.getBoundingClientRect();
            if (left + menuRect.width > window.innerWidth + window.scrollX) left = window.innerWidth + window.scrollX - menuRect.width - 8;
            slashMenuEl.style.position = 'fixed';
            slashMenuEl.style.top = (top - window.scrollY) + 'px';
            slashMenuEl.style.left = (left - window.scrollX) + 'px';
            highlightSlashOption(0);
        }

        function hideSlashMenu() {
            slashMenu.active = false;
            slashMenu.textarea = null;
            slashMenu.startPos = -1;
            slashMenuEl.style.display = 'none';
        }

        function fuzzyMatch(query, target) {
            if (!query) return true;
            var q = query.toLowerCase(), t = target.toLowerCase(), qi = 0;
            for (var ti = 0; ti < t.length && qi < q.length; ti++) { if (t[ti] === q[qi]) qi++; }
            return qi === q.length;
        }

        function buildSlashMenuHtml(query) {
            var html = '', hasAny = false;
            getAllVariableGroups().forEach(function(g) {
                var matched = g.vars.filter(function(v) { return fuzzyMatch(query, v); });
                if (matched.length === 0) return;
                hasAny = true;
                html += '<div class="var-group-label">' + escapeHtml(g.group) + '</div>';
                matched.forEach(function(v) {
                    html += '<div class="var-option" data-var="' + v + '" onmousedown="event.preventDefault();slashSelect(this, \\'' + v + '\\')" onmouseenter="highlightSlashByEl(this)">' + escapeHtml('{{' + v + '}}') + '</div>';
                });
            });
            return hasAny ? html : '<div class="slash-menu-empty">No matching fields</div>';
        }

        function highlightSlashOption(index) {
            var options = slashMenuEl.querySelectorAll('.var-option');
            options.forEach(function(o) { o.classList.remove('highlighted'); });
            if (options[index]) { options[index].classList.add('highlighted'); options[index].scrollIntoView({ block: 'nearest' }); }
        }
        function highlightSlashByEl(el) {
            var options = Array.prototype.slice.call(slashMenuEl.querySelectorAll('.var-option'));
            var idx = options.indexOf(el);
            if (idx !== -1) highlightSlashOption(idx);
        }
        function getHighlightedIndex() {
            var options = Array.prototype.slice.call(slashMenuEl.querySelectorAll('.var-option'));
            for (var i = 0; i < options.length; i++) { if (options[i].classList.contains('highlighted')) return i; }
            return -1;
        }

        function filterSlashMenu() {
            var ta = slashMenu.textarea;
            if (ta.selectionStart <= slashMenu.startPos) { hideSlashMenu(); return; }
            var query = ta.value.substring(slashMenu.startPos + 1, ta.selectionStart);
            if (query.indexOf(' ') !== -1) { hideSlashMenu(); return; }
            slashMenuEl.innerHTML = buildSlashMenuHtml(query);
            highlightSlashOption(0);
        }

        function slashSelect(optionEl, varName) {
            var ta = slashMenu.textarea;
            var tag = '{{' + varName + '}}';
            var val = ta.value;
            var cursorPos = ta.selectionStart;
            ta.value = val.substring(0, slashMenu.startPos) + tag + val.substring(cursorPos);
            var newPos = slashMenu.startPos + tag.length;
            hideSlashMenu();
            ta.focus();
            ta.setSelectionRange(newPos, newPos);
        }

        document.addEventListener('input', function(e) {
            if (e.target.tagName !== 'TEXTAREA') return;
            if (slashMenu.active) { filterSlashMenu(); }
            else {
                var ta = e.target, pos = ta.selectionStart;
                if (pos > 0 && ta.value[pos - 1] === '/') {
                    if (pos === 1) { showSlashMenu(ta, pos - 1); }
                    else {
                        var before = ta.value[pos - 2];
                        if (before <= ' ' || before === '(' || before === '[' || before === '{') showSlashMenu(ta, pos - 1);
                    }
                }
            }
        });

        document.addEventListener('keydown', function(e) {
            if (!slashMenu.active || e.target.tagName !== 'TEXTAREA') return;
            var options = slashMenuEl.querySelectorAll('.var-option');
            if (options.length === 0 && e.key !== 'Escape') return;
            var idx = getHighlightedIndex();
            if (e.key === 'ArrowDown') { e.preventDefault(); highlightSlashOption(Math.min(idx + 1, options.length - 1)); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); highlightSlashOption(Math.max(idx - 1, 0)); }
            else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); var h = slashMenuEl.querySelector('.var-option.highlighted'); if (h) slashSelect(h, h.dataset.var); }
            else if (e.key === 'Escape') { e.preventDefault(); hideSlashMenu(); }
        });

        document.addEventListener('scroll', function(e) {
            if (slashMenu.active && e.target.tagName === 'TEXTAREA') hideSlashMenu();
        }, true);

        document.addEventListener('keydown', function(e) {
            if (e.key !== 'Enter' && e.key !== ' ') return;
            var el = e.target;
            if (el.getAttribute('role') !== 'button') return;
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'BUTTON') return;
            e.preventDefault();
            el.click();
        });

        function toggleAccordion(id) {
            var arrow = document.getElementById(id + '_arrow');
            var body = document.getElementById(id + '_body') || document.getElementById(id + '_body_wrap');
            if (!body) return;
            var expanded = body.style.display !== 'none';
            body.style.display = expanded ? 'none' : '';
            if (arrow) arrow.classList.toggle('expanded', !expanded);
            var card = body.closest('.campaign-card');
            if (card) card.classList.toggle('collapsed', expanded);
            var header = body.previousElementSibling;
            if (header) header.setAttribute('aria-expanded', expanded ? 'false' : 'true');
            updateCampaignUnsavedBadges(id);
            if (expanded) {
                body.querySelectorAll('.vs-customize-area.open').forEach(function(area) {
                    area.classList.remove('open');
                    var rowHeader = area.previousElementSibling;
                    if (rowHeader) rowHeader.setAttribute('aria-expanded', 'false');
                    var areaId = area.id || '';
                    var parts = areaId.replace('vs_customize_', '').split('_');
                    if (parts.length >= 2) {
                        var cKey = parts[0];
                        var vtId = parts.slice(1).join('_');
                        var cArrow = document.getElementById('vs_arrow_' + cKey + '_' + vtId);
                        if (cArrow) cArrow.classList.remove('expanded');
                    }
                });
            }
            updateFoldAllLabel();
            updateFoldCampaignsLabel();
            var vtMatch = id.match(/^vt_(.+)$/);
            if (vtMatch) updateProgressiveReveal(vtMatch[1]);
            requestAnimationFrame(updateSaveBarShadow);
        }

        function isAnyExpanded() {
            var found = false;
            document.querySelectorAll('#visit_types_container .campaign-card:not(.collapsed)').forEach(function() { found = true; });
            if (!found) {
                document.querySelectorAll('.vs-customize-area.open').forEach(function() { found = true; });
            }
            return found;
        }

        function updateFoldAllLabel() {
            var btn = document.getElementById('collapse_all_btn');
            if (!btn) return;
            btn.textContent = isAnyExpanded() ? 'Fold all' : 'Unfold all';
        }

        function foldAll() {
            document.querySelectorAll('#visit_types_container .campaign-card:not(.collapsed)').forEach(function(card) {
                var bodyEl = card.querySelector('.campaign-body');
                if (bodyEl) bodyEl.style.display = 'none';
                card.classList.add('collapsed');
                var arrowEl = card.querySelector('.accordion-icon');
                if (arrowEl) arrowEl.classList.remove('expanded');
                bodyEl.querySelectorAll('.vs-customize-area.open').forEach(function(area) {
                    area.classList.remove('open');
                });
                bodyEl.querySelectorAll('.vs-campaign-row .accordion-icon.expanded').forEach(function(a) {
                    a.classList.remove('expanded');
                });
            });
        }

        function unfoldAll() {
            document.querySelectorAll('#visit_types_container .campaign-card').forEach(function(card) {
                var bodyEl = card.querySelector('.campaign-body');
                if (bodyEl) bodyEl.style.display = '';
                card.classList.remove('collapsed');
                var arrowEl = card.querySelector('.accordion-icon');
                if (arrowEl) arrowEl.classList.add('expanded');
                bodyEl.querySelectorAll('.vs-customize-area').forEach(function(area) {
                    area.classList.add('open');
                });
                bodyEl.querySelectorAll('.vs-campaign-row .accordion-icon').forEach(function(a) {
                    a.classList.add('expanded');
                });
            });
        }

        function updateAllProgressiveReveal() {
            noteTypes.forEach(function(nt) { updateProgressiveReveal(nt.id); });
        }

        function toggleFoldAll() {
            if (isAnyExpanded()) {
                foldAll();
            } else {
                unfoldAll();
            }
            updateFoldAllLabel();
            updateAllProgressiveReveal();
            requestAnimationFrame(updateSaveBarShadow);
        }

        function isAnyCampaignExpanded() {
            var found = false;
            document.querySelectorAll('#global_alerts_container .campaign-card:not(.collapsed), #global_scheduled_container .campaign-card:not(.collapsed)').forEach(function() { found = true; });
            return found;
        }

        function updateFoldCampaignsLabel() {
            var btn = document.getElementById('campaigns_fold_btn');
            if (!btn) return;
            btn.textContent = isAnyCampaignExpanded() ? 'Fold all' : 'Unfold all';
        }

        function toggleFoldCampaigns() {
            var containers = ['global_alerts_container', 'global_scheduled_container'];
            if (isAnyCampaignExpanded()) {
                containers.forEach(function(cid) {
                    document.querySelectorAll('#' + cid + ' .campaign-card:not(.collapsed)').forEach(function(card) {
                        var bodyEl = card.querySelector('.campaign-body');
                        if (bodyEl) bodyEl.style.display = 'none';
                        card.classList.add('collapsed');
                        var arrowEl = card.querySelector('.accordion-icon');
                        if (arrowEl) arrowEl.classList.remove('expanded');
                    });
                });
            } else {
                containers.forEach(function(cid) {
                    document.querySelectorAll('#' + cid + ' .campaign-card').forEach(function(card) {
                        var bodyEl = card.querySelector('.campaign-body');
                        if (bodyEl) bodyEl.style.display = '';
                        card.classList.remove('collapsed');
                        var arrowEl = card.querySelector('.accordion-icon');
                        if (arrowEl) arrowEl.classList.add('expanded');
                    });
                });
            }
            updateFoldCampaignsLabel();
            requestAnimationFrame(updateSaveBarShadow);
        }

        var pendingSwitchTab = null;

        function getActiveTabId() {
            var el = document.querySelector('.tab-item.active');
            return el ? el.dataset.tab : null;
        }

        function isCurrentTabDirty() {
            var tabId = getActiveTabId();
            if (!tabId) return false;
            if (tabId === 'campaigns' || tabId === 'visit-settings') {
                var btn = document.getElementById('save_' + tabId);
                return btn && !btn.disabled;
            }
            return false;
        }

        function doSwitchTab(tabName) {
            clearBanners();
            document.querySelectorAll('.tab-item').forEach(function(t) {
                t.classList.remove('active');
                t.setAttribute('aria-selected', 'false');
            });
            document.querySelectorAll('.tab-panel').forEach(function(t) { t.classList.remove('active'); });
            var tabEl = document.querySelector('.tab-item[data-tab="' + tabName + '"]');
            if (tabEl) {
                tabEl.classList.add('active');
                tabEl.setAttribute('aria-selected', 'true');
            }
            document.getElementById(tabName).classList.add('active');
            localStorage.setItem('pn_admin_tab', tabName);
            if (tabName === 'history') loadHistory();
        }

        function switchTab(tabName) {
            if (isCurrentTabDirty()) {
                pendingSwitchTab = tabName;
                var saveBtn = document.getElementById('unsaved_modal_save');
                var tabId = getActiveTabId();
                if (saveBtn) saveBtn.style.display = (tabId === 'campaigns' || tabId === 'visit-settings') ? '' : 'none';
                openModal('unsaved_modal');
                return;
            }
            doSwitchTab(tabName);
        }

        function closeUnsavedModal() {
            closeModal('unsaved_modal');
            pendingSwitchTab = null;
        }

        async function unsavedModalSave() {
            var tabId = getActiveTabId();
            closeModal('unsaved_modal');
            if (tabId === 'campaigns') await saveCampaignsTab();
            if (tabId === 'visit-settings') await saveVisitSettingsTab();
            if (pendingSwitchTab) {
                doSwitchTab(pendingSwitchTab);
                pendingSwitchTab = null;
            }
        }

        async function unsavedModalDiscard() {
            var tabId = getActiveTabId();
            closeModal('unsaved_modal');
            if (tabId === 'campaigns' || tabId === 'visit-settings') {
                await discardTab(tabId);
            }
            if (pendingSwitchTab) {
                doSwitchTab(pendingSwitchTab);
                pendingSwitchTab = null;
            }
        }

        // --- Duration / interval helpers ---

        function parseDuration(str) {
            str = str.trim().toLowerCase();
            if (!str) return null;
            if (/^\\d+$/.test(str)) return parseInt(str);
            var units = {w: 10080, d: 1440, h: 60, m: 1};
            var total = 0, matched = false, pattern = /(\\d+)\\s*(w|d|h|m)/g, match, lastIndex = 0;
            while ((match = pattern.exec(str)) !== null) {
                if (str.substring(lastIndex, match.index).trim()) return null;
                total += parseInt(match[1]) * units[match[2]];
                matched = true;
                lastIndex = pattern.lastIndex;
            }
            if (str.substring(lastIndex).trim()) return null;
            return matched && total > 0 ? total : null;
        }

        function validateIntervalInput(input, campaignKey) {
            var val = input.value.trim();
            if (!val) { input.classList.remove('valid', 'invalid'); return; }
            if (parseDuration(val) !== null) { input.classList.add('valid'); input.classList.remove('invalid'); }
            else { input.classList.add('invalid'); input.classList.remove('valid'); }
        }

        function formatInterval(minutes, campaignKey) {
            var parts = [];
            if (minutes >= 10080) { parts.push(Math.floor(minutes / 10080) + 'w'); minutes %= 10080; }
            if (minutes >= 1440) { parts.push(Math.floor(minutes / 1440) + 'd'); minutes %= 1440; }
            if (minutes >= 60) { parts.push(Math.floor(minutes / 60) + 'h'); minutes %= 60; }
            if (minutes > 0 || parts.length === 0) parts.push(minutes + 'm');
            return parts.join(' ');
        }

        function sortIntervals(arr, campaignKey) {
            arr.sort(function(a, b) { return b - a; });
        }

        // --- Global interval management ---

        function renderGlobalIntervals(campaignKey) {
            var container = document.getElementById('global_' + campaignKey + '_interval_list');
            if (!container) return;
            var intervals = globalIntervals[campaignKey] || [];
            container.innerHTML = '';
            intervals.forEach(function(val, idx) {
                var tag = document.createElement('div');
                tag.className = 'interval-tag';
                tag.innerHTML = '<span>' + escapeHtml(formatInterval(val, campaignKey)) + '</span><span class="interval-remove" onclick="removeGlobalInterval(\\'' + campaignKey + '\\',' + idx + ')">x</span>';
                container.appendChild(tag);
            });
        }

        function addGlobalInterval(campaignKey) {
            var input = document.getElementById('global_' + campaignKey + '_new_interval');
            var minutes = parseDuration(input.value);
            if (minutes === null) return;
            if (globalIntervals[campaignKey].indexOf(minutes) !== -1) {
                showBanner('That interval is already added.', 'error');
                return;
            }
            globalIntervals[campaignKey].push(minutes);
            sortIntervals(globalIntervals[campaignKey], campaignKey);
            renderGlobalIntervals(campaignKey);
            input.value = '';
            input.classList.remove('valid', 'invalid');
            markTabDirty('campaigns');
        }

        function removeGlobalInterval(campaignKey, index) {
            globalIntervals[campaignKey].splice(index, 1);
            renderGlobalIntervals(campaignKey);
            markTabDirty('campaigns');
        }

        // --- Visit type interval management ---

        function renderVtIntervals(vtId, campaignKey) {
            var ikey = vtId + '_' + campaignKey;
            var container = document.getElementById('vt_interval_list_' + vtId + '_' + campaignKey);
            if (!container) return;
            var intervals = vtIntervals[ikey] || [];
            container.innerHTML = '';
            intervals.forEach(function(val, idx) {
                var tag = document.createElement('div');
                tag.className = 'interval-tag';
                tag.innerHTML = '<span>' + escapeHtml(formatInterval(val, campaignKey)) + '</span><span class="interval-remove" onclick="removeVtInterval(\\'' + vtId + '\\',\\'' + campaignKey + '\\',' + idx + ')">x</span>';
                container.appendChild(tag);
            });
        }

        function addVtInterval(vtId, campaignKey) {
            var ikey = vtId + '_' + campaignKey;
            var input = document.getElementById('vt_new_interval_' + vtId + '_' + campaignKey);
            var minutes = parseDuration(input.value);
            if (minutes === null) return;
            if (!vtIntervals[ikey]) vtIntervals[ikey] = [];
            if (vtIntervals[ikey].indexOf(minutes) !== -1) {
                showBanner('That interval is already added.', 'error');
                return;
            }
            vtIntervals[ikey].push(minutes);
            sortIntervals(vtIntervals[ikey], campaignKey);
            renderVtIntervals(vtId, campaignKey);
            input.value = '';
            input.classList.remove('valid', 'invalid');
            checkCustomizeDirty(vtId, campaignKey);
        }

        function removeVtInterval(vtId, campaignKey, index) {
            var ikey = vtId + '_' + campaignKey;
            vtIntervals[ikey].splice(index, 1);
            renderVtIntervals(vtId, campaignKey);
            checkCustomizeDirty(vtId, campaignKey);
        }

        // --- Channel checkbox helpers ---

        function getChannelCheckboxes(prefix) {
            var channels = [];
            var smsEl = document.getElementById(prefix + '_channel_sms');
            var emailEl = document.getElementById(prefix + '_channel_email');
            if (isToggleChecked(smsEl)) channels.push('sms');
            if (isToggleChecked(emailEl)) channels.push('email');
            return channels;
        }

        function setChannelCheckboxes(prefix, channels) {
            var ch = channels || [];
            var smsEl = document.getElementById(prefix + '_channel_sms');
            var emailEl = document.getElementById(prefix + '_channel_email');
            setToggleChecked(smsEl, ch.indexOf('sms') !== -1);
            setToggleChecked(emailEl, ch.indexOf('email') !== -1);
        }

        // --- Global campaign card rendering ---

        function buildSendTimePicker(idPrefix, dirtyTab) {
            var dirtyCall = dirtyTab ? " markTabDirty(\\'" + dirtyTab + "\\')" : '';
            return '<div class="time-picker-wrap" id="' + idPrefix + '_wrap">' +
                '<div class="time-picker-box" onclick="openTimePicker(\\'' + idPrefix + '\\')">' +
                    '<input type="text" id="' + idPrefix + '_hour" maxlength="2" placeholder="09" ' +
                        'onclick="event.stopPropagation(); this.select()" ' +
                        'oninput="filterTimeDigits(this, 23);' + dirtyCall + '" ' +
                        'onblur="padTimeInput(this)">' +
                    '<span class="tp-colon">:</span>' +
                    '<input type="text" id="' + idPrefix + '_minute" maxlength="2" placeholder="00" ' +
                        'onclick="event.stopPropagation(); this.select()" ' +
                        'oninput="filterTimeDigits(this, 59);' + dirtyCall + '" ' +
                        'onblur="padTimeInput(this)">' +
                    '<span class="tp-icon">T</span>' +
                '</div>' +
                '<div class="tp-dropdown" id="' + idPrefix + '_dropdown">' +
                    '<div class="tp-col" id="' + idPrefix + '_hcol"></div>' +
                    '<div class="tp-col" id="' + idPrefix + '_mcol"></div>' +
                '</div>' +
            '</div>';
        }

        function filterTimeDigits(input, max) {
            input.value = input.value.replace(/[^0-9]/g, '');
            if (input.value.length === 2) {
                var num = parseInt(input.value, 10);
                if (num > max) input.value = String(max);
            }
        }

        function padTimeInput(input) {
            var val = input.value.trim();
            if (val.length === 1) input.value = '0' + val;
            if (val === '') return;
            var max = input.id.indexOf('_hour') !== -1 ? 23 : 59;
            var num = parseInt(input.value, 10);
            if (isNaN(num) || num < 0) input.value = '00';
            else if (num > max) input.value = String(max);
        }

        function openTimePicker(idPrefix) {
            var dropdown = document.getElementById(idPrefix + '_dropdown');
            var isOpen = dropdown.classList.contains('open');
            closeAllTimePickers();
            if (isOpen) return;
            var hourEl = document.getElementById(idPrefix + '_hour');
            var minEl = document.getElementById(idPrefix + '_minute');
            var currentHour = hourEl.value || '09';
            var currentMin = minEl.value || '00';
            var hcol = document.getElementById(idPrefix + '_hcol');
            var mcol = document.getElementById(idPrefix + '_mcol');
            hcol.innerHTML = '';
            mcol.innerHTML = '';
            for (var h = 0; h < 24; h++) {
                var hh = h < 10 ? '0' + h : '' + h;
                var hItem = document.createElement('div');
                hItem.className = 'tp-col-item' + (hh === currentHour ? ' selected' : '');
                hItem.textContent = hh;
                hItem.setAttribute('data-val', hh);
                hItem.onclick = (function(val) {
                    return function(e) {
                        e.stopPropagation();
                        hourEl.value = val;
                        hcol.querySelectorAll('.tp-col-item').forEach(function(el) { el.classList.remove('selected'); });
                        this.classList.add('selected');
                        hourEl.dispatchEvent(new Event('input'));
                    };
                })(hh);
                hcol.appendChild(hItem);
            }
            for (var m = 0; m < 60; m++) {
                var mm = m < 10 ? '0' + m : '' + m;
                var mItem = document.createElement('div');
                mItem.className = 'tp-col-item' + (mm === currentMin ? ' selected' : '');
                mItem.textContent = mm;
                mItem.setAttribute('data-val', mm);
                mItem.onclick = (function(val) {
                    return function(e) {
                        e.stopPropagation();
                        minEl.value = val;
                        mcol.querySelectorAll('.tp-col-item').forEach(function(el) { el.classList.remove('selected'); });
                        this.classList.add('selected');
                        minEl.dispatchEvent(new Event('input'));
                    };
                })(mm);
                mcol.appendChild(mItem);
            }
            dropdown.classList.add('open');
            var selectedH = hcol.querySelector('.selected');
            if (selectedH) selectedH.scrollIntoView({block: 'center'});
            var selectedM = mcol.querySelector('.selected');
            if (selectedM) selectedM.scrollIntoView({block: 'center'});
        }

        function closeAllTimePickers() {
            document.querySelectorAll('.tp-dropdown.open').forEach(function(d) { d.classList.remove('open'); });
        }

        document.addEventListener('click', function(e) {
            if (!e.target.closest('.time-picker-wrap')) closeAllTimePickers();
        });

        function setSendTimePicker(idPrefix, timeStr) {
            var parts = (timeStr || '09:00').split(':');
            var hourEl = document.getElementById(idPrefix + '_hour');
            var minEl = document.getElementById(idPrefix + '_minute');
            if (hourEl) hourEl.value = parts[0] || '09';
            if (minEl) minEl.value = parts[1] || '00';
        }

        function getSendTimeValue(idPrefix) {
            var hourEl = document.getElementById(idPrefix + '_hour');
            var minEl = document.getElementById(idPrefix + '_minute');
            if (!hourEl || !minEl) return '';
            var h = hourEl.value || '09';
            var m = minEl.value || '00';
            if (h.length === 1) h = '0' + h;
            if (m.length === 1) m = '0' + m;
            return h + ':' + m;
        }

        function buildGlobalTemplateHtml(idPrefix, channel, checked, templateValue, dirtyTab) {
            var label = channel === 'sms' ? 'SMS' : 'Email';
            var cardId = idPrefix + '_' + channel + '_card';
            var dirtyInput = dirtyTab ? ' oninput="markTabDirty(\\'' + dirtyTab + '\\')"' : '';
            return '<div class="channel-card" id="' + cardId + '">' +
                '<div class="channel-header">' +
                    '<span class="channel-toggle">' +
                        label +
                        ' <span class="channel-not-configured" data-channel="' + channel + '" style="display:none;color:var(--color-text-muted);font-weight:normal;">(' + (channel === 'sms' ? 'Twilio' : 'SendGrid') + ' not configured)</span>' +
                    '</span>' +
                    '<span class="accordion-actions" onclick="event.stopPropagation()">' +
                        '<span class="badge badge-orange badge-mini template-unsaved" id="' + idPrefix + '_' + channel + '_unsaved" style="display:none;">Unsaved</span>' +
                        '<button type="button" class="btn btn-default btn-xs" onclick="toggleVarDropdown(this)">+ Insert Field</button>' +
                        '<div class="var-dropdown"></div>' +
                    '</span>' +
                '</div>' +
                '<div class="channel-body">' +
                    '<div class="form-group">' +
                        '<textarea id="' + idPrefix + '_' + channel + '_template" placeholder="Type / to insert a field"' + dirtyInput + '>' + escapeHtml(templateValue) + '</textarea>' +
                    '</div>' +
                '</div>' +
            '</div>';
        }

        function buildChannelCardHtml(idPrefix, channel, checked, templateValue, dirtyTab, resetContext) {
            var label = channel === 'sms' ? 'SMS' : 'Email';
            var cardId = idPrefix + '_' + channel + '_card';
            var dirtyCall = dirtyTab ? 'markTabDirty(\\'' + dirtyTab + '\\')' : '';
            var dirtyInput = dirtyTab ? ' oninput="markTabDirty(\\'' + dirtyTab + '\\')"' : '';
            var resetBtn = '';
            if (resetContext) {
                resetBtn = '<button type="button" class="btn btn-default btn-xs" id="' + idPrefix + '_' + channel + '_reset" style="display:none" onclick="resetChannelToGlobal(\\'' + resetContext.vtId + '\\', \\'' + resetContext.campaignKey + '\\', \\'' + channel + '\\')">Reset</button>';
            }
            return '<div class="channel-card" id="' + cardId + '">' +
                '<div class="channel-header">' +
                    '<span class="channel-toggle">' +
                        label +
                        ' <span class="channel-not-configured" data-channel="' + channel + '" style="display:none;color:var(--color-text-muted);font-weight:normal;">(' + (channel === 'sms' ? 'Twilio' : 'SendGrid') + ' not configured)</span>' +
                    '</span>' +
                    '<span class="accordion-actions" onclick="event.stopPropagation()">' +
                        '<span class="vs-channel-inherit-label" id="' + idPrefix + '_' + channel + '_inherit"></span>' +
                        resetBtn +
                        '<button type="button" class="btn btn-default btn-xs" onclick="toggleVarDropdown(this)">+ Insert Field</button>' +
                        '<div class="var-dropdown"></div>' +
                        '<canvas-checkbox id="' + idPrefix + '_channel_' + channel + '" aria-label="' + label + '"' +
                            (checked ? ' checked' : '') +
                            (resetContext ? ' onchange="onVsChannelChange(\\'' + resetContext.vtId + '\\',\\'' + resetContext.campaignKey + '\\')"' : '') +
                        '></canvas-checkbox>' +
                    '</span>' +
                '</div>' +
                '<div class="channel-body">' +
                    '<div class="form-group">' +
                        '<textarea id="' + idPrefix + '_' + channel + '_template" placeholder="Type / to insert a field"' + dirtyInput + '>' + escapeHtml(templateValue) + '</textarea>' +
                    '</div>' +
                '</div>' +
            '</div>';
        }

        function renderCampaignAccordions(config) {
            var alerts = [
                {key: 'confirmation', label: 'Confirmation'},
                {key: 'cancellation', label: 'Cancellation'},
                {key: 'noshow', label: 'No-show'},
            ];
            var scheduled = [
                {key: 'reminder', label: 'Appointment Reminders'},
                {key: 'telehealth', label: 'Telehealth Join'},
            ];
            renderGlobalGroup('global_alerts_container', alerts, config, false);
            renderGlobalGroup('global_scheduled_container', scheduled, config, true);
        }

        function renderGlobalGroup(containerId, campaigns, config, isScheduled) {
            var container = document.getElementById(containerId);
            container.innerHTML = '';
            campaigns.forEach(function(c) {
                var enabledKey = c.key === 'reminder' ? 'reminders_enabled' : c.key + '_enabled';
                var isActive = config[enabledKey] === true;
                var channels = config[c.key + '_channels'] || [];
                var smsTpl = config[c.key + '_sms_template'] || '';
                var emailTpl = config[c.key + '_email_template'] || '';
                var smsOn = channels.indexOf('sms') !== -1;
                var emailOn = channels.indexOf('email') !== -1;
                var prefix = 'global_' + c.key;

                var html = '<div class="campaign-card collapsed" id="' + prefix + '_card">' +
                    '<div class="campaign-header" role="button" tabindex="0" aria-expanded="false" aria-controls="' + prefix + '_body" onclick="toggleAccordion(\\'' + prefix + '\\')">' +
                        '<div style="display:flex;align-items:center;gap:var(--space-tiny);padding:var(--accordion-title-padding);flex:1;">' +
                            '<span class="accordion-icon" id="' + prefix + '_arrow"></span>' +
                            '<span class="campaign-title">' + escapeHtml(c.label) + '</span>' +
                            '<span class="badge badge-orange badge-mini campaign-unsaved" id="' + prefix + '_unsaved" style="display:none;margin-left:auto;">Unsaved</span>' +
                        '</div>' +
                    '</div>' +
                    '<div class="campaign-body" id="' + prefix + '_body" style="display:none;">';

                if (isScheduled) {
                    var hintText = c.key === 'reminder'
                        ? 'Use <code>w</code> weeks, <code>d</code> days, <code>h</code> hours, <code>m</code> minutes. Per-visit-type intervals override these.'
                        : 'Use <code>w</code> weeks, <code>d</code> days, <code>h</code> hours, <code>m</code> minutes.';
                    html += '<div class="form-group">' +
                        '<label>Default Intervals</label>' +
                        '<div class="interval-list" id="' + prefix + '_interval_list"></div>' +
                        '<div class="add-interval">' +
                            '<input type="text" id="' + prefix + '_new_interval" placeholder="Enter interval" oninput="validateIntervalInput(this, \\'' + c.key + '\\')" onkeydown="if(event.key===\\'Enter\\'){event.preventDefault();addGlobalInterval(\\'' + c.key + '\\')}">' +
                            '<button class="btn btn-secondary btn-sm" onclick="addGlobalInterval(\\'' + c.key + '\\')">Add</button>' +
                        '</div>' +
                        '<div class="interval-hint">' + hintText + '</div>' +
                    '</div>';
                }

                if (isScheduled && c.key === 'reminder') {
                    html += '<div class="form-group">' +
                        '<label>Send Time for Day-or-Longer Reminders</label>' +
                        '<div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;">' +
                            buildSendTimePicker('day_out_send', 'campaigns') +
                            '<select id="day_out_timezone" onchange="markTabDirty(\\'campaigns\\')" style="width:auto;">' +
                                '<option value="America/New_York">Eastern (New York)</option>' +
                                '<option value="America/Chicago">Central (Chicago)</option>' +
                                '<option value="America/Denver">Mountain (Denver)</option>' +
                                '<option value="America/Los_Angeles">Pacific (Los Angeles)</option>' +
                                '<option value="America/Anchorage">Alaska (Anchorage)</option>' +
                                '<option value="Pacific/Honolulu">Hawaii (Honolulu)</option>' +
                            '</select>' +
                        '</div>' +
                        '<small style="color:var(--color-text-muted);display:block;margin-top:4px;">Shorter intervals are sent relative to the appointment time.</small>' +
                    '</div>';
                }

                html += buildGlobalTemplateHtml(prefix, 'sms', smsOn, smsTpl, 'campaigns');
                html += buildGlobalTemplateHtml(prefix, 'email', emailOn, emailTpl, 'campaigns');
                html += '</div></div>';
                container.innerHTML += html;
            });
        }

        // --- Visit type rendering ---

        async function loadNoteTypes() {
            try {
                const response = await fetch('/plugin-io/api/patient_notify/admin/note-types');
                noteTypes = await response.json();
            } catch (e) { noteTypes = []; }
            renderVisitSettings();
            updateChannelWarnings();
        }

        function getVisitTypeCampaigns(nt) {
            var campaigns = [
                {key: 'confirmation', prefix: 'confirmation', label: 'Confirmation', hasIntervals: false},
                {key: 'cancellation', prefix: 'cancellation', label: 'Cancellation', hasIntervals: false},
                {key: 'noshow', prefix: 'noshow', label: 'No-show', hasIntervals: false},
                {key: 'reminders', prefix: 'reminder', label: 'Reminders', hasIntervals: true},
            ];
            if (nt.is_telehealth) {
                campaigns.push({key: 'telehealth', prefix: 'telehealth', label: 'Telehealth Join', hasIntervals: true});
            }
            return campaigns;
        }

        function getGlobalTemplateValue(prefix, field) {
            var el = document.getElementById('global_' + prefix + '_' + field + '_template');
            return el ? el.value : '';
        }

        function getCampaignEnabledState(saved, prefix, globalConfig) {
            var enabledKey = prefix === 'reminder' ? 'reminders_enabled' : prefix + '_enabled';
            var ntEnabled = saved[enabledKey];
            if (ntEnabled === null || ntEnabled === undefined) {
                return globalConfig[enabledKey] === true;
            }
            return ntEnabled === true;
        }

        function countActiveAndCustomized(nt, saved, globalConfig) {
            var campaigns = getVisitTypeCampaigns(nt);
            var active = 0;
            var customized = 0;
            campaigns.forEach(function(c) {
                if (getCampaignEnabledState(saved, c.prefix, globalConfig)) active++;
                if (saved[c.prefix + '_override'] === true) customized++;
            });
            return {active: active, total: campaigns.length, customized: customized};
        }

        function updateVisitTypeCounts(vtId) {
            var nt = noteTypes.find(function(n) { return n.id === vtId; });
            if (!nt) return;
            var campaigns = getVisitTypeCampaigns(nt);
            var active = 0;
            campaigns.forEach(function(c) {
                var el = document.getElementById('vs_toggle_' + c.key + '_' + vtId);
                if (isToggleChecked(el)) active++;
            });
            var countEl = document.getElementById('vs_count_' + vtId);
            if (countEl) countEl.textContent = active + '/' + campaigns.length;
        }

        var currentConfig = {};
        var customizeSnapshots = {};

        function renderVisitSettings() {
            var container = document.getElementById('visit_types_container');
            if (!container) return;
            container.innerHTML = '';

            if (noteTypes.length === 0) {
                container.innerHTML = '<p style="color:var(--color-text-muted);font-style:italic;">No schedulable visit types found.</p>';
                return;
            }

            noteTypes.forEach(function(nt) {
                var saved = savedNoteTypeCampaigns[nt.id] || {};
                var campaigns = getVisitTypeCampaigns(nt);
                var counts = countActiveAndCustomized(nt, saved, currentConfig);

                var masterOn = saved.master_enabled !== false;
                var masterTitle = masterOn
                    ? 'Notifications are on for this visit type.'
                    : 'The configuration for this visit type becomes active when you toggle it on.';
                var rowsHtml = '';
                var rowIndex = 0;
                campaigns.forEach(function(c) {
                    rowIndex++;
                    var isEnabled = getCampaignEnabledState(saved, c.prefix, currentConfig);
                    var hasOverride = saved[c.prefix + '_override'] === true;
                    var smsTpl = hasOverride ? (saved[c.prefix + '_sms_template'] || '') : (currentConfig[c.prefix + '_sms_template'] || '');
                    var emailTpl = hasOverride ? (saved[c.prefix + '_email_template'] || '') : (currentConfig[c.prefix + '_email_template'] || '');
                    var channels = hasOverride ? (saved[c.prefix + '_channels'] || []) : (currentConfig[c.prefix + '_channels'] || []);
                    var smsOn = channels.indexOf('sms') !== -1;
                    var emailOn = channels.indexOf('email') !== -1;
                    var vtPrefix = 'vt_' + c.key + '_' + nt.id;

                    if (c.hasIntervals) {
                        var ikey = nt.id + '_' + c.key;
                        if (hasOverride) {
                            vtIntervals[ikey] = (saved[c.prefix + '_intervals'] || []).slice();
                        } else {
                            var globalKey = c.prefix + '_intervals';
                            vtIntervals[ikey] = (currentConfig[globalKey] || []).slice();
                        }
                    }


                    rowsHtml += '<div class="vs-campaign-row" id="vs_row_' + c.key + '_' + nt.id + '">' +
                        '<div class="vs-campaign-row-header" role="button" tabindex="0" aria-expanded="false" aria-controls="vs_customize_' + c.key + '_' + nt.id + '" onclick="toggleCustomize(\\'' + nt.id + '\\', \\'' + c.key + '\\')">' +
                            '<span class="accordion-icon" id="vs_arrow_' + c.key + '_' + nt.id + '"></span>' +
                            '<span class="vs-campaign-name">' + escapeHtml(c.label) + '</span>' +
                            '<div class="vs-campaign-status">' +
                                '<span class="badge badge-blue badge-mini" id="vs_row_status_' + c.key + '_' + nt.id + '" style="display:none">Customized</span>' +
                                '<span class="vs-row-channels" id="vs_row_channels_' + c.key + '_' + nt.id + '"></span>' +
                                '<canvas-checkbox id="vs_toggle_' + c.key + '_' + nt.id + '" aria-label="' + escapeHtml(c.label) + '"' +
                                    (isEnabled ? ' checked' : '') +
                                    ' onclick="event.stopPropagation()" onchange="onVsRowChange(\\'' + nt.id + '\\',\\'' + c.key + '\\')">' +
                                '</canvas-checkbox>' +
                            '</div>' +
                        '</div>' +
                        '<div class="vs-customize-area" id="vs_customize_' + c.key + '_' + nt.id + '">' +
                            '<p class="vs-customize-hint">Edit the templates below to customize this campaign for this visit type.</p>';

                    if (c.key === 'reminders') {
                        rowsHtml += '<div class="form-group" style="margin-top:4px;margin-bottom:12px;">' +
                            '<label>Send Time</label>' +
                            buildSendTimePicker('vt_send_' + nt.id, null) +
                        '</div>';
                    }

                    if (c.hasIntervals) {
                        rowsHtml += '<div class="form-group">' +
                            '<label>Intervals</label>' +
                            '<div class="interval-list" id="vt_interval_list_' + nt.id + '_' + c.key + '"></div>' +
                            '<div class="add-interval">' +
                                '<input type="text" id="vt_new_interval_' + nt.id + '_' + c.key + '" placeholder="Enter interval" oninput="validateIntervalInput(this, \\'' + c.key + '\\')" onkeydown="if(event.key===\\'Enter\\'){event.preventDefault();addVtInterval(\\'' + nt.id + '\\',\\'' + c.key + '\\')}">' +
                                '<button class="btn btn-secondary btn-sm" onclick="addVtInterval(\\'' + nt.id + '\\',\\'' + c.key + '\\')">Add</button>' +
                            '</div>' +
                            '<div class="interval-hint">Use <code>w</code> weeks, <code>d</code> days, <code>h</code> hours, <code>m</code> minutes.</div>' +
                        '</div>';
                    }

                    var rc = {vtId: nt.id, campaignKey: c.key};
                    rowsHtml += buildChannelCardHtml(vtPrefix, 'sms', smsOn, smsTpl, null, rc);
                    rowsHtml += buildChannelCardHtml(vtPrefix, 'email', emailOn, emailTpl, null, rc);

                    rowsHtml += '</div></div>';
                });

                var safeName = escapeHtml(nt.name);
                var teleLabel = nt.is_telehealth ? ' <span class="badge badge-blue badge-mini">Telehealth</span>' : '';
                var customizedBadge = '<span class="badge badge-blue badge-mini" id="vs_customized_' + nt.id + '" style="display:none">Customized</span>';

                var card = document.createElement('div');
                card.className = 'campaign-card collapsed';
                card.id = 'vt_card_' + nt.id;
                card.setAttribute('data-master-on', masterOn ? 'true' : 'false');
                card.innerHTML =
                    '<div class="campaign-header" role="button" tabindex="0" aria-expanded="false" aria-controls="vt_' + nt.id + '_body" onclick="toggleAccordion(\\'vt_' + nt.id + '\\')">' +
                        '<div style="display:flex;align-items:center;gap:var(--space-tiny);padding:var(--accordion-title-padding);flex:1;">' +
                            '<span class="accordion-icon" id="vt_' + nt.id + '_arrow"></span>' +
                            '<span class="campaign-title">' + safeName + teleLabel + '</span>' +
                        '</div>' +
                        '<span class="accordion-actions" onclick="event.stopPropagation()">' +
                            customizedBadge +
                            '<span class="campaign-count" id="vs_count_' + nt.id + '" style="cursor:pointer" onclick="toggleAccordion(\\'' + 'vt_' + nt.id + '\\')">' + counts.active + '/' + counts.total + '</span>' +
                            '<button class="toggle" role="switch" aria-checked="' + (masterOn ? 'true' : 'false') + '" id="vs_master_' + nt.id + '" data-canvas-tooltip="' + masterTitle + '"' +
                                ' onclick="event.stopPropagation();toggleAriaChecked(this);toggleVisitType(\\'' + nt.id + '\\',this.getAttribute(\\\'aria-checked\\\')===\\\'true\\\')">' +
                            '</button>' +
                        '</span>' +
                    '</div>' +
                    '<div class="campaign-body" id="vt_' + nt.id + '_body" style="display:none;">' +
                        '<div id="vs_campaigns_' + nt.id + '">' +
                            rowsHtml +
                        '</div>' +
                    '</div>';

                container.appendChild(card);

                // Render intervals and send times for all campaigns (pre-populated)
                // Attach change detection listeners for customize areas
                campaigns.forEach(function(c) {
                    renderVtIntervals(nt.id, c.key);
                    if (c.key === 'reminders') {
                        var sendTime = (saved.reminder_send_time) || currentConfig.day_out_send_time || '09:00';
                        setSendTimePicker('vt_send_' + nt.id, sendTime);
                    }
                    var area = document.getElementById('vs_customize_' + c.key + '_' + nt.id);
                    if (area) {
                        area.addEventListener('input', function() { checkCustomizeDirty(nt.id, c.key); });
                        area.addEventListener('change', function() { checkCustomizeDirty(nt.id, c.key); });
                    }
                    updateNoChannelWarning(nt.id, c.key);
                    updateCampaignRowStatus(nt.id, c.key);
                });
            });
        }

        async function toggleVisitType(vtId, enabled) {
            var nt = noteTypes.find(function(n) { return n.id === vtId; });
            if (!nt) return;
            var saved = savedNoteTypeCampaigns[vtId] || {};
            saved.note_type_id = vtId;
            saved.note_type_name = nt.name;
            saved.master_enabled = enabled;

            savedNoteTypeCampaigns[vtId] = saved;
            var patch = {};
            patch[vtId] = saved;
            var response = await patchConfig({note_type_campaigns: patch});
            if (!response.ok) {
                showBanner('Failed to update visit type.', 'error');
            }

            applyMasterStateToCard(vtId, enabled);
            updateVisitTypeCounts(vtId);
        }

        function applyMasterStateToCard(vtId, enabled) {
            var card = document.getElementById('vt_card_' + vtId);
            if (card) card.setAttribute('data-master-on', enabled ? 'true' : 'false');
            var toggle = document.getElementById('vs_master_' + vtId);
            if (toggle) {
                var tip = enabled
                    ? 'Notifications are on for this visit type.'
                    : 'The configuration for this visit type becomes active when you toggle it on.';
                toggle.setAttribute('data-canvas-tooltip', tip);
            }
        }

        function onVsRowChange(vtId, campaignKey) {
            updateVisitTypeCounts(vtId);
            updateNoChannelWarning(vtId, campaignKey);
            markTabDirty('visit-settings');
        }

        function onVsChannelChange(vtId, campaignKey) {
            updateRowChannelIndicators(vtId, campaignKey);
            updateNoChannelWarning(vtId, campaignKey);
            markTabDirty('visit-settings');
        }

        function updateRowChannelIndicators(vtId, campaignKey) {
            var vtPrefix = 'vt_' + campaignKey + '_' + vtId;
            var smsOn = isToggleChecked(document.getElementById(vtPrefix + '_channel_sms'));
            var emailOn = isToggleChecked(document.getElementById(vtPrefix + '_channel_email'));
            var el = document.getElementById('vs_row_channels_' + campaignKey + '_' + vtId);
            if (el) {
                el.innerHTML =
                    '<span class="' + (smsOn ? 'ch-on' : '') + '">SMS ' + (smsOn ? '&#10003;' : '&#10005;') + '</span>' +
                    '<span class="' + (emailOn ? 'ch-on' : '') + '">Email ' + (emailOn ? '&#10003;' : '&#10005;') + '</span>';
            }
        }

        function updateCampaignRowStatus(vtId, campaignKey) {
            var prefix = fieldPrefix(campaignKey);
            var vtPrefix = 'vt_' + campaignKey + '_' + vtId;
            var curSms = (document.getElementById(vtPrefix + '_sms_template') || {}).value || '';
            var curEmail = (document.getElementById(vtPrefix + '_email_template') || {}).value || '';
            var globalSms = currentConfig[prefix + '_sms_template'] || '';
            var globalEmail = currentConfig[prefix + '_email_template'] || '';
            var isCustomized = curSms !== globalSms || curEmail !== globalEmail;
            var snap = customizeSnapshots[vtId + '_' + campaignKey];
            var isDirty = false;
            if (snap) {
                if (curSms !== snap.sms || curEmail !== snap.email) isDirty = true;
            }
            var area = document.getElementById('vs_customize_' + campaignKey + '_' + vtId);
            var campaignExpanded = area && area.classList.contains('open');
            var el = document.getElementById('vs_row_status_' + campaignKey + '_' + vtId);
            if (el) {
                if (campaignExpanded) {
                    el.style.display = 'none';
                } else if (isDirty) {
                    el.textContent = 'Unsaved';
                    el.className = 'badge badge-orange badge-mini';
                    el.style.display = '';
                } else if (isCustomized) {
                    el.textContent = 'Customized';
                    el.className = 'badge badge-blue badge-mini';
                    el.style.display = '';
                } else {
                    el.style.display = 'none';
                }
            }
            updateRowChannelIndicators(vtId, campaignKey);
            updateVisitTypeCustomized(vtId);
        }

        function updateProgressiveReveal(vtId) {
            var nt = noteTypes.find(function(n) { return n.id === vtId; });
            if (!nt) return;
            var campaigns = getVisitTypeCampaigns(nt);
            var vtExpanded = false;
            var vtBody = document.getElementById('vt_' + vtId + '_body');
            if (vtBody && vtBody.style.display !== 'none') vtExpanded = true;

            campaigns.forEach(function(c) {
                var area = document.getElementById('vs_customize_' + c.key + '_' + vtId);
                var campaignExpanded = area && area.classList.contains('open');
                var rowBadge = document.getElementById('vs_row_status_' + c.key + '_' + vtId);

                if (vtExpanded && campaignExpanded) {
                    if (rowBadge) rowBadge.style.display = 'none';
                } else if (vtExpanded && !campaignExpanded) {
                    updateCampaignRowStatus(vtId, c.key);
                }
            });
            updateVisitTypeCustomized(vtId);
        }

        function updateVisitTypeCustomized(vtId) {
            var nt = noteTypes.find(function(n) { return n.id === vtId; });
            if (!nt) return;
            var vtBody = document.getElementById('vt_' + vtId + '_body');
            var vtExpanded = vtBody && vtBody.style.display !== 'none';
            var badge = document.getElementById('vs_customized_' + vtId);
            if (!badge) return;

            if (vtExpanded) {
                badge.style.display = 'none';
                return;
            }

            var campaigns = getVisitTypeCampaigns(nt);
            var anyUnsaved = false;
            var anyCustomized = false;
            campaigns.forEach(function(c) {
                var prefix = fieldPrefix(c.key);
                var vtPrefix = 'vt_' + c.key + '_' + vtId;
                var curSms = (document.getElementById(vtPrefix + '_sms_template') || {}).value || '';
                var curEmail = (document.getElementById(vtPrefix + '_email_template') || {}).value || '';
                var globalSms = currentConfig[prefix + '_sms_template'] || '';
                var globalEmail = currentConfig[prefix + '_email_template'] || '';
                var snap = customizeSnapshots[vtId + '_' + c.key];
                if (snap) {
                    if (curSms !== snap.sms || curEmail !== snap.email) anyUnsaved = true;
                }
                if (curSms !== globalSms || curEmail !== globalEmail) anyCustomized = true;
            });

            if (anyUnsaved) {
                badge.textContent = 'Unsaved';
                badge.className = 'badge badge-orange badge-mini';
                badge.style.display = '';
            } else if (anyCustomized) {
                badge.textContent = 'Customized';
                badge.className = 'badge badge-blue badge-mini';
                badge.style.display = '';
            } else {
                badge.style.display = 'none';
            }
        }

        function updateChannelInheritLabel(vtPrefix, channel, inheritsGlobal, isDirty) {
            var el = document.getElementById(vtPrefix + '_' + channel + '_inherit');
            if (!el) return;
            if (isDirty) {
                el.textContent = 'Unsaved';
                el.className = 'badge badge-orange badge-mini';
            } else if (inheritsGlobal) {
                el.textContent = 'Inherits global';
                el.className = 'badge badge-basic badge-mini';
            } else {
                el.textContent = 'Customized';
                el.className = 'badge badge-blue badge-mini';
            }
        }

        function updateNoChannelWarning(vtId, campaignKey) {
            var prefix = fieldPrefix(campaignKey);
            var vtPrefix = 'vt_' + campaignKey + '_' + vtId;
            var curSms = (document.getElementById(vtPrefix + '_sms_template') || {}).value || '';
            var curEmail = (document.getElementById(vtPrefix + '_email_template') || {}).value || '';
            var globalSms = currentConfig[prefix + '_sms_template'] || '';
            var globalEmail = currentConfig[prefix + '_email_template'] || '';
            updateChannelInheritLabel(vtPrefix, 'sms', curSms === globalSms, false);
            updateChannelInheritLabel(vtPrefix, 'email', curEmail === globalEmail, false);
        }


        function toggleCustomize(vtId, campaignKey) {
            var area = document.getElementById('vs_customize_' + campaignKey + '_' + vtId);
            if (!area) return;
            area.classList.toggle('open');
            var isOpen = area.classList.contains('open');
            var arrow = document.getElementById('vs_arrow_' + campaignKey + '_' + vtId);
            if (arrow) arrow.classList.toggle('expanded', isOpen);
            var rowHeader = area.previousElementSibling;
            if (rowHeader) rowHeader.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
            if (area.classList.contains('open')) {
                var key = vtId + '_' + campaignKey;
                if (!customizeSnapshots[key]) snapshotCustomize(vtId, campaignKey);
                checkCustomizeDirty(vtId, campaignKey);
            }
            updateProgressiveReveal(vtId);
            updateFoldAllLabel();
            requestAnimationFrame(updateSaveBarShadow);
        }

        function snapshotCustomize(vtId, campaignKey) {
            var prefix = fieldPrefix(campaignKey);
            var vtPrefix = 'vt_' + campaignKey + '_' + vtId;
            var snap = {
                sms: (document.getElementById(vtPrefix + '_sms_template') || {}).value || '',
                email: (document.getElementById(vtPrefix + '_email_template') || {}).value || '',
                intervals: (vtIntervals[vtId + '_' + campaignKey] || []).slice(),
            };
            if (campaignKey === 'reminders') {
                snap.sendTime = getSendTimeValue('vt_send_' + vtId);
            }
            customizeSnapshots[vtId + '_' + campaignKey] = snap;
        }

        function checkCustomizeDirty(vtId, campaignKey) {
            var key = vtId + '_' + campaignKey;
            var snap = customizeSnapshots[key];
            if (!snap) return;
            var vtPrefix = 'vt_' + campaignKey + '_' + vtId;

            var prefix = fieldPrefix(campaignKey);
            var curSms = (document.getElementById(vtPrefix + '_sms_template') || {}).value || '';
            var curEmail = (document.getElementById(vtPrefix + '_email_template') || {}).value || '';
            var globalSms = currentConfig[prefix + '_sms_template'] || '';
            var globalEmail = currentConfig[prefix + '_email_template'] || '';
            var smsDirty = curSms !== snap.sms;
            var emailDirty = curEmail !== snap.email;
            updateChannelInheritLabel(vtPrefix, 'sms', curSms === globalSms, smsDirty);
            updateChannelInheritLabel(vtPrefix, 'email', curEmail === globalEmail, emailDirty);
            updateResetButtons(vtId, campaignKey);
            updateCampaignRowStatus(vtId, campaignKey);
            checkTabDirty('visit-settings');
        }

        function resetToGlobal(vtId, campaignKey) {
            var prefix = fieldPrefix(campaignKey);
            var vtPrefix = 'vt_' + campaignKey + '_' + vtId;

            // Read current global templates and populate form fields as draft
            var globalSms = currentConfig[prefix + '_sms_template'] || '';
            var globalEmail = currentConfig[prefix + '_email_template'] || '';

            var smsEl = document.getElementById(vtPrefix + '_sms_template');
            if (smsEl) smsEl.value = globalSms;
            var emailEl = document.getElementById(vtPrefix + '_email_template');
            if (emailEl) emailEl.value = globalEmail;

            if (campaignKey === 'reminders' || campaignKey === 'telehealth') {
                var globalKey = prefix + '_intervals';
                var ikey = vtId + '_' + campaignKey;
                vtIntervals[ikey] = (currentConfig[globalKey] || []).slice();
                renderVtIntervals(vtId, campaignKey);
            }
            if (campaignKey === 'reminders') {
                setSendTimePicker('vt_send_' + vtId, currentConfig.day_out_send_time || '09:00');
            }

            checkCustomizeDirty(vtId, campaignKey);
        }

        function resetChannelToGlobal(vtId, campaignKey, channel) {
            var prefix = fieldPrefix(campaignKey);
            var vtPrefix = 'vt_' + campaignKey + '_' + vtId;
            var globalTpl = currentConfig[prefix + '_' + channel + '_template'] || '';
            var el = document.getElementById(vtPrefix + '_' + channel + '_template');
            if (el) el.value = globalTpl;
            checkCustomizeDirty(vtId, campaignKey);
        }

        function updateResetButtons(vtId, campaignKey) {
            var prefix = fieldPrefix(campaignKey);
            var vtPrefix = 'vt_' + campaignKey + '_' + vtId;
            ['sms', 'email'].forEach(function(ch) {
                var btn = document.getElementById(vtPrefix + '_' + ch + '_reset');
                if (!btn) return;
                var curTpl = (document.getElementById(vtPrefix + '_' + ch + '_template') || {}).value || '';
                var globalTpl = currentConfig[prefix + '_' + ch + '_template'] || '';
                btn.style.display = (curTpl !== globalTpl) ? '' : 'none';
            });
        }

        // --- Gather / save / load ---

        function gatherSingleCampaign(vtId, campaignKey) {
            var nt = noteTypes.find(function(n) { return n.id === vtId; });
            if (!nt) return null;
            var prefix = fieldPrefix(campaignKey);
            var vtPrefix = 'vt_' + campaignKey + '_' + vtId;
            var entry = {};
            entry.note_type_id = vtId;
            entry.note_type_name = nt.name;

            var enabledKey = prefix === 'reminder' ? 'reminders_enabled' : prefix + '_enabled';
            entry[enabledKey] = isToggleChecked(document.getElementById('vs_toggle_' + campaignKey + '_' + vtId));

            var channels = [];
            if (isToggleChecked(document.getElementById(vtPrefix + '_channel_sms'))) channels.push('sms');
            if (isToggleChecked(document.getElementById(vtPrefix + '_channel_email'))) channels.push('email');
            entry[prefix + '_channels'] = channels;
            entry[prefix + '_sms_template'] = (document.getElementById(vtPrefix + '_sms_template') || {}).value || '';
            entry[prefix + '_email_template'] = (document.getElementById(vtPrefix + '_email_template') || {}).value || '';
            if (campaignKey === 'reminders' || campaignKey === 'telehealth') {
                entry[prefix + '_intervals'] = (vtIntervals[vtId + '_' + campaignKey] || []).slice();
            }
            if (campaignKey === 'reminders') {
                entry.reminder_send_time = getSendTimeValue('vt_send_' + vtId);
            }
            return entry;
        }

        function validateSingleCampaign(data, prefix, label, hasIntervals) {
            var errors = [];
            if (!data || !data[prefix + '_override']) return errors;
            var channels = data[prefix + '_channels'] || [];
            if (channels.length === 0) {
                errors.push(label + ': enable at least one channel');
            }
            if (hasIntervals) {
                var intervals = data[prefix + '_intervals'] || [];
                if (intervals.length === 0) {
                    errors.push(label + ': add at least one interval');
                }
            }
            channels.forEach(function(ch) {
                var tpl = data[prefix + '_' + ch + '_template'] || '';
                if (tpl.trim() === '') {
                    errors.push(label + ': ' + ch.toUpperCase() + ' template cannot be empty');
                }
            });
            return errors;
        }

        function validateGlobalTemplates() {
            var errors = [];
            var campaigns = [
                {prefix: 'confirmation', label: 'Confirmation'},
                {prefix: 'cancellation', label: 'Cancellation'},
                {prefix: 'noshow', label: 'No-show'},
                {prefix: 'reminder', label: 'Reminders'},
                {prefix: 'telehealth', label: 'Telehealth Join'},
            ];
            campaigns.forEach(function(c) {
                var sms = (document.getElementById('global_' + c.prefix + '_sms_template') || {}).value || '';
                if (sms.trim() === '') {
                    errors.push(c.label + ': SMS template cannot be empty');
                }
                var email = (document.getElementById('global_' + c.prefix + '_email_template') || {}).value || '';
                if (email.trim() === '') {
                    errors.push(c.label + ': email template cannot be empty');
                }
            });
            return errors;
        }

        var tabSnapshots = {};

        function gatherTabState(tabId) {
            if (tabId === 'campaigns') {
                return JSON.stringify({
                    confirmation_sms: (document.getElementById('global_confirmation_sms_template') || {}).value || '',
                    confirmation_email: (document.getElementById('global_confirmation_email_template') || {}).value || '',
                    cancellation_sms: (document.getElementById('global_cancellation_sms_template') || {}).value || '',
                    cancellation_email: (document.getElementById('global_cancellation_email_template') || {}).value || '',
                    noshow_sms: (document.getElementById('global_noshow_sms_template') || {}).value || '',
                    noshow_email: (document.getElementById('global_noshow_email_template') || {}).value || '',
                    reminder_sms: (document.getElementById('global_reminder_sms_template') || {}).value || '',
                    reminder_email: (document.getElementById('global_reminder_email_template') || {}).value || '',
                    reminder_intervals: (globalIntervals.reminder || []).slice(),
                    telehealth_sms: (document.getElementById('global_telehealth_sms_template') || {}).value || '',
                    telehealth_email: (document.getElementById('global_telehealth_email_template') || {}).value || '',
                    telehealth_intervals: (globalIntervals.telehealth || []).slice(),
                    send_time: getSendTimeValue('day_out_send'),
                    timezone: (document.getElementById('day_out_timezone') || {}).value || '',
                });
            }
            if (tabId === 'visit-settings') {
                var state = {};
                noteTypes.forEach(function(nt) {
                    var campaigns = getVisitTypeCampaigns(nt);
                    campaigns.forEach(function(c) {
                        var vtPrefix = 'vt_' + c.key + '_' + nt.id;
                        var k = nt.id + '_' + c.key;
                        state[k + '_sms'] = (document.getElementById(vtPrefix + '_sms_template') || {}).value || '';
                        state[k + '_email'] = (document.getElementById(vtPrefix + '_email_template') || {}).value || '';
                        state[k + '_enabled'] = isToggleChecked(document.getElementById('vs_toggle_' + c.key + '_' + nt.id));
                        state[k + '_smsCh'] = isToggleChecked(document.getElementById(vtPrefix + '_channel_sms'));
                        state[k + '_emailCh'] = isToggleChecked(document.getElementById(vtPrefix + '_channel_email'));
                        if (c.hasIntervals) {
                            state[k + '_intervals'] = (vtIntervals[nt.id + '_' + c.key] || []).slice();
                        }
                        if (c.key === 'reminders') {
                            state[k + '_sendTime'] = getSendTimeValue('vt_send_' + nt.id);
                        }
                    });
                });
                return JSON.stringify(state);
            }
            return '';
        }

        function snapshotTab(tabId) {
            tabSnapshots[tabId] = gatherTabState(tabId);
        }

        function snapshotAllTabs() {
            snapshotTab('campaigns');
            snapshotTab('visit-settings');
        }

        function markTabDirty(tabId) {
            checkTabDirty(tabId);
            if (tabId === 'campaigns') updateAllCampaignBadges();
        }

        function checkTabDirty(tabId) {
            var current = gatherTabState(tabId);
            var isDirty = current !== tabSnapshots[tabId];
            var btn = document.getElementById('save_' + tabId);
            var discard = document.getElementById('discard_' + tabId);
            if (btn) btn.disabled = !isDirty;
            if (discard) discard.disabled = !isDirty;
            if (tabId === 'visit-settings') updateResetAllState();
        }

        function updateResetAllState() {
            var resetAll = document.getElementById('reset_all_vs');
            if (!resetAll) return;
            var anyCustomized = false;
            noteTypes.forEach(function(nt) {
                var campaigns = getVisitTypeCampaigns(nt);
                campaigns.forEach(function(c) {
                    var prefix = fieldPrefix(c.key);
                    var vtPrefix = 'vt_' + c.key + '_' + nt.id;
                    var curSms = (document.getElementById(vtPrefix + '_sms_template') || {}).value || '';
                    var curEmail = (document.getElementById(vtPrefix + '_email_template') || {}).value || '';
                    var globalSms = currentConfig[prefix + '_sms_template'] || '';
                    var globalEmail = currentConfig[prefix + '_email_template'] || '';
                    if (curSms !== globalSms || curEmail !== globalEmail) anyCustomized = true;
                });
            });
            resetAll.disabled = !anyCustomized;
        }

        function clearTabDirty(tabId) {
            snapshotTab(tabId);
            var btn = document.getElementById('save_' + tabId);
            var discard = document.getElementById('discard_' + tabId);
            if (btn) btn.disabled = true;
            if (discard) discard.disabled = true;
            if (tabId === 'campaigns') {
                updateAllCampaignBadges();
            }
            if (tabId === 'visit-settings') {
                updateResetAllState();
            }
        }

        function updateCampaignUnsavedBadges(id) {
            var prefix = id;
            var key = prefix.replace('global_', '');
            var smsEl = document.getElementById(prefix + '_sms_template');
            var emailEl = document.getElementById(prefix + '_email_template');
            if (!smsEl && !emailEl) return;

            var smsDirty = smsEl && (smsEl.value || '') !== (currentConfig[key + '_sms_template'] || '');
            var emailDirty = emailEl && (emailEl.value || '') !== (currentConfig[key + '_email_template'] || '');
            var anyDirty = smsDirty || emailDirty;

            var card = document.getElementById(prefix + '_card');
            var isCollapsed = card && card.classList.contains('collapsed');

            var headerBadge = document.getElementById(prefix + '_unsaved');
            var smsBadge = document.getElementById(prefix + '_sms_unsaved');
            var emailBadge = document.getElementById(prefix + '_email_unsaved');

            if (headerBadge) headerBadge.style.display = (anyDirty && isCollapsed) ? '' : 'none';
            if (smsBadge) smsBadge.style.display = (smsDirty && !isCollapsed) ? '' : 'none';
            if (emailBadge) emailBadge.style.display = (emailDirty && !isCollapsed) ? '' : 'none';
        }

        function updateAllCampaignBadges() {
            ['confirmation', 'cancellation', 'noshow', 'reminder', 'telehealth'].forEach(function(key) {
                updateCampaignUnsavedBadges('global_' + key);
            });
        }

        window.addEventListener('beforeunload', function(e) {
            var anyDirty = false;
            ['save_campaigns', 'save_visit-settings'].forEach(function(id) {
                var btn = document.getElementById(id);
                if (btn && !btn.disabled) anyDirty = true;
            });
            if (anyDirty) {
                e.preventDefault();
                e.returnValue = '';
            }
        });

        function setField(id, value) {
            var el = document.getElementById(id);
            if (!el) return;
            if (el.getAttribute('role') === 'switch' || el.tagName === 'CANVAS-CHECKBOX') {
                setToggleChecked(el, !!value);
            } else if (el.type === 'checkbox') {
                el.checked = !!value;
            } else {
                el.value = value || '';
            }
        }

        function populateCampaignsFields(config) {
            var campaigns = ['confirmation', 'cancellation', 'noshow', 'reminder', 'telehealth'];
            campaigns.forEach(function(key) {
                var prefix = 'global_' + key;
                setField(prefix + '_sms_template', config[key + '_sms_template']);
                setField(prefix + '_email_template', config[key + '_email_template']);
                var channels = config[key + '_channels'] || [];
                setField(prefix + '_channel_sms', channels.indexOf('sms') !== -1);
                setField(prefix + '_channel_email', channels.indexOf('email') !== -1);
            });
            setSendTimePicker('day_out_send', config.day_out_send_time || '09:00');
            setField('day_out_timezone', config.day_out_timezone || 'America/New_York');
            globalIntervals.reminder = (config.reminder_intervals || []).slice();
            globalIntervals.telehealth = (config.telehealth_intervals || []).slice();
            renderGlobalIntervals('reminder');
            renderGlobalIntervals('telehealth');
        }

        function populateVisitSettingsFields(config) {
            savedNoteTypeCampaigns = config.note_type_campaigns || {};
            currentConfig = config;
            renderVisitSettings();
        }

        async function discardTab(tabId) {
            var response = await fetch('/plugin-io/api/patient_notify/admin/config');
            var config = await response.json();
            if (tabId === 'campaigns') {
                populateCampaignsFields(config);
            } else if (tabId === 'visit-settings') {
                currentConfig = config;
                savedNoteTypeCampaigns = config.note_type_campaigns || {};
                restoreVsFields();
                snapshotVsCampaigns();
            }
            clearTabDirty(tabId);
                    }

        async function patchConfig(partial) {
            var response = await fetch('/plugin-io/api/patient_notify/admin/config', {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(partial)
            });
            return response;
        }


        async function saveCampaignsTab() {
            clearBanners();
            var errors = validateGlobalTemplates();
            if (errors.length > 0) {
                showBanner(errors[0], 'error');
                return;
            }

            var partial = {
                confirmation_sms_template: document.getElementById('global_confirmation_sms_template').value,
                confirmation_email_template: document.getElementById('global_confirmation_email_template').value,
                cancellation_sms_template: document.getElementById('global_cancellation_sms_template').value,
                cancellation_email_template: document.getElementById('global_cancellation_email_template').value,
                noshow_sms_template: document.getElementById('global_noshow_sms_template').value,
                noshow_email_template: document.getElementById('global_noshow_email_template').value,
                reminder_sms_template: document.getElementById('global_reminder_sms_template').value,
                reminder_email_template: document.getElementById('global_reminder_email_template').value,
                reminder_intervals: (globalIntervals.reminder || []).slice(),
                telehealth_sms_template: document.getElementById('global_telehealth_sms_template').value,
                telehealth_email_template: document.getElementById('global_telehealth_email_template').value,
                telehealth_intervals: (globalIntervals.telehealth || []).slice(),
                day_out_send_time: getSendTimeValue('day_out_send'),
                day_out_timezone: (document.getElementById('day_out_timezone') || {}).value || 'America/New_York',
            };
            var response = await patchConfig(partial);
            if (response.ok) {
                currentConfig = Object.assign(currentConfig, partial);
                                clearTabDirty('campaigns');
            } else {
                var errData = await response.json().catch(function() { return {}; });
                showBanner(errData.error || 'Failed to save campaigns.', 'error');
            }
        }

        async function saveVisitSettingsTab() {
            clearBanners();
            var allPatches = {};
            var errors = [];
            noteTypes.forEach(function(nt) {
                var campaigns = getVisitTypeCampaigns(nt);
                campaigns.forEach(function(c) {
                    var prefix = fieldPrefix(c.key);
                    var entry = gatherSingleCampaign(nt.id, c.key);
                    if (!entry) return;

                    var channels = entry[prefix + '_channels'] || [];
                    var smsTpl = entry[prefix + '_sms_template'] || '';
                    var emailTpl = entry[prefix + '_email_template'] || '';
                    if (channels.indexOf('sms') !== -1 && smsTpl.trim() === '') {
                        errors.push(nt.name + ' ' + c.label + ': SMS template cannot be empty');
                    }
                    if (channels.indexOf('email') !== -1 && emailTpl.trim() === '') {
                        errors.push(nt.name + ' ' + c.label + ': email template cannot be empty');
                    }
                    if (c.hasIntervals) {
                        var intervals = entry[prefix + '_intervals'] || [];
                        if (intervals.length === 0) {
                            errors.push(nt.name + ' ' + c.label + ': add at least one interval');
                        }
                    }

                    var globalSms = currentConfig[prefix + '_sms_template'] || '';
                    var globalEmail = currentConfig[prefix + '_email_template'] || '';
                    var globalChannels = (currentConfig[prefix + '_channels'] || []).slice().sort();
                    var sortedChannels = channels.slice().sort();
                    var matchesGlobal = smsTpl === globalSms && emailTpl === globalEmail &&
                        JSON.stringify(sortedChannels) === JSON.stringify(globalChannels);
                    if (matchesGlobal && c.hasIntervals) {
                        matchesGlobal = JSON.stringify(entry[prefix + '_intervals']) === JSON.stringify(currentConfig[prefix + '_intervals'] || []);
                    }
                    if (matchesGlobal && c.key === 'reminders') {
                        matchesGlobal = entry.reminder_send_time === (currentConfig.day_out_send_time || '09:00');
                    }
                    entry[prefix + '_override'] = !matchesGlobal;

                    if (!allPatches[nt.id]) allPatches[nt.id] = Object.assign({}, savedNoteTypeCampaigns[nt.id] || {});
                    Object.assign(allPatches[nt.id], entry);
                });
            });

            if (errors.length > 0) {
                showBanner(errors[0], 'error');
                return;
            }

            var response = await patchConfig({note_type_campaigns: allPatches});
            if (response.ok) {
                Object.keys(allPatches).forEach(function(vtId) {
                    savedNoteTypeCampaigns[vtId] = allPatches[vtId];
                });
                noteTypes.forEach(function(nt) {
                    var campaigns = getVisitTypeCampaigns(nt);
                    campaigns.forEach(function(c) {
                        snapshotCustomize(nt.id, c.key);
                        updateCampaignRowStatus(nt.id, c.key);
                        updateResetButtons(nt.id, c.key);
                        updateNoChannelWarning(nt.id, c.key);
                    });
                    updateVisitTypeCounts(nt.id);
                });
                                clearTabDirty('visit-settings');
            } else {
                var errData = await response.json().catch(function() { return {}; });
                showBanner(errData.error || 'Failed to save visit settings.', 'error');
            }
        }

        function resetAllToGlobal() {
            noteTypes.forEach(function(nt) {
                var campaigns = getVisitTypeCampaigns(nt);
                campaigns.forEach(function(c) {
                    resetToGlobal(nt.id, c.key);
                });
            });
            checkTabDirty('visit-settings');
        }

        function restoreVsFields() {
            noteTypes.forEach(function(nt) {
                var saved = savedNoteTypeCampaigns[nt.id] || {};
                var campaigns = getVisitTypeCampaigns(nt);
                campaigns.forEach(function(c) {
                    var prefix = fieldPrefix(c.key);
                    var vtPrefix = 'vt_' + c.key + '_' + nt.id;
                    var hasOverride = saved[prefix + '_override'] === true;
                    var smsTpl = hasOverride ? (saved[prefix + '_sms_template'] || '') : (currentConfig[prefix + '_sms_template'] || '');
                    var emailTpl = hasOverride ? (saved[prefix + '_email_template'] || '') : (currentConfig[prefix + '_email_template'] || '');
                    var channels = hasOverride ? (saved[prefix + '_channels'] || []) : (currentConfig[prefix + '_channels'] || []);
                    setField(vtPrefix + '_sms_template', smsTpl);
                    setField(vtPrefix + '_email_template', emailTpl);
                    setField(vtPrefix + '_channel_sms', channels.indexOf('sms') !== -1);
                    setField(vtPrefix + '_channel_email', channels.indexOf('email') !== -1);
                    setField('vs_toggle_' + c.key + '_' + nt.id, getCampaignEnabledState(saved, prefix, currentConfig));
                    if (c.hasIntervals) {
                        var ikey = nt.id + '_' + c.key;
                        if (hasOverride) {
                            vtIntervals[ikey] = (saved[prefix + '_intervals'] || []).slice();
                        } else {
                            vtIntervals[ikey] = (currentConfig[prefix + '_intervals'] || []).slice();
                        }
                        renderVtIntervals(nt.id, c.key);
                    }
                    if (c.key === 'reminders') {
                        var sendTime = (saved.reminder_send_time) || currentConfig.day_out_send_time || '09:00';
                        setSendTimePicker('vt_send_' + nt.id, sendTime);
                    }
                    updateResetButtons(nt.id, c.key);
                    updateNoChannelWarning(nt.id, c.key);
                    updateCampaignRowStatus(nt.id, c.key);
                });
                updateVisitTypeCounts(nt.id);
            });
        }

        function snapshotVsCampaigns() {
            noteTypes.forEach(function(nt) {
                var campaigns = getVisitTypeCampaigns(nt);
                campaigns.forEach(function(c) {
                    snapshotCustomize(nt.id, c.key);
                });
            });
        }

        async function saveCustomVariables() {
            clearBanners();
            var partial = {custom_variables: gatherCustomVariables()};
            var response = await patchConfig(partial);
            if (response.ok) {
                            } else {
                showBanner('Failed to save variables.', 'error');
            }
        }

        async function loadConfig() {
            var response = await fetch('/plugin-io/api/patient_notify/admin/config');
            var config = await response.json();
            currentConfig = config;

            // Render global campaign accordion cards
            renderCampaignAccordions(config);

            // Populate global send time and timezone (rendered inside the reminders accordion)
            setSendTimePicker('day_out_send', config.day_out_send_time || '09:00');
            var tzEl = document.getElementById('day_out_timezone');
            if (tzEl) tzEl.value = config.day_out_timezone || 'America/New_York';

            // Load global intervals for scheduled types
            globalIntervals.reminder = (config.reminder_intervals || []).slice();
            globalIntervals.telehealth = (config.telehealth_intervals || []).slice();
            renderGlobalIntervals('reminder');
            renderGlobalIntervals('telehealth');

            // Custom variables
            customVariablesList = [];
            var cv = config.custom_variables || {};
            Object.keys(cv).forEach(function(k) { customVariablesList.push({key: k, value: cv[k]}); });
            renderCustomVariables();

            loadIntegrationStatus();

            savedNoteTypeCampaigns = config.note_type_campaigns || {};
            await loadNoteTypes();
            snapshotVsCampaigns();

            // Snapshot all tabs after DOM is fully populated
            snapshotAllTabs();
            updateResetAllState();
        }

        // --- Integration status ---

        var twilioConfigured = true;
        var sendgridConfigured = true;

        async function loadIntegrationStatus() {
            try {
                var response = await fetch('/plugin-io/api/patient_notify/admin/integration-status');
                var data = await response.json();
                twilioConfigured = data.twilio_configured;
                sendgridConfigured = data.sendgrid_configured;
                document.getElementById('integration_loading').style.display = 'none';
                document.getElementById('integration_details').style.display = '';
                var twilioEl = document.getElementById('twilio_status_icon');
                twilioEl.textContent = data.twilio_configured ? 'Configured' : 'Not configured';
                twilioEl.style.color = data.twilio_configured ? 'var(--color-primary)' : 'var(--color-danger)';
                twilioEl.style.fontWeight = '700';
                var sendgridEl = document.getElementById('sendgrid_status_icon');
                sendgridEl.textContent = data.sendgrid_configured ? 'Configured' : 'Not configured';
                sendgridEl.style.color = data.sendgrid_configured ? 'var(--color-primary)' : 'var(--color-danger)';
                sendgridEl.style.fontWeight = '700';
                if (!data.twilio_configured && !data.sendgrid_configured) {
                    document.getElementById('integration_fallback_note').style.display = '';
                }
                updateChannelWarnings();
            } catch (e) {
                document.getElementById('integration_loading').textContent = 'Could not check integration status.';
            }
        }

        function updateChannelWarnings() {
            document.querySelectorAll('.channel-not-configured').forEach(function(el) {
                var channel = el.getAttribute('data-channel');
                if ((channel === 'sms' && !twilioConfigured) || (channel === 'email' && !sendgridConfigured)) {
                    el.style.display = '';
                } else {
                    el.style.display = 'none';
                }
            });
        }

        // --- Custom variables ---

        function renderCustomVariables() {
            var tbody = document.getElementById('custom_variables_body');
            tbody.innerHTML = '';
            customVariablesList.forEach(function(cv, index) {
                var row = tbody.insertRow();
                row.innerHTML =
                    '<td style="padding:6px 8px;border-bottom:1px solid var(--color-border);"><code>' + escapeHtml(cv.key) + '</code></td>' +
                    '<td style="padding:6px 8px;border-bottom:1px solid var(--color-border);">' + escapeHtml(cv.value) + '</td>' +
                    '<td style="padding:6px 8px;border-bottom:1px solid var(--color-border);"><button class="btn btn-default btn-sm" style="width:100%;" onclick="confirmRemoveVariable(' + index + ')">Remove</button></td>';
            });
        }


        function showCvError(field, message) {
            var errorEl = document.getElementById('new_cv_' + field + '_error');
            var inputEl = document.getElementById('new_cv_' + field);
            errorEl.textContent = message;
            errorEl.style.display = 'block';
            inputEl.style.borderColor = 'var(--color-danger)';
        }

        function clearCvError(field) {
            var errorEl = document.getElementById('new_cv_' + field + '_error');
            var inputEl = document.getElementById('new_cv_' + field);
            errorEl.style.display = 'none';
            inputEl.style.borderColor = '#E9E9E9';
        }

        function validateCvKey() {
            var keyInput = document.getElementById('new_cv_key');
            var raw = keyInput.value.trim();
            if (!raw) {
                showCvError('key', 'Variable name is required');
                return false;
            }
            if (!/^[a-zA-Z0-9_]+$/.test(raw)) {
                showCvError('key', 'Only letters, numbers, and underscores allowed');
                return false;
            }
            var duplicate = customVariablesList.some(function(cv) { return cv.key === raw; });
            if (duplicate) {
                showCvError('key', 'A variable with this name already exists');
                return false;
            }
            clearCvError('key');
            return true;
        }

        function validateCvValue() {
            var valueInput = document.getElementById('new_cv_value');
            if (!valueInput.value.trim()) {
                showCvError('value', 'Value is required');
                return false;
            }
            clearCvError('value');
            return true;
        }

        function handleCvKeydown(event, field) {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            if (field === 'key') {
                if (!validateCvKey()) {
                    document.getElementById('new_cv_key').focus();
                    return;
                }
                var valueInput = document.getElementById('new_cv_value');
                if (!valueInput.value.trim()) {
                    valueInput.focus();
                    return;
                }
                addCustomVariable();
            } else {
                var keyInput = document.getElementById('new_cv_key');
                if (!keyInput.value.trim()) {
                    showCvError('key', 'Variable name is required');
                    keyInput.focus();
                    return;
                }
                if (!validateCvKey()) {
                    keyInput.focus();
                    return;
                }
                if (!validateCvValue()) {
                    document.getElementById('new_cv_value').focus();
                    return;
                }
                addCustomVariable();
            }
        }

        function addCustomVariable() {
            var keyValid = validateCvKey();
            var valueValid = validateCvValue();
            if (!keyValid) {
                document.getElementById('new_cv_key').focus();
                return;
            }
            if (!valueValid) {
                document.getElementById('new_cv_value').focus();
                return;
            }
            var keyInput = document.getElementById('new_cv_key');
            var valueInput = document.getElementById('new_cv_value');
            var key = keyInput.value.trim().replace(/[^a-zA-Z0-9_]/g, '_');
            var value = valueInput.value.trim();
            customVariablesList.push({key: key, value: value});
            renderCustomVariables();
            keyInput.value = '';
            valueInput.value = '';
            clearCvError('key');
            clearCvError('value');
            keyInput.focus();
            document.querySelectorAll('.var-dropdown').forEach(function(d) { d.innerHTML = ''; });
            saveCustomVariables();
        }

        var campaignLabels = {
            confirmation: 'Confirmation', cancellation: 'Cancellation',
            noshow: 'No-show', reminder: 'Reminders', telehealth: 'Telehealth Join'
        };

        function findVariableUsages(varKey) {
            var pattern = '{{' + varKey + '}}';
            var usages = [];
            var textareas = document.querySelectorAll('textarea[id$="_template"]');
            textareas.forEach(function(ta) {
                if (ta.value.indexOf(pattern) === -1) return;
                var id = ta.id;
                var channel = id.indexOf('_sms_') !== -1 ? 'SMS' : 'Email';
                if (id.startsWith('global_')) {
                    var key = id.replace('global_', '').replace('_sms_template', '').replace('_email_template', '');
                    var label = campaignLabels[key] || key;
                    usages.push('Campaigns > ' + label + ' > ' + channel);
                } else if (id.startsWith('vt_')) {
                    var rest = id.substring(3);
                    var campKey = rest.split('_')[0];
                    var label = campaignLabels[campKey] || campKey;
                    var ntName = '';
                    for (var i = 0; i < noteTypes.length; i++) {
                        if (id.indexOf(noteTypes[i].id) !== -1) {
                            ntName = noteTypes[i].name;
                            break;
                        }
                    }
                    usages.push('Visit Type Overrides > ' + ntName + ' > ' + label + ' > ' + channel);
                }
            });
            return usages;
        }

        function confirmRemoveVariable(index) {
            var cv = customVariablesList[index];
            var usages = findVariableUsages(cv.key);
            if (usages.length > 0) {
                var msg = document.getElementById('cv_remove_message');
                msg.innerHTML = 'Cannot remove <strong>' + escapeHtml(cv.key) + '</strong>. Remove <code style="background:var(--color-bg);padding:1px 4px;border-radius:var(--radius);">{{' + escapeHtml(cv.key) + '}}</code> from these templates first:<ul style="margin:var(--space-tiny) 0 0;padding-left:20px;font-size:var(--font-size-label);">' +
                    usages.map(function(u) { return '<li>' + escapeHtml(u) + '</li>'; }).join('') +
                    '</ul>';
                document.getElementById('cv_remove_confirm_btn').style.display = 'none';
                openModal('cv_remove_modal');
                return;
            }
            var msg = document.getElementById('cv_remove_message');
            msg.innerHTML = 'Remove variable <strong>' + escapeHtml(cv.key) + '</strong> with value <strong>' + escapeHtml(cv.value) + '</strong>?';
            document.getElementById('cv_remove_confirm_btn').style.display = '';
            var btn = document.getElementById('cv_remove_confirm_btn');
            btn.onclick = function() {
                customVariablesList.splice(index, 1);
                renderCustomVariables();
                document.querySelectorAll('.var-dropdown').forEach(function(d) { d.innerHTML = ''; });
                closeCvRemoveModal();
                saveCustomVariables();
            };
            openModal('cv_remove_modal');
        }

        function closeCvRemoveModal() {
            closeModal('cv_remove_modal');
        }

        function gatherCustomVariables() {
            var result = {};
            customVariablesList.forEach(function(cv) { result[cv.key] = cv.value; });
            return result;
        }

        // --- History ---

        const PATIENT_APP_HASH = btoa('patient_notify.handlers.patient_app:NotifyPatientApp');

        async function loadHistory() {
            const response = await fetch('/plugin-io/api/patient_notify/admin/history');
            globalHistoryData = await response.json();
            renderHistoryTable();
        }

        function renderHistoryTable() {
            const tbody = document.getElementById('history_body');
            const emptyState = document.getElementById('history_empty');
            tbody.innerHTML = '';

            var filterFailed = document.getElementById('history_filter_failed').getAttribute('aria-checked') === 'true';
            var data = globalHistoryData;
            if (filterFailed) {
                data = data.filter(function(e) { return e.status === 'failed'; });
            }

            if (data.length === 0) {
                tbody.parentElement.style.display = 'none';
                emptyState.style.display = 'block';
                emptyState.textContent = filterFailed ? 'No failed notifications.' : 'No notifications sent yet.';
                return;
            }
            tbody.parentElement.style.display = '';
            emptyState.style.display = 'none';

            data.forEach(function(entry) {
                var originalIndex = globalHistoryData.indexOf(entry);

                const row = tbody.insertRow();
                row.insertCell(0).textContent = new Date(entry.timestamp).toLocaleString();

                const patientCell = row.insertCell(1);
                const firstName = entry.patient_first_name || '';
                const lastName = entry.patient_last_name || '';
                const fullName = (firstName + ' ' + lastName).trim();
                if (fullName) {
                    const link = document.createElement('a');
                    link.className = 'patient-link';
                    link.textContent = fullName;
                    link.href = '#';
                    link.title = 'View patient details';
                    link.onclick = function(e) { e.preventDefault(); openPatientModal(entry.patient_id, fullName); };
                    patientCell.appendChild(link);
                } else {
                    patientCell.textContent = entry.patient_id.substring(0, 8) + '...';
                    patientCell.title = entry.patient_id;
                }

                row.insertCell(2).textContent = entry.campaign_type;
                row.insertCell(3).textContent = entry.channel || '\\u2014';

                const statusCell = row.insertCell(4);
                const statusBadge = document.createElement('span');
                var statusColor = entry.status === 'delivered' ? 'badge-green' : entry.status === 'failed' ? 'badge-red' : 'badge-grey';
                statusBadge.className = 'badge ' + statusColor + ' badge-mini';
                statusBadge.textContent = entry.status;
                statusCell.appendChild(statusBadge);

                const detailsCell = row.insertCell(5);
                if (entry.error) {
                    const errorSpan = document.createElement('span');
                    errorSpan.className = 'error-text';
                    errorSpan.textContent = entry.error;
                    detailsCell.appendChild(errorSpan);
                } else {
                    detailsCell.textContent = '\\u2014';
                }

                const actionsCell = row.insertCell(6);
                if (entry.status === 'failed') {
                    var retryBtn = document.createElement('button');
                    retryBtn.className = 'btn btn-default btn-sm';
                    retryBtn.textContent = 'Retry';
                    retryBtn.onclick = function() { openRetryModal(entry, originalIndex); };
                    actionsCell.appendChild(retryBtn);
                }
            });
        }

        // --- Retry modal ---

        var pendingRetry = {patientId: null, logIndex: null};

        function openRetryModal(entry, logIndex) {
            pendingRetry.patientId = entry.patient_id;
            pendingRetry.logIndex = logIndex;

            var name = ((entry.patient_first_name || '') + ' ' + (entry.patient_last_name || '')).trim() || 'this patient';
            var msg = 'Retry the ' + entry.campaign_type + ' ' + (entry.channel || '') +
                ' notification for ' + name + '?';
            if (entry.error) msg += '\\n\\nOriginal error: ' + entry.error;

            document.getElementById('retry_message').textContent = msg;
            openModal('retry_modal');
            document.getElementById('retry_confirm_btn').onclick = executeRetry;
        }

        async function executeRetry() {
            var btn = document.getElementById('retry_confirm_btn');
            btn.disabled = true;
            btn.textContent = 'Retrying...';

            try {
                var response = await fetch(
                    '/plugin-io/api/patient_notify/patient/' + pendingRetry.patientId + '/retry',
                    {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({log_index: pendingRetry.logIndex}),
                    }
                );
                var data;
                try { data = await response.json(); } catch (_e) { data = {}; }

                if (response.ok && data.result && data.result.success) {
                                    } else {
                    var errMsg = (data.result && data.result.error) || data.error || response.statusText || 'Unknown error';
                    showBanner('Retry failed: ' + errMsg, 'error');
                }
            } catch (err) {
                showBanner('Retry failed: ' + err.message, 'error');
            }

            btn.disabled = false;
            btn.textContent = 'Retry';
            closeRetryModal();
            loadHistory();
        }

        function closeRetryModal() {
            closeModal('retry_modal');
        }

        // --- Patient modal ---

        async function openPatientModal(patientId, patientName) {
            const loading = document.getElementById('modal_loading');
            const content = document.getElementById('modal_content_inner');
            document.getElementById('modal_patient_name').textContent = patientName || 'Patient Details';
            loading.style.display = 'block';
            content.style.display = 'none';
            openModal('patient_modal');

            try {
                const response = await fetch('/plugin-io/api/patient_notify/admin/patient/' + patientId);
                const patient = await response.json();
                if (patient.error) { loading.textContent = 'Error: ' + patient.error; return; }

                const fullName = ((patient.first_name || '') + ' ' + (patient.last_name || '')).trim();
                var headerHtml = escapeHtml(fullName || 'Patient Details');
                var subtitleParts = [];
                if (patient.mrn) subtitleParts.push('MRN: ' + escapeHtml(patient.mrn));
                if (patient.preferred_name) subtitleParts.push('Goes by "' + escapeHtml(patient.preferred_name) + '"');
                document.getElementById('modal_patient_name').innerHTML = headerHtml +
                    (subtitleParts.length ? '<p class="modal-subtitle">' + subtitleParts.join(' &middot; ') + '</p>' : '');

                var warningsHtml = '';
                if (patient.deceased) warningsHtml += '<div class="patient-status-warn">This patient is marked as deceased. Messages should not be sent.</div>';
                else if (!patient.active) warningsHtml += '<div class="patient-status-warn">This patient is inactive.</div>';

                var apptHtml = '';
                if (patient.next_appointment) {
                    var apptDate = new Date(patient.next_appointment.start_time).toLocaleString();
                    apptHtml = '<div class="next-appt">Next appointment: ' + escapeHtml(apptDate) + '</div>';
                }

                function consentBadge(consent, optedOut) {
                    if (optedOut) return '<span class="badge badge-red badge-mini" style="margin-left:var(--space-tiny)">opted out</span>';
                    if (consent === true) return '<span class="badge badge-green badge-mini" style="margin-left:var(--space-tiny)">consented</span>';
                    if (consent === false) return '<span class="badge badge-orange badge-mini" style="margin-left:var(--space-tiny)">no consent</span>';
                    return '';
                }

                var dobDisplay = patient.date_of_birth || '\\u2014';
                if (patient.age !== null && patient.age !== undefined) dobDisplay += ' (age ' + patient.age + ')';

                document.getElementById('modal_patient_info').innerHTML = warningsHtml + apptHtml +
                    '<div class="info-item"><div class="info-label">Date of Birth</div><div>' + escapeHtml(dobDisplay) + '</div></div>' +
                    '<div class="info-item"><div class="info-label">Phone</div><div>' + escapeHtml(patient.phone || '\\u2014') + consentBadge(patient.sms_consent, patient.sms_opted_out) + '</div></div>' +
                    '<div class="info-item"><div class="info-label">Email</div><div>' + escapeHtml(patient.email || '\\u2014') + consentBadge(patient.email_consent, patient.email_opted_out) + '</div></div>' +
                    '<div class="info-item"><div class="info-label">Address</div><div>' + escapeHtml(patient.address || '\\u2014') + '</div></div>';

                document.getElementById('modal_actions').innerHTML =
                    '<a class="btn btn-default" href="/patient/' + patientId + '/edit" target="_blank">View Profile</a>' +
                    '<a class="btn btn-secondary" href="/patient/' + patientId + '/chart" target="_blank">View Chart</a>';

                var patientHistory = globalHistoryData.filter(function(e) { return e.patient_id === patientId; });
                var historyContainer = document.getElementById('modal_history');
                if (patientHistory.length === 0) {
                    historyContainer.innerHTML = '<div style="color:var(--color-text-muted);font-size:var(--font-size-label);">No notifications sent to this patient yet.</div>';
                } else {
                    var tableHtml = '<table class="table"><thead><tr><th>Date</th><th>Campaign</th><th>Channel</th><th>Status</th></tr></thead><tbody>';
                    patientHistory.forEach(function(e) {
                        var sc = e.status === 'delivered' ? 'badge-green' : e.status === 'failed' ? 'badge-red' : 'badge-grey';
                        tableHtml += '<tr><td>' + escapeHtml(new Date(e.timestamp).toLocaleString()) + '</td><td>' + escapeHtml(e.campaign_type) + '</td><td>' + escapeHtml(e.channel || '\\u2014') + '</td><td><span class="badge ' + sc + ' badge-mini">' + escapeHtml(e.status) + '</span></td></tr>';
                    });
                    tableHtml += '</tbody></table>';
                    historyContainer.innerHTML = tableHtml;
                }

                loading.style.display = 'none';
                content.style.display = 'block';
            } catch (err) {
                loading.textContent = 'Failed to load patient details.';
            }
        }

        function closePatientModal() {
            closeModal('patient_modal');
        }

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                document.querySelectorAll('.modal-backdrop.active').forEach(function(b) {
                    var id = b.id.replace('-backdrop', '');
                    closeModal(id);
                });
                pendingSwitchTab = null;
            }
        });

        loadConfig();

        var savedTab = localStorage.getItem('pn_admin_tab');
        if (savedTab && document.getElementById(savedTab)) {
            document.querySelectorAll('.tab-item').forEach(function(t) {
                t.classList.toggle('active', t.dataset.tab === savedTab);
            });
            document.querySelectorAll('.tab-panel').forEach(function(t) { t.classList.remove('active'); });
            document.getElementById(savedTab).classList.add('active');
            if (savedTab === 'history') loadHistory();
        }

        function updateSaveBarShadow() {
            document.querySelectorAll('.save-bar').forEach(function(bar) {
                var parent = bar.closest('.tab-panel');
                if (!parent || !parent.classList.contains('active')) return;
                var parentRect = parent.getBoundingClientRect();
                var stuck = parentRect.bottom > window.innerHeight + 1;
                bar.classList.toggle('stuck', stuck);
            });
        }
        window.addEventListener('scroll', updateSaveBarShadow, true);
        window.addEventListener('resize', updateSaveBarShadow);
        updateSaveBarShadow();

    </script>
</body>
</html>
        """
        return [HTMLResponse(html)]

    @api.get("/admin/note-types")
    def get_note_types(self) -> list[Response | Effect]:
        """Return schedulable note types for per-type reminder configuration."""
        from canvas_sdk.v1.data.note import NoteType

        note_types = NoteType.objects.filter(
            is_scheduleable=True, is_active=True
        ).order_by("name")
        return [
            JSONResponse(
                [
                    {"id": str(nt.id), "name": nt.name, "is_telehealth": nt.is_telehealth}
                    for nt in note_types
                ],
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/admin/integration-status")
    def get_integration_status(self) -> list[Response | Effect]:
        """Check whether Twilio and SendGrid secrets are configured."""
        twilio_keys = ("twilio-account-sid", "twilio-auth-token", "twilio-phone-number")
        sendgrid_keys = ("sendgrid-api-key", "sendgrid-from-email")
        twilio_configured = all(self.secrets.get(k) for k in twilio_keys)
        sendgrid_configured = all(self.secrets.get(k) for k in sendgrid_keys)
        return [
            JSONResponse(
                {
                    "twilio_configured": twilio_configured,
                    "sendgrid_configured": sendgrid_configured,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/admin/config")
    def get_config(self) -> list[Response | Effect]:
        """Get current campaign configuration."""
        config = load_config()
        return [JSONResponse(config.to_dict(), status_code=HTTPStatus.OK)]

    @api.post("/admin/config")
    def save_config_endpoint(self) -> list[Response | Effect]:
        """Save campaign configuration."""
        data = self.request.json()
        try:
            config = CampaignConfig.from_dict(data)
        except TypeError as e:
            return [JSONResponse({"error": f"Invalid configuration: {e}"}, status_code=HTTPStatus.BAD_REQUEST)]
        for key in config.custom_variables:
            if not _CUSTOM_VAR_KEY_RE.match(key):
                return [JSONResponse(
                    {"error": f"Invalid custom variable key: {key}. Only letters, numbers, and underscores allowed."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )]
        save_config(config)
        return [JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]

    @api.patch("/admin/config")
    def patch_config_endpoint(self) -> list[Response | Effect]:
        """Partially update campaign configuration."""
        data = self.request.json()
        for key in data.get("custom_variables", {}):
            if not _CUSTOM_VAR_KEY_RE.match(key):
                return [JSONResponse(
                    {"error": f"Invalid custom variable key: {key}. Only letters, numbers, and underscores allowed."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )]
        intervals = data.get("reminder_intervals")
        if intervals is not None:
            for val in intervals:
                if not isinstance(val, int) or val < 0:
                    return [JSONResponse(
                        {"error": "Reminder intervals must be non-negative integers."},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )]
        for nt_id, nt_data in data.get("note_type_campaigns", {}).items():
            nt_intervals = nt_data.get("reminder_intervals")
            if nt_intervals is not None:
                for val in nt_intervals:
                    if not isinstance(val, int) or val < 0:
                        return [JSONResponse(
                            {"error": "Reminder intervals for visit type must be non-negative."},
                            status_code=HTTPStatus.BAD_REQUEST,
                        )]
        send_time = data.get("day_out_send_time")
        if send_time is not None and not _SEND_TIME_RE.match(send_time):
            return [JSONResponse(
                {"error": "Send time must be in HH:MM format (00:00 to 23:59)."},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        try:
            patch_config(data)
        except (TypeError, ValueError) as e:
            return [
                JSONResponse(
                    {"error": f"Invalid configuration: {e}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        return [JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]

    @api.delete("/admin/config")
    def reset_config_endpoint(self) -> list[Response | Effect]:
        """Delete cached config so next load returns fresh defaults."""
        cache = get_cache()
        cache.delete("cr:config")
        return [JSONResponse({"status": "config reset"}, status_code=HTTPStatus.OK)]

    @api.get("/admin/history")
    def get_global_history(self) -> list[Response | Effect]:
        """Get global notification history enriched with patient names."""
        from canvas_sdk.v1.data.patient import Patient

        cache = get_cache()
        history_json = cache.get("cr:global_log", default="[]")
        history = json.loads(history_json)

        history.reverse()

        patient_ids = list({entry["patient_id"] for entry in history if entry.get("patient_id")})
        patient_map: dict[str, dict[str, str]] = {}
        if patient_ids:
            patients = Patient.objects.filter(id__in=patient_ids).only(
                "id", "first_name", "last_name"
            )
            for p in patients:
                patient_map[str(p.id)] = {
                    "first_name": p.first_name or "",
                    "last_name": p.last_name or "",
                }

        for entry in history:
            pid = entry.get("patient_id", "")
            info = patient_map.get(pid, {})
            entry["patient_first_name"] = info.get("first_name", "")
            entry["patient_last_name"] = info.get("last_name", "")

        return [JSONResponse(history, status_code=HTTPStatus.OK)]

    @api.get("/admin/patient/<patient_id>")
    def get_patient_detail(self) -> list[Response | Effect]:
        """Get patient detail for modal display."""
        from datetime import date

        from canvas_sdk.v1.data.appointment import Appointment
        from canvas_sdk.v1.data.patient import Patient

        patient_id = self.request.path_params["patient_id"]
        try:
            patient = Patient.objects.prefetch_related("telecom", "addresses").get(
                id=patient_id
            )
        except Patient.DoesNotExist:
            return [
                JSONResponse(
                    {"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND
                )
            ]

        phone = ""
        email = ""
        sms_consent = None
        email_consent = None
        sms_opted_out = False
        email_opted_out = False
        for t in patient.telecom.all():
            if t.system == "phone" and not phone:
                phone = t.value or ""
                sms_consent = t.has_consent
                sms_opted_out = bool(t.opted_out)
            elif t.system == "email" and not email:
                email = t.value or ""
                email_consent = t.has_consent
                email_opted_out = bool(t.opted_out)

        address = ""
        for a in patient.addresses.all():
            if a.state == "active":
                parts = [p for p in [a.city, a.state_code] if p]
                if parts:
                    address = ", ".join(parts)
                    if a.use == "home":
                        break

        age = None
        if patient.birth_date:
            today = date.today()
            age = (
                today.year
                - patient.birth_date.year
                - (
                    (today.month, today.day)
                    < (patient.birth_date.month, patient.birth_date.day)
                )
            )

        next_appointment = None
        try:
            from django.utils import timezone

            appt = (
                Appointment.objects.filter(
                    patient_id=patient_id,
                    start_time__gte=timezone.now(),
                )
                .order_by("start_time")
                .first()
            )
            if appt:
                next_appointment = {
                    "start_time": appt.start_time.isoformat(),
                    "status": appt.status or "",
                }
        except Exception:
            pass

        nickname = patient.nickname or ""
        preferred_name = ""
        if nickname and nickname.lower() != (patient.first_name or "").lower():
            preferred_name = nickname

        return [
            JSONResponse(
                {
                    "id": str(patient.id),
                    "first_name": patient.first_name or "",
                    "last_name": patient.last_name or "",
                    "preferred_name": preferred_name,
                    "mrn": patient.mrn or "",
                    "date_of_birth": str(patient.birth_date)
                    if patient.birth_date
                    else "",
                    "age": age,
                    "active": patient.active,
                    "deceased": patient.deceased,
                    "phone": phone,
                    "email": email,
                    "sms_consent": sms_consent,
                    "sms_opted_out": sms_opted_out,
                    "email_consent": email_consent,
                    "email_opted_out": email_opted_out,
                    "address": address,
                    "next_appointment": next_appointment,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/patient/<patient_id>/history")
    def get_patient_history(self) -> list[Response | Effect]:
        """Get patient-specific notification history."""
        patient_id = self.request.path_params["patient_id"]
        cache = get_cache()
        history_json = cache.get(f"cr:log:{patient_id}", default="[]")
        history = json.loads(history_json)

        history.reverse()

        return [JSONResponse(history, status_code=HTTPStatus.OK)]

    @api.get("/patient-view")
    def get_patient_view_page(self) -> list[Response | Effect]:
        """Serve patient notification history page."""
        html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Patient Notifications</title>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Lato:400,700,400italic,700italic&subset=latin">
    <style>
        :root {
            --color-text: rgba(0, 0, 0, 0.87);
            --color-text-active: rgba(0, 0, 0, 0.95);
            --color-text-muted: #767676;
            --color-primary: #22BA45;
            --color-secondary: #2185D0;
            --color-danger: #BD0B00;
            --color-warning: #ED4A0B;
            --color-accent-brown: #935330;
            --color-bg: #F5F5F5;
            --color-border: #E9E9E9;
            --color-surface: #FFFFFF;
            --color-error-bg: #fff6f6;
            --color-error-border: #e0b4b4;
            --color-error-text: #9f3a38;
            --font-family: lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            --font-size-base: 16px;
            --font-size-label: .92857143em;
            --font-size-input: 1em;
            --line-height-base: 1.4285em;
            --line-height-label: 1em;
            --font-weight-bold: 700;
            --space-mini: 4px;
            --space-tiny: 8px;
            --space-small: 12px;
            --space-medium: 16px;
            --space-large: 20px;
            --space-huge: 24px;
            --radius: .28571429rem;
            --border-width: 1px;
            --border-color: var(--color-border);
            --transition-fast: 200ms;
            --transition-base: 250ms;
            --input-padding: .67857143em 1em;
            --input-line-height: 1.21428571em;
            --input-border: 1px solid rgba(34, 36, 38, 0.15);
            --input-focus-border: #85b7d9;
            --input-placeholder: rgba(191, 191, 191, 0.87);
            --input-focus-placeholder: rgba(115, 115, 115, 0.87);
            --input-transition: 0.1s ease;
            --btn-padding: .67857143em 1.5em;
            --btn-padding-sm: .58928571em 1.125em;
            --btn-font-size: 1rem;
            --btn-font-size-sm: .92857143rem;
            --btn-padding-xs: .5em .85714286em;
            --btn-font-size-xs: .78571429rem;
            --row-positive-bg: #fcfff5;
            --row-positive-text: #2c662d;
            --row-warning-bg: #fffaf3;
            --row-warning-text: #573a08;
            --row-negative-bg: #fff6f6;
            --row-negative-text: #9f3a38;
            --row-active-bg: #e0e0e0;
            --table-header-bg: #f9fafb;
            --table-border: rgba(34, 36, 38, 0.1);
            --checkbox-size: 15px;
            --checkbox-border: 1px solid #d4d4d5;
            --checkbox-radius: .21428571rem;
            --checkbox-hover-border: rgba(34, 36, 38, 0.35);
            --checkbox-focus-border: #96c8da;
            --checkbox-check-color: var(--color-text-active);
            --checkbox-label-offset: 1.85714em;
            --tab-padding: .85714286em 1.14285714em;
            --tab-font-size: 1em;
            --tab-line-height: 1em;
            --tab-color: var(--color-text);
            --tab-active-color: var(--color-text-active);
            --tab-active-weight: 700;
            --tab-border: 2px solid rgba(34, 36, 38, 0.15);
            --tab-active-border: 2px solid rgb(27, 28, 29);
            --tab-margin-bottom: var(--space-medium);
            --tab-badge-font-size: .71428571em;
            --tab-badge-padding: .21428571em .5625em;
            --tab-badge-color: #767676;
            --tab-badge-border: 1px solid #767676;
            --tab-badge-radius: .28571429rem;
            --tab-badge-margin-left: .71428571em;
            --radio-size: 13px;
            --radio-border: 1px solid #d4d4d5;
            --radio-hover-border: rgba(34, 36, 38, 0.35);
            --radio-focus-border: #96c8da;
            --radio-dot-color: var(--color-text);
            --radio-dot-scale: scale(.53846154);
            --radio-label-offset: 1.85714em;
            --dropdown-padding: .67857143em 2.1em .67857143em 1em;
            --dropdown-border: 1px solid rgba(34, 36, 38, 0.15);
            --dropdown-focus-border: #96c8da;
            --dropdown-shadow: 0 2px 3px 0 rgba(34, 36, 38, 0.15);
            --dropdown-arrow-right: 1em;
            --dropdown-arrow-color: rgba(0, 0, 0, 0.8);
            --dropdown-menu-max-height: 16.02857143em;
            --dropdown-item-padding: .78571429em 1.14285714em;
            --dropdown-item-separator: 1px solid #fafafa;
            --dropdown-item-hover-bg: rgba(0, 0, 0, 0.05);
            --dropdown-item-selected-bg: rgba(0, 0, 0, 0.05);
            --dropdown-item-selected-color: var(--color-text-active);
            --tooltip-bg: var(--color-surface);
            --tooltip-color: var(--color-text);
            --tooltip-border: 1px solid #d4d4d5;
            --tooltip-padding: .833em 1em;
            --tooltip-shadow: 0 2px 4px 0 rgba(34, 36, 38, 0.12), 0 2px 10px 0 rgba(34, 36, 38, 0.15);
            --tooltip-arrow-size: .71428571em;
            --divider-border: 1px solid rgba(34, 36, 38, 0.15);
            --divider-margin: 1rem 0;
            --skeleton-bg: #e9e9e9;
            --skeleton-shine: #f5f5f5;
            --accordion-title-padding: 7px 0;
            --accordion-title-color: var(--color-text);
            --accordion-content-padding: 7px 0;
            --accordion-icon-size: 1.125em;
            --accordion-icon-transition: transform 0.1s ease;
            --accordion-styled-title-padding: .75em 1em;
            --accordion-styled-title-color: rgba(0, 0, 0, 0.4);
            --accordion-styled-title-active-color: var(--color-text);
            --accordion-styled-title-border: 1px solid rgba(34, 36, 38, 0.15);
            --accordion-styled-content-padding: .5em 1em 1.5em;
            --accordion-styled-shadow: 0 1px 2px 0 rgba(34, 36, 38, 0.15), 0 0 0 1px rgba(34, 36, 38, 0.15);
            --card-bg: var(--color-surface);
            --card-shadow: 0 1px 3px 0 #d4d4d5, 0 0 0 1px #d4d4d5;
            --card-hover-shadow: 0 1px 3px 0 #bcbdbd, 0 0 0 1px #d4d4d5;
            --card-padding: var(--space-medium);
            --spinner-size: 24px;
            --toggle-width: 3.5rem;
            --toggle-height: 1.5rem;
            --toggle-thumb-size: 1.5rem;
            --toggle-checked-offset: 2.15rem;
            --toggle-track-inactive: rgba(0, 0, 0, 0.05);
            --toggle-track-inactive-hover: rgba(0, 0, 0, 0.15);
            --toggle-track-active: var(--color-secondary);
            --toggle-thumb-shadow: 0 1px 2px 0 rgba(34, 36, 38, 0.15), 0 0 0 1px rgba(34, 36, 38, 0.15) inset;
        }
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        html { font-size: var(--font-size-base); line-height: var(--line-height-base); }
        body {
            font-family: var(--font-family);
            color: var(--color-text);
            background: var(--color-bg);
            margin: 0;
            padding: var(--space-medium);
            padding-bottom: 120px;
        }
        /* Accordion styled (card-like collapsible sections) */
        .accordion-styled {
            background: var(--color-surface);
            border-radius: var(--radius);
            box-shadow: var(--accordion-styled-shadow);
            margin-bottom: var(--space-small);
        }
        .accordion-styled + .accordion-styled .accordion-title {
            border-top: none;
        }
        .accordion-title {
            display: flex;
            align-items: center;
            gap: var(--space-tiny);
            padding: var(--accordion-styled-title-padding);
            font-size: 1em;
            font-weight: var(--font-weight-bold);
            color: var(--accordion-styled-title-active-color);
            background: transparent;
            border: none;
            width: 100%;
            text-align: left;
            cursor: pointer;
            font-family: var(--font-family);
            min-height: 44px;
            transition: color 0.1s ease;
        }
        .accordion-title:hover { color: rgba(0, 0, 0, 0.95); }
        .accordion-title:focus-visible { outline: 2px solid var(--color-secondary); outline-offset: -2px; }
        .accordion-icon {
            display: inline-block;
            width: 0;
            height: 0;
            border-top: 6px solid transparent;
            border-bottom: 6px solid transparent;
            border-left: 7px solid currentColor;
            flex-shrink: 0;
            transition: var(--accordion-icon-transition);
        }
        .accordion-item.open .accordion-icon {
            transform: rotate(90deg);
        }
        .accordion-content {
            display: none;
            padding: var(--accordion-styled-content-padding);
        }
        .accordion-content > :last-child {
            margin-bottom: 0;
        }
        .accordion-item.open .accordion-content {
            display: block;
        }
        .accordion-item + .accordion-item .accordion-title {
            border-top: var(--accordion-styled-title-border);
        }
        /* Table */
        .table {
            width: 100%;
            border-collapse: collapse;
            font-size: 1em;
            color: var(--color-text);
        }
        .table th {
            padding: 0.5rem 1rem;
            vertical-align: middle;
            text-align: left;
            font-weight: var(--font-weight-bold);
            background: var(--color-surface);
            border-bottom: 2px solid var(--color-border);
        }
        .table td {
            padding: 0.5rem 1rem;
            vertical-align: middle;
            text-align: left;
        }
        .table tr { border-bottom: 1px solid var(--color-border); }
        .table thead tr { border-bottom: none; }
        .table-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
        .table tbody tr:hover { background: rgba(0, 0, 50, 0.025); }
        /* Badge */
        .badge {
            display: inline-block;
            line-height: 1;
            vertical-align: baseline;
            margin: 0 .14285714em;
            background-color: #e8e8e8;
            padding: .5833em .833em;
            color: rgba(0, 0, 0, 0.6);
            font-weight: var(--font-weight-bold);
            border: 0 solid transparent;
            border-radius: var(--radius);
            font-size: .85714286rem;
            white-space: nowrap;
        }
        .badge-mini { font-size: .64285714rem; }
        .badge-green { background: #21ba45; color: #fff; }
        .badge-red { background: #db2828; color: #fff; }
        /* Empty state */
        .empty-state {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: var(--space-huge);
            color: var(--color-text-muted);
            font-size: var(--font-size-input);
            text-align: center;
        }
        /* Banner */
        .banner-warning { background-color: #fffaf3; color: #573a08; box-shadow: 0 0 0 1px #c9ba9b inset; }
        /* Form */
        .form-row {
            display: flex;
            gap: var(--space-small);
            margin-bottom: var(--space-small);
            align-items: flex-end;
        }
        .form-row:last-child {
            margin-bottom: 0;
        }
        .form-group {
            flex: 1;
        }
        .form-group .label {
            display: block;
            margin: 0 0 .28571429rem 0;
            font-size: var(--font-size-label);
            font-weight: var(--font-weight-bold);
            color: rgba(0, 0, 0, 0.87);
            text-transform: none;
        }
        .form-group select {
            width: 100%;
            padding: var(--input-padding);
            font-size: 1em;
            font-family: var(--font-family);
            line-height: var(--input-line-height);
            color: rgba(0, 0, 0, 0.87);
            background: var(--color-surface);
            border: var(--input-border);
            border-radius: var(--radius);
            transition: border-color var(--input-transition);
            outline: 0;
        }
        .form-group select:focus {
            border-color: var(--input-focus-border);
        }
        /* Radio */
        .channel-options {
            display: flex;
            gap: var(--space-medium);
            padding-top: var(--space-mini);
        }
        .radio-wrap {
            position: relative;
            display: flex;
            align-items: center;
            min-height: 44px;
            cursor: pointer;
            font-size: 1rem;
            line-height: 1;
        }
        .radio-wrap input[type="radio"] {
            position: absolute;
            top: 50%;
            left: 0;
            transform: translateY(-50%);
            opacity: 0;
            width: var(--radio-size);
            height: var(--radio-size);
            cursor: pointer;
            z-index: 3;
        }
        .radio-wrap .radio-dot {
            position: relative;
            flex-shrink: 0;
            box-sizing: content-box;
            width: var(--radio-size);
            height: var(--radio-size);
            background: var(--color-surface);
            border: var(--radio-border);
            border-radius: 500rem;
            transition: border 0.1s ease;
        }
        .radio-wrap .radio-dot::after {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            width: var(--radio-size);
            height: var(--radio-size);
            border-radius: 500rem;
            background-color: var(--radio-dot-color);
            transform: var(--radio-dot-scale);
            opacity: 0;
            transition: opacity 0.1s ease;
        }
        .radio-wrap input:checked + .radio-dot { border-color: var(--radio-hover-border); }
        .radio-wrap input:checked + .radio-dot::after { opacity: 1; }
        .radio-wrap input:hover + .radio-dot { border-color: var(--radio-hover-border); }
        .radio-wrap input:focus-visible + .radio-dot { border-color: var(--radio-focus-border); }
        .radio-wrap span:last-child {
            padding-left: var(--space-tiny);
            color: var(--color-text);
        }
        /* Preview */
        .preview-card {
            background: var(--color-surface);
            border: var(--border-width) solid var(--color-border);
            border-radius: var(--radius);
        }
        .preview-area {
            padding: var(--space-small);
            font-size: var(--font-size-label);
            white-space: pre-wrap;
            min-height: 60px;
            color: var(--color-text);
        }
        .preview-area p {
            margin: var(--space-tiny) 0 0 0;
        }
        .preview-area > *:first-child {
            margin-top: 0;
        }
        /* Buttons */
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: var(--btn-padding);
            font-size: var(--btn-font-size);
            font-weight: var(--font-weight-bold);
            font-family: var(--font-family);
            line-height: var(--input-line-height);
            border: none;
            border-radius: var(--radius);
            cursor: pointer;
            transition: opacity var(--transition-fast);
            min-height: 1em;
        }
        .btn:focus-visible { outline: 2px solid var(--color-secondary); outline-offset: 2px; }
        .btn-primary { background: var(--color-primary); color: #fff; }
        .btn-primary:hover { opacity: 0.9; }
        .btn-disabled {
            background: var(--color-border);
            color: var(--color-text-muted);
            cursor: not-allowed;
            pointer-events: none;
        }
        .send-actions {
            display: flex;
            gap: var(--space-tiny);
            margin-top: var(--space-small);
        }
        /* Banner */
        .banner {
            position: relative;
            min-height: 1em;
            margin: 1em 0;
            background: #f8f8f9;
            padding: 1em 1.5em;
            line-height: 1.4285em;
            color: rgba(0, 0, 0, 0.87);
            border-radius: var(--radius);
            font-size: 1em;
            transition: opacity 0.1s ease;
        }
        .banner-error { background-color: #fff6f6; color: #9f3a38; box-shadow: 0 0 0 1px #e0b4b4 inset; }
        .banner-dismissible { padding-right: 2.5em; }
        .banner-dismiss {
            position: absolute;
            top: 1em;
            right: 1em;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: none;
            border: none;
            cursor: pointer;
            padding: 0;
            min-height: 0;
            opacity: 0.5;
            color: inherit;
        }
        .banner-dismiss:hover { opacity: 1; }
        /* Dropdown (matches Canvas Semantic UI selection dropdown) */
        .dropdown {
            position: relative;
            display: flex;
            align-items: center;
            width: 100%;
            padding: var(--dropdown-padding);
            font-size: 1em;
            font-family: var(--font-family);
            line-height: var(--input-line-height);
            color: var(--color-text);
            background: var(--color-surface);
            border: var(--dropdown-border);
            border-radius: var(--radius);
            cursor: pointer;
            outline: none;
            transition: border-color 0.1s ease, box-shadow 0.1s ease, border-radius 0.1s ease;
        }
        .dropdown:focus {
            border-color: var(--dropdown-focus-border);
        }
        .dropdown.open {
            border-color: var(--dropdown-focus-border);
            border-radius: var(--radius) var(--radius) 0 0;
            box-shadow: var(--dropdown-shadow);
            z-index: 10;
        }
        .dropdown-text {
            flex: 1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: var(--color-text);
        }
        .dropdown-text.placeholder { color: var(--input-placeholder); }
        .dropdown-arrow {
            position: absolute;
            top: 50%;
            right: var(--dropdown-arrow-right);
            transform: translateY(-50%);
            width: 0;
            height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid var(--dropdown-arrow-color);
            pointer-events: none;
        }
        .dropdown-menu {
            display: none;
            position: absolute;
            top: 100%;
            left: -1px;
            right: -1px;
            max-height: var(--dropdown-menu-max-height);
            overflow-y: auto;
            background: var(--color-surface);
            border: var(--dropdown-border);
            border-top: none;
            border-radius: 0 0 var(--radius) var(--radius);
            box-shadow: var(--dropdown-shadow);
            z-index: 11;
            list-style: none;
            margin: 0;
            padding: 0;
        }
        .dropdown.open .dropdown-menu {
            display: block;
            border-color: var(--dropdown-focus-border);
        }
        .dropdown-option {
            padding: var(--dropdown-item-padding);
            font-size: 1em;
            color: var(--color-text);
            cursor: pointer;
            border-top: var(--dropdown-item-separator);
            transition: background 0.1s ease;
        }
        .dropdown-option:first-child { border-top: none; }
        .dropdown-option:hover, .dropdown-option.highlighted {
            background: var(--dropdown-item-hover-bg);
            color: var(--color-text-active);
        }
        .dropdown-option.selected {
            background: var(--dropdown-item-selected-bg);
            color: var(--dropdown-item-selected-color);
            font-weight: var(--font-weight-bold);
        }
        .dropdown-option[aria-disabled="true"] { color: var(--color-text-muted); cursor: not-allowed; }
        /* Combobox (searchable dropdown, shares visual treatment with dropdown) */
        .combobox {
            position: relative;
            width: 100%;
        }
        .combobox-input {
            width: 100%;
            padding: var(--dropdown-padding);
            font-size: 1em;
            font-family: var(--font-family);
            line-height: var(--input-line-height);
            color: var(--color-text);
            background: var(--color-surface);
            border: var(--dropdown-border);
            border-radius: var(--radius);
            transition: border-color 0.1s ease, box-shadow 0.1s ease, border-radius 0.1s ease;
            cursor: pointer;
            outline: none;
        }
        .combobox-input:focus {
            border-color: var(--dropdown-focus-border);
        }
        .combobox.open .combobox-input {
            border-color: var(--dropdown-focus-border);
            border-bottom-color: transparent;
            border-radius: var(--radius) var(--radius) 0 0;
            box-shadow: var(--dropdown-shadow);
        }
        .combobox-input::placeholder { color: var(--input-placeholder); }
        .combobox-arrow {
            position: absolute;
            top: 50%;
            right: var(--dropdown-arrow-right);
            transform: translateY(-50%);
            width: 0;
            height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid var(--dropdown-arrow-color);
            pointer-events: none;
        }
        .combobox-listbox {
            display: none;
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            max-height: var(--dropdown-menu-max-height);
            overflow-y: auto;
            background: var(--color-surface);
            border: var(--dropdown-border);
            border-top: none;
            border-radius: 0 0 var(--radius) var(--radius);
            box-shadow: var(--dropdown-shadow);
            z-index: 11;
            list-style: none;
            margin: 0;
            padding: 0;
        }
        .combobox.open .combobox-listbox {
            display: block;
            border-color: var(--dropdown-focus-border);
        }
        .combobox.flip .combobox-listbox {
            top: auto;
            bottom: 100%;
            border-top: var(--dropdown-border);
            border-bottom: none;
            border-radius: var(--radius) var(--radius) 0 0;
        }
        .combobox.flip .combobox-input {
            border-radius: 0 0 var(--radius) var(--radius);
        }
        .combobox-option {
            padding: var(--dropdown-item-padding);
            font-size: 1em;
            color: var(--color-text);
            cursor: pointer;
            border-top: var(--dropdown-item-separator);
            transition: background 0.1s ease;
        }
        .combobox-option:first-child { border-top: none; }
        .combobox-option:hover, .combobox-option.highlighted {
            background: var(--dropdown-item-hover-bg);
            color: var(--color-text-active);
        }
        .combobox-option.selected {
            background: var(--dropdown-item-selected-bg);
            color: var(--dropdown-item-selected-color);
            font-weight: var(--font-weight-bold);
        }
        .combobox-option[aria-disabled="true"] { color: var(--color-text-muted); cursor: not-allowed; }
        .combobox-option.hidden { display: none; }
        .combobox-empty {
            padding: var(--dropdown-item-padding);
            color: var(--color-text-muted);
            font-size: 1em;
        }
        /* Link */
        a { color: var(--color-secondary); text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div id="banner_area"></div>
    <div id="delivery_alert" class="banner banner-warning" style="display:none"></div>

    <div class="accordion accordion-styled">
        <div class="accordion-item open" id="send_section">
            <button class="accordion-title" aria-expanded="true" aria-controls="send_body" onclick="toggleSection('send')">
                <span class="accordion-icon" id="send_icon"></span>
                Send Notification
            </button>
            <div class="accordion-content" id="send_body">
                <div class="form-row">
                    <div class="form-group">
                        <label class="label" id="appointment-label">Appointment</label>
                        <div class="combobox" id="send_appointment">
                            <input class="combobox-input" type="text" role="combobox"
                                aria-autocomplete="list" aria-expanded="false"
                                aria-controls="appointment-listbox" aria-labelledby="appointment-label"
                                placeholder="Loading...">
                            <span class="combobox-arrow"></span>
                            <ul class="combobox-listbox" id="appointment-listbox" role="listbox" aria-labelledby="appointment-label">
                            </ul>
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="label" id="campaign-label">Campaign</label>
                        <div class="dropdown" id="send_campaign" role="listbox" tabindex="0"
                            aria-labelledby="campaign-label" aria-expanded="false">
                            <span class="dropdown-text">Confirmation</span>
                            <span class="dropdown-arrow"></span>
                            <ul class="dropdown-menu">
                                <li class="dropdown-option selected" role="option" aria-selected="true" data-value="confirmation">Confirmation</li>
                                <li class="dropdown-option" role="option" aria-selected="false" data-value="reminders">Reminder</li>
                                <li class="dropdown-option" role="option" aria-selected="false" data-value="noshow">No-show</li>
                                <li class="dropdown-option" role="option" aria-selected="false" data-value="cancellation">Cancellation</li>
                            </ul>
                        </div>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="label">Channel</label>
                        <div class="channel-options">
                            <label class="radio-wrap">
                                <input type="radio" name="send_channel" value="sms" checked onchange="onFormChange()">
                                <span class="radio-dot"></span>
                                <span>SMS</span>
                            </label>
                            <label class="radio-wrap">
                                <input type="radio" name="send_channel" value="email" onchange="onFormChange()">
                                <span class="radio-dot"></span>
                                <span>Email</span>
                            </label>
                        </div>
                    </div>
                </div>
                <div class="form-group" style="margin-top: var(--space-small)">
                    <label class="label">Message preview</label>
                    <div class="preview-card">
                        <div id="preview_content" class="preview-area">Select an appointment to preview.</div>
                    </div>
                </div>
                <div class="send-actions">
                    <button id="send_btn" class="btn btn-disabled" onclick="sendNotification()" disabled>Send</button>
                </div>
            </div>
        </div>
    </div>

    <div class="accordion accordion-styled">
        <div class="accordion-item open" id="history_section">
            <button class="accordion-title" aria-expanded="true" aria-controls="history_body" onclick="toggleSection('history')">
                <span class="accordion-icon" id="history_icon"></span>
                Notification History
            </button>
            <div class="accordion-content" id="history_body">
                <div id="content">
                    <div class="empty-state">Loading...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        var currentPatientId = new URLSearchParams(window.location.search).get('patient_id');

        var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

        function formatDate(iso) {
            var d = new Date(iso);
            var h = d.getHours();
            var ampm = h >= 12 ? 'PM' : 'AM';
            h = h % 12 || 12;
            var min = d.getMinutes().toString().padStart(2, '0');
            return MONTHS[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear() + ' ' + h + ':' + min + ' ' + ampm;
        }

        function formatDateShort(iso) {
            var d = new Date(iso);
            var h = d.getHours();
            var ampm = h >= 12 ? 'PM' : 'AM';
            h = h % 12 || 12;
            var min = d.getMinutes().toString().padStart(2, '0');
            return MONTHS[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear() + ' ' + h + ':' + min + ' ' + ampm;
        }

        function toggleSection(name) {
            var item = document.getElementById(name + '_section');
            var title = item.querySelector('.accordion-title');
            var isOpen = item.classList.contains('open');
            item.classList.toggle('open');
            title.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
        }

        var dismissSvg = '<svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

        function escapeHtml(str) {
            var div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }

        function showBanner(msg, type) {
            var area = document.getElementById('banner_area');
            area.innerHTML = '';
            var cls = type === 'error' ? 'banner-error' : 'banner-warning';
            var div = document.createElement('div');
            div.className = 'banner ' + cls + ' banner-dismissible';
            div.innerHTML = '<button class="banner-dismiss" aria-label="Dismiss">' + dismissSvg + '</button>' + escapeHtml(msg);
            area.appendChild(div);
            area.scrollIntoView({behavior: 'smooth', block: 'nearest'});
        }

        document.addEventListener('click', function(e) {
            var dismiss = e.target.closest('.banner-dismiss');
            if (dismiss) {
                var banner = dismiss.closest('.banner');
                banner.style.opacity = '0';
                setTimeout(function() { banner.remove(); }, 100);
            }
        });

        async function loadHistory() {
            try {
                const urlParams = new URLSearchParams(window.location.search);
                const patientId = urlParams.get('patient_id');

                if (!patientId) {
                    document.getElementById('content').innerHTML = '<div class="empty-state">No patient ID provided</div>';
                    return;
                }

                const response = await fetch('/plugin-io/api/patient_notify/patient/' + patientId + '/history', {cache: 'no-store'});

                if (!response.ok) {
                    document.getElementById('content').innerHTML = '<div class="empty-state">Error: ' + response.status + ' ' + response.statusText + '</div>';
                    return;
                }

                const history = await response.json();

                if (history.length === 0) {
                    document.getElementById('content').innerHTML = '<div class="empty-state">No notifications sent to this patient yet</div>';
                    return;
                }

                var blockedCodes = [21610, 21612, 21614, 30006, 30007];
                var alertBanner = document.getElementById('delivery_alert');
                for (var i = 0; i < history.length; i++) {
                    var e = history[i];
                    if (e.channel === 'sms' && e.error_code && blockedCodes.indexOf(e.error_code) !== -1) {
                        alertBanner.textContent = 'SMS delivery blocked: ' + (e.error || 'Patient may have opted out or has an unreachable number');
                        alertBanner.style.display = 'block';
                        break;
                    }
                }

                const table = document.createElement('table');
                table.className = 'table';
                const thead = table.createTHead();
                const headerRow = thead.insertRow();
                ['Date', 'Campaign', 'Status'].forEach(text => {
                    const th = document.createElement('th');
                    th.textContent = text;
                    headerRow.appendChild(th);
                });

                const tbody = table.createTBody();
                history.forEach(entry => {
                    const row = tbody.insertRow();
                    row.insertCell(0).textContent = formatDate(entry.timestamp);
                    row.insertCell(1).textContent = entry.campaign_type;
                    const statusCell = row.insertCell(2);
                    const statusBadge = document.createElement('span');
                    var sc = entry.status === 'delivered' ? 'badge-green' : entry.status === 'failed' ? 'badge-red' : 'badge-grey';
                    statusBadge.className = 'badge ' + sc + ' badge-mini';
                    statusBadge.textContent = entry.status;
                    statusCell.appendChild(statusBadge);
                });

                const wrapper = document.createElement('div');
                wrapper.className = 'table-scroll';
                wrapper.appendChild(table);
                const content = document.getElementById('content');
                content.innerHTML = '';
                content.appendChild(wrapper);
            } catch (err) {
                const errorDiv = document.createElement('div');
                errorDiv.className = 'empty-state';
                errorDiv.textContent = 'Error: ' + err.message;
                const contentEl = document.getElementById('content');
                contentEl.innerHTML = '';
                contentEl.appendChild(errorDiv);
            }
        }

        /* Dropdown init */
        function initDropdown(id) {
            var root = document.getElementById(id);
            var textEl = root.querySelector('.dropdown-text');
            var menu = root.querySelector('.dropdown-menu');
            var options = Array.from(menu.querySelectorAll('.dropdown-option:not([aria-disabled="true"])'));
            var highlighted = -1;

            function open() {
                root.classList.add('open');
                root.setAttribute('aria-expanded', 'true');
                highlighted = -1;
                clearHighlight();
            }
            function close() {
                root.classList.remove('open');
                root.setAttribute('aria-expanded', 'false');
                highlighted = -1;
                clearHighlight();
            }
            function isOpen() { return root.classList.contains('open'); }
            function clearHighlight() {
                options.forEach(function(o) { o.classList.remove('highlighted'); });
            }
            function highlight(index) {
                clearHighlight();
                if (index < 0) index = options.length - 1;
                if (index >= options.length) index = 0;
                highlighted = index;
                options[highlighted].classList.add('highlighted');
                options[highlighted].scrollIntoView({ block: 'nearest' });
            }
            function selectOption(opt) {
                options.forEach(function(o) {
                    o.classList.remove('selected');
                    o.setAttribute('aria-selected', 'false');
                });
                opt.classList.add('selected');
                opt.setAttribute('aria-selected', 'true');
                var text = opt.textContent;
                textEl.textContent = text;
                textEl.title = text;
                textEl.classList.remove('placeholder');
                root.dataset.value = opt.dataset.value;
                close();
                root.focus();
                root.dispatchEvent(new Event('change', { bubbles: true }));
            }

            root.addEventListener('click', function(e) {
                if (e.target.closest('.dropdown-option')) return;
                isOpen() ? close() : open();
            });
            menu.addEventListener('click', function(e) {
                var opt = e.target.closest('.dropdown-option');
                if (opt && opt.getAttribute('aria-disabled') !== 'true') selectOption(opt);
            });
            root.addEventListener('keydown', function(e) {
                switch (e.key) {
                    case 'Enter': case ' ':
                        e.preventDefault();
                        if (!isOpen()) open();
                        else if (highlighted >= 0) selectOption(options[highlighted]);
                        break;
                    case 'Escape': e.preventDefault(); close(); break;
                    case 'ArrowDown':
                        e.preventDefault();
                        if (!isOpen()) open();
                        highlight(highlighted + 1);
                        break;
                    case 'ArrowUp':
                        e.preventDefault();
                        if (!isOpen()) open();
                        highlight(highlighted - 1);
                        break;
                    case 'Home': if (isOpen()) { e.preventDefault(); highlight(0); } break;
                    case 'End': if (isOpen()) { e.preventDefault(); highlight(options.length - 1); } break;
                    case 'Tab':
                        if (isOpen()) { if (highlighted >= 0) selectOption(options[highlighted]); close(); }
                        break;
                    default:
                        if (e.key.length === 1) {
                            if (!isOpen()) open();
                            var match = options.findIndex(function(o, i) {
                                return i > highlighted && o.textContent.toLowerCase().startsWith(e.key.toLowerCase());
                            });
                            if (match === -1) match = options.findIndex(function(o) {
                                return o.textContent.toLowerCase().startsWith(e.key.toLowerCase());
                            });
                            if (match >= 0) highlight(match);
                        }
                }
            });
            document.addEventListener('click', function(e) { if (!root.contains(e.target)) close(); });

            /* expose reinit for dynamic options */
            root._refreshOptions = function() {
                options = Array.from(menu.querySelectorAll('.dropdown-option:not([aria-disabled="true"])'));
                highlighted = -1;
            };
            root._selectByValue = function(val) {
                var match = options.find(function(o) { return o.dataset.value === val; });
                if (match) selectOption(match);
            };
        }

        /* Combobox init */
        function initCombobox(id) {
            var root = document.getElementById(id);
            var input = root.querySelector('.combobox-input');
            var listbox = root.querySelector('.combobox-listbox');
            var allOptions = Array.from(listbox.querySelectorAll('.combobox-option:not([aria-disabled="true"])'));
            var highlighted = -1;
            var selectedValue = null;

            function getVisible() {
                return allOptions.filter(function(o) { return !o.classList.contains('hidden'); });
            }
            function open() {
                root.classList.add('open');
                input.setAttribute('aria-expanded', 'true');
                highlighted = -1;
                clearHighlight();
                flipIfNeeded();
            }
            function close() {
                root.classList.remove('open');
                root.classList.remove('flip');
                input.setAttribute('aria-expanded', 'false');
                highlighted = -1;
                clearHighlight();
            }
            function isOpen() { return root.classList.contains('open'); }
            function flipIfNeeded() {
                root.classList.remove('flip');
                var rect = listbox.getBoundingClientRect();
                if (rect.bottom > window.innerHeight) root.classList.add('flip');
            }
            function clearHighlight() {
                allOptions.forEach(function(o) { o.classList.remove('highlighted'); });
                input.removeAttribute('aria-activedescendant');
            }
            function highlight(index) {
                var visible = getVisible();
                clearHighlight();
                if (visible.length === 0) return;
                if (index < 0) index = visible.length - 1;
                if (index >= visible.length) index = 0;
                highlighted = index;
                var opt = visible[highlighted];
                opt.classList.add('highlighted');
                opt.id = id + '-option-' + highlighted;
                input.setAttribute('aria-activedescendant', opt.id);
                opt.scrollIntoView({ block: 'nearest' });
            }
            function selectOption(opt) {
                allOptions.forEach(function(o) { o.classList.remove('selected'); });
                opt.classList.add('selected');
                input.value = opt.textContent;
                selectedValue = opt.dataset.value;
                input.dataset.value = selectedValue;
                if (opt.dataset.isTelehealth) input.dataset.isTelehealth = opt.dataset.isTelehealth;
                close();
                showAll();
                input.focus();
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }
            function showAll() {
                allOptions.forEach(function(o) { o.classList.remove('hidden'); });
                var empty = listbox.querySelector('.combobox-empty');
                if (empty) empty.remove();
            }
            function filter(query) {
                var q = query.toLowerCase();
                var anyVisible = false;
                allOptions.forEach(function(o) {
                    if (o.textContent.toLowerCase().indexOf(q) >= 0) {
                        o.classList.remove('hidden');
                        anyVisible = true;
                    } else {
                        o.classList.add('hidden');
                    }
                });
                var empty = listbox.querySelector('.combobox-empty');
                if (!anyVisible) {
                    if (!empty) {
                        empty = document.createElement('li');
                        empty.className = 'combobox-empty';
                        empty.textContent = 'No results';
                        listbox.appendChild(empty);
                    }
                } else if (empty) {
                    empty.remove();
                }
                highlighted = -1;
                clearHighlight();
            }

            input.addEventListener('click', function() {
                if (!isOpen()) { showAll(); open(); }
            });
            input.addEventListener('input', function() {
                if (!isOpen()) open();
                filter(input.value);
            });
            input.addEventListener('keydown', function(e) {
                var visible = getVisible();
                switch (e.key) {
                    case 'Enter':
                        e.preventDefault();
                        if (!isOpen()) { showAll(); open(); }
                        else if (highlighted >= 0 && visible[highlighted]) selectOption(visible[highlighted]);
                        break;
                    case 'Escape':
                        e.preventDefault();
                        if (selectedValue) {
                            var sel = allOptions.find(function(o) { return o.dataset.value === selectedValue; });
                            if (sel) input.value = sel.textContent;
                        } else { input.value = ''; }
                        close();
                        showAll();
                        break;
                    case 'ArrowDown':
                        e.preventDefault();
                        if (!isOpen()) { showAll(); open(); }
                        highlight(highlighted + 1);
                        break;
                    case 'ArrowUp':
                        e.preventDefault();
                        if (!isOpen()) { showAll(); open(); }
                        highlight(highlighted - 1);
                        break;
                    case 'Home':
                        if (isOpen()) { e.preventDefault(); highlight(0); }
                        break;
                    case 'End':
                        if (isOpen()) { e.preventDefault(); highlight(visible.length - 1); }
                        break;
                    case 'Tab':
                        if (isOpen()) {
                            if (highlighted >= 0 && visible[highlighted]) selectOption(visible[highlighted]);
                            close();
                            showAll();
                        }
                        break;
                }
            });
            listbox.addEventListener('click', function(e) {
                var opt = e.target.closest('.combobox-option');
                if (opt && !opt.classList.contains('hidden')) selectOption(opt);
            });
            document.addEventListener('click', function(e) {
                if (!root.contains(e.target)) {
                    if (isOpen()) {
                        if (selectedValue) {
                            var sel = allOptions.find(function(o) { return o.dataset.value === selectedValue; });
                            if (sel) input.value = sel.textContent;
                        } else { input.value = ''; }
                        close();
                        showAll();
                    }
                }
            });

            root._refresh = function() {
                allOptions = Array.from(listbox.querySelectorAll('.combobox-option:not([aria-disabled="true"])'));
            };
            root._selectByValue = function(val) {
                var match = allOptions.find(function(o) { return o.dataset.value === val; });
                if (match) selectOption(match);
            };
        }

        /* Value helpers */
        function getApptValue() {
            var inp = document.querySelector('#send_appointment .combobox-input');
            return (inp && inp.dataset.value) || '';
        }
        function getApptTelehealth() {
            var inp = document.querySelector('#send_appointment .combobox-input');
            return inp && inp.dataset.isTelehealth === '1';
        }
        function getCampaignValue() {
            return document.getElementById('send_campaign').dataset.value || 'confirmation';
        }

        var appointmentsList = [];

        async function loadAppointments() {
            if (!currentPatientId) return;
            try {
                var resp = await fetch('/plugin-io/api/patient_notify/patient/' + currentPatientId + '/appointments');
                appointmentsList = await resp.json();
                var listbox = document.getElementById('appointment-listbox');
                listbox.innerHTML = '';
                if (appointmentsList.length === 0) {
                    var inp = document.querySelector('#send_appointment .combobox-input');
                    inp.placeholder = 'No appointments found';
                    inp.dataset.value = '';
                    return;
                }
                appointmentsList.forEach(function(appt) {
                    var li = document.createElement('li');
                    li.className = 'combobox-option';
                    li.setAttribute('role', 'option');
                    li.dataset.value = appt.id;
                    li.dataset.isTelehealth = appt.is_telehealth ? '1' : '0';
                    var label = formatDateShort(appt.start_time);
                    if (appt.note_type_name) label += ' \\u2014 ' + appt.note_type_name;
                    if (appt.provider_name) label += ' (' + appt.provider_name + ')';
                    li.textContent = label;
                    listbox.appendChild(li);
                });
                initCombobox('send_appointment');
                document.getElementById('send_appointment')._selectByValue(appointmentsList[0].id);
                onAppointmentChange();
            } catch (err) {
                var inp = document.querySelector('#send_appointment .combobox-input');
                inp.placeholder = 'Error loading appointments';
                inp.dataset.value = '';
            }
        }

        function onAppointmentChange() {
            var hasTelehealth = getApptTelehealth();
            var campaignEl = document.getElementById('send_campaign');
            var menu = campaignEl.querySelector('.dropdown-menu');
            var existingTh = menu.querySelector('[data-value="telehealth"]');
            if (hasTelehealth && !existingTh) {
                var li = document.createElement('li');
                li.className = 'dropdown-option';
                li.setAttribute('role', 'option');
                li.setAttribute('aria-selected', 'false');
                li.dataset.value = 'telehealth';
                li.textContent = 'Telehealth Join';
                menu.appendChild(li);
                campaignEl._refreshOptions();
            } else if (!hasTelehealth && existingTh) {
                var wasSelected = getCampaignValue() === 'telehealth';
                existingTh.remove();
                campaignEl._refreshOptions();
                if (wasSelected) campaignEl._selectByValue('confirmation');
            }
            onFormChange();
        }

        function onFormChange() {
            var apptId = getApptValue();
            var btn = document.getElementById('send_btn');
            if (apptId) {
                btn.disabled = false;
                btn.className = 'btn btn-primary';
            } else {
                btn.disabled = true;
                btn.className = 'btn btn-disabled';
            }
            fetchPreview();
        }

        async function fetchPreview() {
            var apptId = getApptValue();
            var campaign = getCampaignValue();
            if (!apptId || !currentPatientId) return;

            try {
                var resp = await fetch(
                    '/plugin-io/api/patient_notify/patient/' + currentPatientId + '/preview',
                    {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({appointment_id: apptId, campaign_type: campaign}),
                    }
                );
                var data = await resp.json();
                var channel = document.querySelector('input[name="send_channel"]:checked').value;
                var previewEl = document.getElementById('preview_content');
                var content = channel === 'email'
                    ? (data.email_content || '(empty template)')
                    : (data.sms_content || '(empty template)');
                previewEl.innerHTML = content;
            } catch (err) {
                document.getElementById('preview_content').textContent = 'Error loading preview: ' + err.message;
            }
        }

        async function sendNotification() {
            var apptId = getApptValue();
            var campaign = getCampaignValue();
            var channel = document.querySelector('input[name="send_channel"]:checked').value;
            if (!apptId || !currentPatientId) return;

            var btn = document.getElementById('send_btn');
            btn.disabled = true;
            btn.className = 'btn btn-disabled';
            btn.textContent = 'Sending...';

            try {
                var resp = await fetch(
                    '/plugin-io/api/patient_notify/patient/' + currentPatientId + '/send',
                    {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({appointment_id: apptId, campaign_type: campaign, channel: channel}),
                    }
                );
                var data;
                try { data = await resp.json(); } catch (_e) { data = {}; }
                if (resp.ok && data.result && data.result.success) {
                                    } else {
                    var errMsg = (data.result && data.result.error) || data.error || resp.statusText || 'Unknown error';
                    showBanner('Send failed: ' + errMsg, 'error');
                }
            } catch (err) {
                showBanner('Send failed: ' + err.message, 'error');
            }

            btn.disabled = false;
            btn.className = 'btn btn-primary';
            btn.textContent = 'Send';
            loadHistory();
        }

        /* Init campaign dropdown and wire change events */
        initDropdown('send_campaign');
        document.getElementById('send_campaign').addEventListener('change', onFormChange);
        document.getElementById('send_appointment').addEventListener('change', function() { onAppointmentChange(); });

        loadHistory();
        loadAppointments();
    </script>
</body>
</html>
        """
        return [HTMLResponse(html)]

    def _send_single_notification(self, patient: Any, appointment: Any, campaign_type: str, channel: str, config: Any) -> Any:
        """Send a single notification on the given channel. Returns a DeliveryResult."""
        from patient_notify.services.delivery import (
            DeliveryResult,
            _EMAIL_SUBJECTS,
            _has_direct_email_keys,
            _has_direct_sms_keys,
            _newlines_to_br,
            _normalize_phone_e164,
            _send_email,
            _send_sms,
        )
        from patient_notify.services.config import resolve_templates
        from patient_notify.services.templates import get_template_variables, render_template

        note_type = appointment.note_type
        note_type_id = str(note_type.id) if note_type else None

        sms_template, email_template = resolve_templates(config, campaign_type, note_type_id)

        variables = get_template_variables(patient, appointment, config=config, note_type=note_type)

        if channel == "sms" and _has_direct_sms_keys(self.secrets):
            sms_content = render_template(sms_template, variables)
            phone = None
            for contact in patient.telecom.filter(system="phone", has_consent=True, state="active"):
                normalized = _normalize_phone_e164(contact.value)
                if normalized:
                    phone = normalized
                    break
            if phone:
                return _send_sms(
                    to_phone=phone, body=sms_content,
                    account_sid=self.secrets["twilio-account-sid"],
                    auth_token=self.secrets["twilio-auth-token"],
                    from_number=self.secrets["twilio-phone-number"],
                )
            return DeliveryResult(success=False, channel="sms", error="no valid phone number")

        if channel == "email" and _has_direct_email_keys(self.secrets):
            email_content = render_template(email_template, variables)
            email_addr = None
            for contact in patient.telecom.filter(system="email", has_consent=True, state="active"):
                email_addr = contact.value
                break
            if email_addr:
                subject = _EMAIL_SUBJECTS.get(campaign_type, "Notification")
                return _send_email(
                    to_email=email_addr, subject=subject,
                    html_body=_newlines_to_br(email_content),
                    api_key=self.secrets["sendgrid-api-key"],
                    from_email=self.secrets["sendgrid-from-email"],
                )
            unfiltered = list(patient.telecom.filter(system="email"))
            if unfiltered:
                problems = []
                for c in unfiltered:
                    if not getattr(c, "has_consent", False):
                        problems.append(f"{c.value} has not been verified for consent")
                    elif getattr(c, "state", "") != "active":
                        problems.append(f"{c.value} is not active")
                error_msg = ", ".join(problems) if problems else "no eligible email address"
            else:
                error_msg = "no email address on file"
            return DeliveryResult(success=False, channel="email", error=error_msg)

        return DeliveryResult(
            success=False, channel=channel,
            error=f"cannot send {channel}, credentials not configured",
        )

    @api.post("/patient/<patient_id>/retry")
    def retry_notification(self) -> list[Response | Effect]:
        """Retry a previously failed notification."""
        from canvas_sdk.v1.data.appointment import Appointment
        from canvas_sdk.v1.data.patient import Patient

        from patient_notify.services.config import load_config
        from patient_notify.services.history import get_patient_log, log_delivery_to_cache

        patient_id = self.request.path_params["patient_id"]
        data = self.request.json()
        log_index = data.get("log_index")

        if log_index is None:
            return [JSONResponse(
                {"error": "log_index is required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        entries = get_patient_log(patient_id)
        entries.reverse()

        if log_index < 0 or log_index >= len(entries):
            return [JSONResponse(
                {"error": "Invalid log_index"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        entry = entries[log_index]
        channel = entry.get("channel", "")
        campaign_type = entry.get("campaign_type", "")
        appointment_id = entry.get("appointment_id", "")

        try:
            patient = Patient.objects.prefetch_related("telecom").get(id=patient_id)
        except Patient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        try:
            appointment = Appointment.objects.select_related(
                "provider", "location", "note_type"
            ).get(id=appointment_id)
        except Appointment.DoesNotExist:
            return [JSONResponse({"error": "Appointment not found"}, status_code=HTTPStatus.NOT_FOUND)]

        try:
            config = load_config()
            result = self._send_single_notification(patient, appointment, campaign_type, channel, config)
            log_delivery_to_cache(appointment_id, patient_id, campaign_type, [result])
        except Exception as exc:
            return [JSONResponse(
                {"error": f"Retry failed: {exc}"},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )]

        return [JSONResponse(
            {"result": {"channel": result.channel, "success": result.success, "error": result.error}},
            status_code=HTTPStatus.OK,
        )]

    @api.get("/patient/<patient_id>/appointments")
    def get_patient_appointments(self) -> list[Response | Effect]:
        """Return recent and upcoming appointments for manual send picker."""
        import arrow
        from canvas_sdk.v1.data.appointment import Appointment

        patient_id = self.request.path_params["patient_id"]
        now = arrow.utcnow()
        window_start = now.shift(days=-30).datetime
        window_end = now.shift(days=90).datetime

        appointments = (
            Appointment.objects.filter(
                patient__id=patient_id,
                start_time__gte=window_start,
                start_time__lte=window_end,
            )
            .select_related("provider", "note_type")
            .order_by("-start_time")
        )

        result = []
        for appt in appointments:
            provider_name = ""
            if appt.provider:
                provider_name = f"{appt.provider.first_name} {appt.provider.last_name}"
            note_type_name = ""
            is_telehealth = False
            if appt.note_type:
                note_type_name = appt.note_type.name
                is_telehealth = appt.note_type.is_telehealth
            result.append({
                "id": str(appt.id),
                "start_time": appt.start_time.isoformat(),
                "status": appt.status or "",
                "provider_name": provider_name,
                "note_type_name": note_type_name,
                "is_telehealth": is_telehealth,
            })

        return [JSONResponse(result, status_code=HTTPStatus.OK)]

    @api.post("/patient/<patient_id>/preview")
    def preview_notification(self) -> list[Response | Effect]:
        """Preview rendered templates for a given appointment and campaign type."""
        from canvas_sdk.v1.data.appointment import Appointment
        from canvas_sdk.v1.data.patient import Patient

        from patient_notify.services.config import load_config
        from patient_notify.services.templates import get_template_variables, render_template

        patient_id = self.request.path_params["patient_id"]
        data = self.request.json()
        appointment_id = data.get("appointment_id")
        campaign_type = data.get("campaign_type")

        if not appointment_id or not campaign_type:
            return [JSONResponse(
                {"error": "appointment_id and campaign_type are required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        try:
            appointment = Appointment.objects.select_related(
                "provider", "location", "note_type"
            ).get(id=appointment_id)
        except Appointment.DoesNotExist:
            return [JSONResponse({"error": "Appointment not found"}, status_code=HTTPStatus.NOT_FOUND)]

        config = load_config()
        note_type = appointment.note_type
        note_type_id = str(note_type.id) if note_type else None

        from patient_notify.services.config import resolve_templates

        sms_template, email_template = resolve_templates(config, campaign_type, note_type_id)

        variables = get_template_variables(patient, appointment, config=config, note_type=note_type)

        return [JSONResponse({
            "sms_content": render_template(sms_template, variables),
            "email_content": render_template(email_template, variables),
        }, status_code=HTTPStatus.OK)]

    @api.post("/patient/<patient_id>/send")
    def send_notification(self) -> list[Response | Effect]:
        """Manually send a notification for a specific appointment."""
        from canvas_sdk.v1.data.appointment import Appointment
        from canvas_sdk.v1.data.patient import Patient

        from patient_notify.services.config import load_config
        from patient_notify.services.history import log_delivery_to_cache

        patient_id = self.request.path_params["patient_id"]
        data = self.request.json()
        appointment_id = data.get("appointment_id")
        campaign_type = data.get("campaign_type")
        channel = data.get("channel")

        if not all([appointment_id, campaign_type, channel]):
            return [JSONResponse(
                {"error": "appointment_id, campaign_type, and channel are required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        if channel not in ("sms", "email"):
            return [JSONResponse(
                {"error": "channel must be sms or email"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        try:
            patient = Patient.objects.prefetch_related("telecom").get(id=patient_id)
        except Patient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        try:
            appointment = Appointment.objects.select_related(
                "provider", "location", "note_type"
            ).get(id=appointment_id)
        except Appointment.DoesNotExist:
            return [JSONResponse({"error": "Appointment not found"}, status_code=HTTPStatus.NOT_FOUND)]

        try:
            config = load_config()
            result = self._send_single_notification(patient, appointment, campaign_type, channel, config)
            log_delivery_to_cache(str(appointment_id), patient_id, campaign_type, [result])
        except Exception as exc:
            return [JSONResponse(
                {"error": f"Send failed: {exc}"},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )]

        return [JSONResponse(
            {"result": {"channel": result.channel, "success": result.success, "error": result.error}},
            status_code=HTTPStatus.OK,
        )]

