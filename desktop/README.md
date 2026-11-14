# GTA 6 Clip Studio — Windows desktop installer (experimental)

This is a personal Windows desktop wrapper for the existing Auto Clipper engine.
The original Python render engine is not intentionally rewritten.

## Implemented in this branch

- Electron NSIS Setup.exe **preview** build in GitHub Actions (`.github/workflows/windows-desktop.yml`).
- Main application menu: **Настройки и токены** and **Проверить обновления**.
- Update client using `electron-updater`: checks GitHub Releases on startup, downloads updates, asks before installing.
- Dedicated settings window: add/delete API and tunnel tokens without editing `.env` by hand.
- Encrypted token storage with Windows DPAPI via Electron `safeStorage`; no plaintext fallback. Only token *presence* is shown.
- At launch, the saved values are decrypted into the backend child process environment. A restart is required after changing keys.
- App data and outputs live under the application's per-user Windows data directory and survive updates.
- Desktop web server binds to `127.0.0.1` only. Legacy non-desktop web server behavior is unchanged.
- Removed embedded credential defaults from the desktop branch's web server. **Rotate any keys previously committed to the public Git history.**

## Important limitations (do not distribute as production software yet)

The setup currently **does not include a self-contained Python runtime or Python packages, FFmpeg, yt-dlp, or AI models**. Those are still needed to render on a clean PC. It also does not automate Cloudflare tunnel provisioning or OAuth onboarding. Some legacy Python modules read `config.json` instead of environment variables; these must be migrated before all stored tokens work end-to-end. Existing OAuth credential files are not migrated to the vault yet.

The release workflow deliberately stops if bundled Python and FFmpeg are absent. This prevents publicly releasing a supposedly complete installer that cannot render.

The repository is public. A GitHub Release in this repository will also be publicly downloadable. Do not put API keys, user configs, OAuth credentials or session files inside the app bundle.

## Development / preview build

Run `.github/workflows/windows-desktop.yml` from the feature branch, or on Windows:

```powershell
cd desktop
npm install
npm run dist:win -- --publish never
```

You can download the unsigned *preview* Setup.exe from the GitHub Actions artifact when the job succeeds. Expect Windows SmartScreen warnings if unsigned; this is not a production-ready installer.

## Stable updates (after dependency packaging and clean-PC testing)

The separate `.github/workflows/windows-release.yml` workflow builds and publishes an NSIS installer, `latest.yml`, and update blockmaps when a semantic version tag `vX.Y.Z` is pushed. The version must equal `desktop/package.json`'s `version`; the release gate checks for packaged runtime components and obvious secrets before publishing. The updater discovers public GitHub Releases from the package's configured owner/repository.

1. Complete portable Python / dependency packaging and test a clean Windows install.
2. Review token and OAuth integration, sign the Windows installer when possible.
3. Bump `desktop/package.json` version, merge the verified code into a stable branch, tag it `vX.Y.Z`.
4. When release CI finishes, install Setup.exe from GitHub Releases once. Future versions will be checked automatically.
5. During rendering, decline the update installation prompt and install when jobs finish.

For a truly private installer distribution, change the update hosting plan before enabling release publishing. Never embed GitHub personal access tokens in a desktop app.

## Next steps

- Add a tested, relocatable Python runtime, dependencies, FFmpeg and yt-dlp to `desktop/runtime` and packaging filters.
- Change all legacy config readers to respect the vault-backed environment without persisting secrets to `config.json`.
- Integrate OAuth credential refresh, per-provider scopes and tunnel management in the settings UI.
- Add clean-machine Windows smoke tests for first launch, actual clip render and update from version N to N+1.
