#!/usr/bin/env bash
# Start Auto Clipper Web UI (Linux/macOS)
cd "$(dirname "$0")/webjs" || exit 1
export STREAMER_GPU_TURBO="${STREAMER_GPU_TURBO:-1}"
export STREAMER_GPU_TURBO_SOURCE="${STREAMER_GPU_TURBO_SOURCE:-1080p}"
exec node server.js