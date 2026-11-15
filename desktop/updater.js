'use strict';
const { app, dialog } = require('electron');
const { autoUpdater } = require('electron-updater');
const vault = require('./vault');
const PRIVATE_FEED = Object.freeze({ provider: 'github', owner: 'misha213123', repo: '-liptest', private: true });


let initiated = false;
let state = { status: 'idle', detail: '' };
let showNotice = null;
let feedConfigured = false;
function configureFeed() {
  feedConfigured = false;
  let token;
  try { token = vault.updaterToken(); }
  catch { emit('needs_auth', 'Хранилище Windows недоступно.'); return false; }
  if (!token) { emit('needs_auth', 'Добавьте ключ GitHub (только чтение) в настройках приложения.'); return false; }
  autoUpdater.setFeedURL({ ...PRIVATE_FEED, token });
  feedConfigured = true;
  return true;
}

function classifyUpdateError(err) {
  const message = String(err && err.message || err || '');
  if (/\b404\b|not found|No published versions|Cannot find latest\.yml|release.*not found/i.test(message)) {
    return { status: 'no_release', detail: 'Пока нет опубликованных обновлений в приватном GitHub Releases. Установлена версия ' + app.getVersion() + '.' };
  }
  if (/\b401\b|\b403\b|Bad credentials|Resource not accessible|Unauthorized|Forbidden/i.test(message)) {
    return { status: 'needs_auth', detail: 'GitHub не разрешил доступ. Проверьте срок действия токена и Contents: Read-only.' };
  }
  return { status: 'error', detail: 'Не удалось проверить обновления. Проверьте соединение с GitHub и повторите попытку.' };
}
function emit(status, detail = '') {
  state = { status, detail };
  if (showNotice) showNotice(state);
}
function setup(onChange) {
  if (initiated) return;
  initiated = true;
  showNotice = onChange;
  if (!app.isPackaged || process.platform !== 'win32') {
    emit('unavailable', 'Обновления проверяются только в установленной версии Windows.');
    return;
  }
  autoUpdater.autoDownload = true;
  autoUpdater.logger = null;
  configureFeed();
  autoUpdater.autoInstallOnAppQuit = false;
  autoUpdater.on('checking-for-update', () => emit('checking', 'Проверяю GitHub Releases…'));
  autoUpdater.on('update-available', info => emit('downloading', 'Скачивается версия ' + info.version));
  autoUpdater.on('download-progress', p => emit('downloading', 'Загружено ' + Math.round(p.percent) + '%'));
  autoUpdater.on('update-not-available', () => emit('current', 'Установлена последняя версия.'));
  autoUpdater.on('error', err => { const info = classifyUpdateError(err); emit(info.status, info.detail); });
  autoUpdater.on('update-downloaded', async info => {
    emit('ready', 'Версия ' + info.version + ' готова к установке.');
    const busy = await new Promise(resolve => {
      const http = require('node:http');
      const req = http.get('http://127.0.0.1:31876/api/tasks', res => {
        let body = '';
        res.on('data', c => { if (body.length < 500000) body += c; });
        res.on('end', () => {
          try { resolve(JSON.parse(body).some(task => !!task.running)); }
          catch { resolve(true); }
        });
      });
      req.setTimeout(3000, () => req.destroy());
      req.on('error', () => resolve(true));
    });
    if (busy) {
      emit('deferred', 'Обновление скачано. Сначала завершите рендер, затем перезапустите приложение.');
      return;
    }
    const result = await dialog.showMessageBox({
      type: 'question', title: 'Обновление GTA 6 Clip Studio',
      message: 'Скачана версия ' + info.version + '. Установить сейчас?',
      detail: 'Сначала завершите активные рендеры: приложение будет закрыто для обновления.',
      buttons: ['Позже', 'Установить'], defaultId: 0, cancelId: 0
    });
    if (result.response === 1) autoUpdater.quitAndInstall(false, true);
  });
  // Startup check, without blocking render/startup.
  setTimeout(() => check(false), 8000);
  // Recheck while the app stays open, without disrupting the UI or renders.
  setInterval(() => check(false), 60 * 60 * 1000);
}
async function check(manual = true) {
  if (!app.isPackaged || process.platform !== 'win32') {
    emit('unavailable', 'Обновления доступны только в Windows Setup.exe');
    return state;
  }
  if (!feedConfigured && !configureFeed()) return state;
  try {
    await autoUpdater.checkForUpdates();
  } catch (e) {
    const info = classifyUpdateError(e);
    emit(info.status, info.detail);
    if (manual && info.status !== 'no_release') await dialog.showMessageBox({ type: 'warning', message: info.detail });
  }
  return state;
}
function refreshCredentials() {
  if (!initiated) return;
  if (configureFeed()) check(false);
}
function getState() { return state; }
module.exports = { setup, check, getState, refreshCredentials };
