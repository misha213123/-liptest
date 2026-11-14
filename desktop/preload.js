'use strict';
const { contextBridge, ipcRenderer } = require('electron');
// Only the local settings window is authorized by the main-process IPC handlers.
contextBridge.exposeInMainWorld('clipStudio', {
  status: () => ipcRenderer.invoke('settings:status'),
  save: (key, value) => ipcRenderer.invoke('settings:save', key, value),
  remove: key => ipcRenderer.invoke('settings:remove', key),
  checkUpdates: () => ipcRenderer.invoke('settings:checkUpdates'),
  onUpdate: callback => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on('settings:updateStatus', listener);
    return () => ipcRenderer.removeListener('settings:updateStatus', listener);
  }
});
