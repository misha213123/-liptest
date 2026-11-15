# GTA 6 Clip Studio — private Windows updates

## Privacy
This repository must remain **Private**. GitHub Releases in this repository are accessible only to authenticated authorized users. The release CI blocks publishing when repository visibility is Public. Never embed GitHub or social-network tokens into the installer or Git.

## First-time migration from 0.1.0 preview to 0.2.0
The existing 0.1.0 app cannot authenticate to a private GitHub release feed. **The first upgrade must be installed manually once**: download the validated 0.2.0 preview from the private repository's successful Windows Desktop Actions job, unpack and run Setup.exe *over the existing installation* without uninstalling. Keep your projects and existing AppData.

Launch the new installed app and open **Приложение → Настройки и токены**.
Create a **fine-grained personal access token** in GitHub under https://github.com/settings/personal-access-tokens/new with:
- Resource owner: `misha213123`
- Repository access: **Only select repositories** → `-liptest`
- Repository permissions: **Contents: Read-only** and **Metadata: Read** (automatically)
- Short expiration; renew it before it expires.

Paste the token only into `GitHub — ключ для приватных обновлений` in the settings window. It is encrypted on disk with Windows safeStorage/DPAPI and is not given to the Python backend.

Use **Приложение → Проверить обновления** after the token is saved. Do not paste secrets in chat, code, screenshots or console logs. When token expires, create a new one and update it in Settings.

## Publishing stable updates
1. Edit and test desktop source in the feature branch. Do not change `main` or existing personal projects.
2. Wait for **Windows desktop installer (experimental)** build to pass. Download the 0.2.0 preview artifact and test loading, creating clips and opening outputs on Windows.
3. To release the reviewed exact version, use `.github/scripts/publish-private.ps1` from the repo checkout with GitHub CLI installed and logged in (or create and push the matching `vX.Y.Z` tag manually).
4. `.github/workflows/windows-release.yml` runs from the tag: verifies Private visibility, builds Python/FFmpeg runtime, runs smoke checks, uploads **Setup.exe**, **latest.yml**, and blockmap to a private GitHub Release.
5. The desktop client checks GitHub Releases on startup and each hour, downloads the newer release, and asks to install. If any render jobs are running, postpone updating until done.

For future releases, increment `desktop/package.json` version, e.g. `0.2.1`, and publish a new matching tag `v0.2.1`. Never reuse an existing version/tag.

## Limitations
The CI smoke tests check runtime binaries, local server and disk detection; they do NOT guarantee that entire live-stream clipping, AI editing, GPU processing or social publishing workflows work end-to-end. Manually test with a non-sensitive video before calling the release stable.

The app is currently unsigned and may show a Windows warning. Do not disable Windows Defender or SmartScreen globally. The Cloudflare tunnel is **not yet** automatically managed and should remain disabled unless authentication and transport security are reviewed.
