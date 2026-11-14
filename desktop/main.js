const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const http = require('node:http');
let server;
let window;
const PORT = 31876;
function root() { return app.isPackaged ? path.join(process.resourcesPath, 'clipper') : path.resolve(__dirname, '..'); }
function waitForServer(tries = 80) {
  http.get('http://127.0.0.1:' + PORT + '/', res => {
    res.resume();
    if (window && !window.isDestroyed()) window.loadURL('http://127.0.0.1:' + PORT);
  }).on('error', () => {
    if (tries > 0) setTimeout(() => waitForServer(tries - 1), 500);
    else dialog.showErrorBox('Startup failed', 'Local server did not start. See the desktop setup instructions.');
  });
}
app.whenReady().then(() => {
  const userData = app.getPath('userData');
  fs.mkdirSync(userData, { recursive: true });
  window = new BrowserWindow({width: 1440,height: 900,webPreferences:{contextIsolation:true,nodeIntegration:false}});
  const script = path.join(root(), 'webjs', 'server.js');
  server = spawn(process.execPath, [script], {
    cwd: root(),
    env: {...process.env, ELECTRON_RUN_AS_NODE:'1', PORT:String(PORT), CLIPPER_DATA_DIR:userData },
    windowsHide:true,stdio:'ignore'
  });
  server.on('error', e => dialog.showErrorBox('Server error', e.message));
  waitForServer();
});
app.on('before-quit', () => { if (server && !server.killed) server.kill(); });
app.on('window-all-closed', () => app.quit());
