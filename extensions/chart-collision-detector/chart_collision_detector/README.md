chart-collision-detector
========================

## Description

The Chart Collision Detector is a Canvas application plugin that monitors patient chart access and warns providers when multiple users are simultaneously viewing the same patient's chart. This helps prevent conflicts and confusion that can arise from concurrent chart access and editing.

## Features

- **Real-time Collision Detection**: Automatically detects when multiple providers are viewing the same patient chart
- **Warning Modal**: Displays a clear warning modal showing which other users are currently viewing the chart
- **Context-Aware**: Monitors chart access both when the application is opened and when navigating between pages
- **Viewer Tracking**: Maintains a list of all current viewers for each patient chart using a cache system
- **Configurable TTL**: Cache timeout is configurable via secrets (default: 5 minutes)

## How It Works

1. When a provider opens or navigates to a patient chart, the application checks for other active viewers
2. The system tracks all current viewers in a cache with a configurable TTL (default 5 minutes)
3. If other providers are detected viewing the same chart, a warning modal is displayed
4. The modal shows:
   - A warning icon
   - The names of other users currently viewing the chart
   - A message about potential conflicts from concurrent editing

## Configuration

The cache TTL (Time To Live) can be configured by setting the `CACHE_TTL_SECONDS` secret in your plugin configuration. If not set, it defaults to 300 seconds (5 minutes).

