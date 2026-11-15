# GTA 6 Clip Studio: public updates without GitHub tokens

New installer versions are published as PUBLIC GitHub Releases. After installing 0.2.2, the application checks `misha213123/-liptest` on startup and hourly; no GitHub login or access token is required. AI and platform credentials still use Windows-protected storage. The old GitHub updater token is removed from local app data on first startup of 0.2.2.

## Security and prerequisites
- The repository must be **Public**. The release workflow stops while the repo is Private.
- Public visibility reveals source code AND previous Git commit history. Rotate/revoke any credentials previously committed before switching.
- Never upload personal `.env`, cookies, OAuth secrets, or AI API keys.
- Keep the application ID unchanged so updates preserve AppData.

## First migration from 0.2.0
- Installed 0.2.0 still has the private token-feed updater and may error when checking for public releases.
- If in-place update fails, download the first public installer from GitHub Releases and install over 0.2.0, **without uninstalling**. After 0.2.2, later updates work without a token.

## Release steps
1. Switch GitHub repository Settings > General > Danger Zone to **Public** after checking history for accidental secrets.
2. Verify the Windows preview build and end-to-end render.
3. From the repository clone:
   - `git fetch origin feature/windows-desktop-installer`
   - `git tag -a v0.2.2 origin/feature/windows-desktop-installer -m "GTA 6 Clip Studio v0.2.2"`
   - `git push origin v0.2.2`
4. The tag triggers `.github/workflows/windows-release.yml` which validates public visibility, stages dependencies, tests Windows binaries, and publishes Setup.exe, `latest.yml`, and update blockmaps.
5. Open the app > Приложение > Проверить обновления.

## Limitations
The CI smoke tests cover dependency health, not real clip generation, livestream analysis, or full social posting. The installer is unsigned and Windows may display a publisher warning.
