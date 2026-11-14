# GTA 6 Clip Studio — обновление без переустановки

The installed 0.1.0 preview already contains electron-updater support. It can update itself **only after a newer version has been published to GitHub Releases** with an NSIS installer and `latest.yml`. GitHub Actions preview artifacts are not an update feed.

## Publishing the first production update

1. Verify the branch preview workflow passed and download the installer artifact.
2. Smoke test on a clean Windows machine: app start, local server, GPU/FFmpeg, yt-dlp, loading a video URL, clipping, subtitles, and saving to disk.
3. Review security: no API keys, session cookies, OAuth secrets or private configuration files in the build. The repository is public; releases are publicly downloadable.
4. Confirm `desktop/package.json` is version `0.2.0`. From a clone:

```powershell
git checkout feature/windows-desktop-installer
git pull --ff-only origin feature/windows-desktop-installer
git tag -a v0.2.0 -m "GTA 6 Clip Studio 0.2.0"
git push origin v0.2.0
```

5. The `windows-release.yml` workflow builds the portable runtime, runs smoke tests and publishes `GTA6-Clip-Studio-Setup-0.2.0.exe`, `latest.yml` and update blockmaps.
6. Start an existing 0.1.0 install. It checks the release feed on startup, downloads the update, then prompts to install. No uninstall is required.

## Future releases

Bump `desktop/package.json` version to `0.2.1`, `0.3.0`, etc., run tests, tag `v0.2.1`, push the tag. Users get the update automatically while preserving their Windows user data directory.

**Do not publish a new release just because compilation succeeded.** Test all supported uploaders and their OAuth flows with your own accounts. First-run connected social accounts and cloud tunnels still require user authorization.

The current installer is unsigned. Windows may warn about the publisher; code signing is recommended before normal distribution.

Do not enable a public Cloudflare Tunnel to this web server until a proper authentication and endpoint exposure audit has been completed. Personal desktop rendering works without a tunnel.
