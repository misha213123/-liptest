'use strict';
const { app, dialog } = require('electron');
const { autoUpdater } = require('electron-updater');
const vault = require('./vault');

const PRIVATE_FEED = Object.freeze({
  provider: 'github', owner: 'misha213123', repo: '-liptest', private: true
});
const emptyProgress = () => ({ percent: null, downloadedBytes: 0, totalBytes: 0,
  bytesPerSecond: 0, etaSeconds: null });
let initiated = false;
let showNotice = null;
let feedConfigured = false;
let downloadTick = 0;
let state = { status: 'idle', detail: '', version: null,
  ...emptyProgress(), code: null, updatedAt: Date.now() };

function emit(status, detail = '', extras = {}) {
  state = { ...state, status, detail, ...extras, updatedAt: Date.now() };
  if (showNotice) showNotice({ ...state });
}
function configureFeed() {
  feedConfigured = false;
  let token;
  try { token = vault.updaterToken(); }
  catch {
    emit('needs_auth', 'Хранилище Windows недоступно. Не получается прочитать GitHub-ключ.');
    return false;
  }
  if (!token) {
    emit('needs_auth', 'Сохраните GitHub-ключ с правом Contents: Read в настройках.');
    return false;
  }
  try {
    autoUpdater.setFeedURL({ ...PRIVATE_FEED, token });
    feedConfigured = true;
    return true;
  } catch {
    emit('error', 'Не удалось настроить обновления из приватного GitHub.', { code: 'FEED' });
    return false;
  }
}
function classifyUpdateError(err) {
  // Never send raw exception text to the renderer: the private feed can contain credentials.
  const message = String(err && err.message || err || '');
  const errorCode = String(err && err.code || '').toUpperCase();
  if (/\b401\b|Bad credentials|Unauthorized/i.test(message))
    return { status: 'needs_auth', detail: 'GitHub отклонил ключ (401). Проверьте его срок действия.', code: 'HTTP_401' };
  if (/\b403\b|Forbidden|Resource not accessible/i.test(message))
    return { status: 'needs_auth', detail: 'Нет доступа к приватному релизу (403). Нужны права Contents: Read.', code: 'HTTP_403' };
  if (/\b404\b|not found|no published versions|Cannot find latest\.yml/i.test(message))
    return { status: 'no_release', detail: 'Обновление в GitHub Releases пока недоступно. Проверьте, опубликован ли новый релиз.', code: 'HTTP_404' };
  if (/\b429\b|rate limit/i.test(message))
    return { status: 'error', detail: 'GitHub временно ограничил запросы. Попробуйте позже.', code: 'HTTP_429' };
  if (/ENOSPC|not enough space|no space left/i.test(message + errorCode))
    return { status: 'error', detail: 'Недостаточно свободного места на диске.', code: 'DISK_FULL' };
  if (/EACCES|EPERM|access denied/i.test(message + errorCode))
    return { status: 'error', detail: 'Windows не разрешает сохранить обновление. Проверьте права доступа.', code: 'PERMISSION' };
  if (/checksum|sha512|signature|verification/i.test(message))
    return { status: 'error', detail: 'Не удалось проверить целостность обновления. Повторите попытку.', code: 'INTEGRITY' };
  if (/ETIMEDOUT|ECONNRESET|ENOTFOUND|EAI_AGAIN|network|timeout|socket hang up/i.test(message + errorCode))
    return { status: 'error', detail: 'Проблема с интернет-соединением при загрузке обновления.', code: 'NETWORK' };
  return { status: 'error', detail: 'Ошибка проверки или загрузки обновления. Повторите попытку после перезапуска.', code: 'UPDATE' };
}
function setup(onChange) {
  if (initiated) return;
  initiated = true;
  showNotice = onChange;
  if (!app.isPackaged || process.platform !== 'win32') {
    emit('unavailable', 'Автообновления доступны только в установленной Windows-версии.');
    return;
  }
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = false;
  autoUpdater.logger = null;
  configureFeed();

  autoUpdater.on('checking-for-update', () =>
    emit('checking', 'Проверяю обновления в GitHub…', { ...emptyProgress(), code: null }));
  autoUpdater.on('update-available', info => {
    downloadTick = Date.now();
    emit('downloading', 'Подготовка загрузки версии ' + info.version + '…', {
      ...emptyProgress(), version: info.version, code: null
    });
  });
  autoUpdater.on('download-progress', progress => {
    downloadTick = Date.now();
    const downloadedBytes = Number(progress.transferred) || 0;
    const totalBytes = Number(progress.total) || 0;
    const bytesPerSecond = Number(progress.bytesPerSecond) || 0;
    const percent = Number.isFinite(progress.percent)
      ? Math.max(0, Math.min(100, progress.percent))
      : totalBytes > 0 ? Math.min(100, downloadedBytes * 100 / totalBytes) : null;
    const etaSeconds = totalBytes > downloadedBytes && bytesPerSecond > 0
      ? Math.ceil((totalBytes - downloadedBytes) / bytesPerSecond) : null;
    emit('downloading', 'Загружается версия ' + (state.version || '') + '…', {
      percent, downloadedBytes, totalBytes, bytesPerSecond, etaSeconds, code: null
    });
  });
  autoUpdater.on('update-not-available', () =>
    emit('current', 'Установлена последняя доступная версия.', { ...emptyProgress(), code: null }));
  autoUpdater.on('error', error => {
    downloadTick = 0;
    const issue = classifyUpdateError(error);
    emit(issue.status, issue.detail, { code: issue.code, etaSeconds: null, bytesPerSecond: 0 });
  });
  autoUpdater.on('update-downloaded', async info => {
    downloadTick = 0;
    emit('ready', 'Версия ' + info.version + ' скачана и проверена.', {
      version: info.version, percent: 100, etaSeconds: 0, bytesPerSecond: 0, code: null
    });
    const busy = await new Promise(resolve => {
      const http = require('node:http');
      const req = http.get('http://127.0.0.1:31876/api/tasks', res => {
        let body = '';
        res.on('data', chunk => { if (body.length < 500000) body += chunk; });
        res.on('end', () => {
          try { resolve(JSON.parse(body).some(task => !!task.running)); }
          catch { resolve(true); }
        });
      });
      req.setTimeout(3000, () => req.destroy());
      req.on('error', () => resolve(true));
    });
    if (busy) {
      emit('deferred', 'Обновление готово. Завершите рендер и перезапустите приложение.');
      return;
    }
    const result = await dialog.showMessageBox({
      type: 'question', title: 'Обновление GTA 6 Clip Studio',
      message: 'Загружена версия ' + info.version + '. Установить сейчас?',
      detail: 'Приложение закроется для обновления. Завершите рендер перед установкой.',
      buttons: ['Позже', 'Установить'], defaultId: 1, cancelId: 0
    });
    if (result.response === 1) autoUpdater.quitAndInstall(false, true);
    else emit('deferred', 'Обновление загружено. Установите его после завершения работы.');
  });
  // Detect a stalled download without presenting it as a completed failure.
  setInterval(() => {
    if (state.status === 'downloading' && downloadTick && Date.now() - downloadTick > 60000) {
      emit('stalled', 'Более минуты нет новых данных о загрузке. Проверьте соединение; при необходимости перезапустите приложение.', {
        bytesPerSecond: 0, etaSeconds: null, code: 'NO_PROGRESS'
      });
    }
  }, 10000);
  setTimeout(() => check(false), 8000);
  setInterval(() => check(false), 60 * 60 * 1000);
}
async function check(manual = true) {
  if (!app.isPackaged || process.platform !== 'win32') {
    emit('unavailable', 'Обновления доступны только в установленной версии Windows.');
    return state;
  }
  if (state.status === 'downloading' || state.status === 'checking') return state;
  if (state.status === 'stalled') {
    if (manual) emit('stalled', 'Загрузка не отвечает. Перезапустите приложение для новой попытки.', { code: 'NO_PROGRESS' });
    return state;
  }
  if (!feedConfigured && !configureFeed()) return state;
  try {
    await autoUpdater.checkForUpdates();
  } catch (error) {
    const issue = classifyUpdateError(error);
    emit(issue.status, issue.detail, { code: issue.code, etaSeconds: null, bytesPerSecond: 0 });
    if (manual && issue.status === 'error') {
      await dialog.showMessageBox({ type: 'warning', message: issue.detail });
    }
  }
  return state;
}
function refreshCredentials() {
  if (!initiated) return;
  if (configureFeed()) check(false);
}
function getState() { return { ...state }; }
module.exports = { setup, check, getState, refreshCredentials };
