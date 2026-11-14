'use strict';
const { app, dialog } = require('electron');
const { autoUpdater } = require('electron-updater');

let initiated = false;
let state = { status: 'idle', detail: '' };
let showNotice = null;
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
  autoUpdater.autoInstallOnAppQuit = false;
  autoUpdater.on('checking-for-update', () => emit('checking', 'Проверяю GitHub Releases…'));
  autoUpdater.on('update-available', info => emit('downloading', 'Скачивается версия ' + info.version));
  autoUpdater.on('download-progress', p => emit('downloading', 'Загружено ' + Math.round(p.percent) + '%'));
  autoUpdater.on('update-not-available', () => emit('current', 'Установлена последняя версия.'));
  autoUpdater.on('error', err => emit('error', 'Ошибка проверки: ' + err.message));
  autoUpdater.on('update-downloaded', async info => {
    emit('ready', 'Версия ' + info.version + ' готова к установке.');
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
}
async function check(manual = true) {
  if (!app.isPackaged || process.platform !== 'win32') {
    emit('unavailable', 'Обновления доступны только в Windows Setup.exe');
    return state;
  }
  try {
    await autoUpdater.checkForUpdates();
  } catch (e) {
    emit('error', 'Проверка не удалась: ' + e.message);
    if (manual) await dialog.showMessageBox({ type: 'warning', message: state.detail });
  }
  return state;
}
function getState() { return state; }
module.exports = { setup, check, getState };
