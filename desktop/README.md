# Windows desktop installer — experimental scaffold

This branch adds an Electron window and GitHub Actions NSIS Setup.exe build without changing the existing Python rendering engine.

## Current limitations (important)
The installer currently bundles the source files and Electron/Node runtime, **not a complete portable Python runtime, installed Python packages, FFmpeg, yt-dlp, or AI models**. The Python backend will not run on a clean Windows machine until those dependencies are provisioned. It does not yet provide a credentials vault, OAuth onboarding, automatic tunnels, or production-grade offline startup.

The existing web server may require configuration and authentication before it can be used; opening it in Electron does not bypass those requirements.

## Next engineering tasks
1. Bundle/test a relocatable Python environment and pinned packages, configure CLIPPER_PY.
2. Bundle FFmpeg and yt-dlp; move all runtime writes to a user-writable app data directory.
3. Add first-run onboarding for configuration and OAuth, storing secrets with Windows DPAPI / Credential Manager.
4. Implement provider-specific callback handling; only provision a persistent Cloudflare tunnel if required.
5. Add signed installer, smoke tests on clean Windows, and publishing after validation.

Build manually: `cd desktop && npm install && npm run dist:win`.
Or run GitHub Actions: **Windows desktop installer (experimental)**.
