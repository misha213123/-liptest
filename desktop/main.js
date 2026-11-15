'use strict';
const { app, BrowserWindow, Menu, dialog, ipcMain } = require('electron');
const { spawn } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const fs = require('node:fs');
const http = require('node:http');
const vault = require('./vault');
const updater = require('./updater');
let server, window, settingsWindow;
const PORT = 31876;
const sourceRoot = () => app.isPackaged ? path.join(process.resourcesPath, 'clipper') : path.resolve(__dirname, '..');
const runtimeRoot = () => app.isPackaged ? path.join(app.getPath('userData'), 'runtime') : sourceRoot();

function prepareRuntime() {
  const root = runtimeRoot();
  fs.mkdirSync(path.join(root, 'output', 'sessions'), { recursive: true });
  fs.mkdirSync(path.join(root, 'config'), { recursive: true });
  if (app.isPackaged) {
    const marker = path.join(root, '.installed-version');
    const installedVersion = fs.existsSync(marker) ? fs.readFileSync(marker, 'utf8') : '';
    if (installedVersion !== app.getVersion()) {
      const src = sourceRoot();
      // Update code on each new version, but never overwrite personal data.
      fs.cpSync(src, root, { recursive: true, force: true, filter: file => {
        const rel = path.relative(src, file).replace(/\\/g, '/');
        if (!rel) return true;
        if (['python', 'ffmpeg', 'bin', 'output', 'faster_whisper_models'].some(name => rel === name || rel.startsWith(name + '/'))) return false;
        const basename = path.basename(file).toLowerCase();
        if (['config.json', 'cookies.txt', 'client_secret.json', 'youtube_credentials.json', 'custom_presets.json'].includes(basename)) return false;
        if (basename.endsWith('.session') || basename === '.env' || basename.startsWith('.env.')) return false;
        return true;
      }});
      const sourceModel = path.join(sourceRoot(), 'bin', 'face_landmarker.task');
      const targetModel = path.join(root, 'bin', 'face_landmarker.task');
      if (fs.existsSync(sourceModel)) {
        fs.mkdirSync(path.dirname(targetModel), { recursive: true });
        fs.copyFileSync(sourceModel, targetModel);
      }
      fs.writeFileSync(marker, app.getVersion(), 'utf8');
    }
  }
  const cfg = path.join(root, 'config.json');
  if (!fs.existsSync(cfg)) {
    fs.writeFileSync(cfg, JSON.stringify({
      ai_providers: {
        highlight_finder: { base_url: 'https://api.openai.com/v1', model: 'gpt-4.1' },
        caption_maker: { model: 'whisper-1', faster_whisper: { model_size: 'small' } }
      },
      aspect_ratio: '9:16', resolution: '1080p', num_clips: 5, subtitle_enabled: true
    }, null, 2));
  }
  return root;
}
function waitForServer(tries = 80) {
  const req = http.get('http://127.0.0.1:' + PORT + '/', res => {
    res.resume();
    if (window && !window.isDestroyed()) window.loadURL('http://127.0.0.1:' + PORT);
  });
  req.on('error', () => {
    if (tries > 0) setTimeout(() => waitForServer(tries - 1), 500);
    else dialog.showErrorBox('Не удалось запустить приложение', 'Локальный сервер не запустился. Проверьте установку и зависимости Python.');
  });
  req.setTimeout(3000, () => req.destroy());
}
function openSettings() {
  if (settingsWindow && !settingsWindow.isDestroyed()) { settingsWindow.focus(); return; }
  settingsWindow = new BrowserWindow({
    width: 640, height: 740, minWidth: 520, minHeight: 600, title: 'Настройки GTA 6 Clip Studio',
    parent: window, modal: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false, contextIsolation: true, sandbox: true
    }
  });
  settingsWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  settingsWindow.webContents.on('will-navigate', event => event.preventDefault());
  settingsWindow.loadFile(path.join(__dirname, 'settings.html'));
  settingsWindow.on('closed', () => { settingsWindow = null; });
}
function authorized(event) {
  const expected = pathToFileURL(path.join(__dirname, 'settings.html')).href;
  if (!settingsWindow || event.sender !== settingsWindow.webContents || event.senderFrame.url !== expected)
    throw new Error('Доступ запрещён');
}
ipcMain.handle('settings:status', event => {
  authorized(event);
  return { ...vault.status(), keys: vault.keys, update: updater.getState(), version: app.getVersion() };
});
ipcMain.handle('settings:save', (event, key, value) => {
  authorized(event); vault.set(key, value); return vault.status();
});
ipcMain.handle('settings:remove', (event, key) => {
  authorized(event); vault.remove(key); return vault.status();
});
ipcMain.handle('settings:checkUpdates', async event => {
  authorized(event);
  return await updater.check(true);
});
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => {
    if (window && !window.isDestroyed()) { if (window.isMinimized()) window.restore(); window.focus(); }
  });
  app.whenReady().then(() => {
    try { vault.removeLegacyGithubUpdates(); } catch { /* Leave other credentials unchanged. */ }
    const root = prepareRuntime();
    const secureEnvironment = {};
    const pythonExe = path.join(sourceRoot(), 'python', 'python.exe');
    if (fs.existsSync(pythonExe)) secureEnvironment.CLIPPER_PY = pythonExe;
    const ffmpegDir = path.join(sourceRoot(), 'ffmpeg');
    const binaryDir = path.join(sourceRoot(), 'bin');
    secureEnvironment.PATH = [ffmpegDir, binaryDir, process.env.PATH || ''].join(path.delimiter);
    try { Object.assign(secureEnvironment, vault.environment()); }
    catch (e) { console.warn('Secure credentials unavailable:', e.message); }
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { label: 'Приложение', submenu: [
        { label: 'Настройки и токены', click: openSettings },
        { label: 'Проверить обновления', click: () => updater.check(true) },
        { type: 'separator' }, { role: 'quit', label: 'Выход' }
      ] }
    ]));
    window = new BrowserWindow({
      width: 1440, height: 900, minWidth: 900, minHeight: 650,
      title: 'GTA 6 Clip Studio',
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true }
    });
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.on('will-navigate', (event, target) => {
      if (!target.startsWith('http://127.0.0.1:' + PORT + '/')) event.preventDefault();
    });
    server = spawn(process.execPath, [path.join(root, 'webjs', 'server.js')], {
      cwd: root, windowsHide: true, stdio: 'ignore',
      env: { ...process.env, ...secureEnvironment, ELECTRON_RUN_AS_NODE: '1',
        PORT: String(PORT), CLIPPER_DESKTOP: '1', CLIPPER_DATA_DIR: app.getPath('userData') }
    });
    server.on('error', e => dialog.showErrorBox('Ошибка сервера', e.message));
    waitForServer();
    updater.setup(state => {
      if (settingsWindow && !settingsWindow.isDestroyed()) settingsWindow.webContents.send('settings:updateStatus', state);
    });
  }).catch(e => dialog.showErrorBox('Ошибка запуска', e.message));
  app.on('before-quit', () => { if (server && !server.killed) server.kill(); });
  app.on('window-all-closed', () => app.quit());
}
