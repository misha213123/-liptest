'use strict';
// Windows DPAPI-backed storage via Electron safeStorage. No plaintext fallback.
const fs = require('node:fs');
const path = require('node:path');
const { app, safeStorage } = require('electron');
const KEY_TO_ENV = Object.freeze({
  openai: 'OPENAI_API_KEY',
  hf: 'HF_API_KEY',
  tiktok_client_key: 'TIKTOK_CLIENT_KEY',
  tiktok_client_secret: 'TIKTOK_CLIENT_SECRET',
  instagram_access_token: 'INSTAGRAM_ACCESS_TOKEN',
  cloudflare_tunnel_token: 'CLOUDFLARE_TUNNEL_TOKEN'
});
const keys = Object.keys(KEY_TO_ENV);
function storageFile() { return path.join(app.getPath('userData'), 'vault.json'); }
function assertAvailable() {
  if (process.platform !== 'win32' || !safeStorage.isEncryptionAvailable())
    throw new Error('Защищённое хранилище Windows недоступно. Токен не сохранён.');
}
function validateKey(key) {
  if (!keys.includes(key)) throw new Error('Неизвестное поле настроек');
}
function load() {
  if (!fs.existsSync(storageFile())) return {};
  const obj = JSON.parse(fs.readFileSync(storageFile(), 'utf8'));
  if (!obj || Array.isArray(obj) || typeof obj !== 'object') throw new Error('Повреждён файл хранилища');
  return obj;
}
function persist(obj) {
  const dest = storageFile();
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const tmp = dest + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2), { mode: 0o600, flag: 'w' });
  fs.renameSync(tmp, dest);
}
function set(key, value) {
  validateKey(key);
  assertAvailable();
  if (typeof value !== 'string' || !value.trim() || value.length > 16384)
    throw new Error('Введите корректное значение токена');
  const data = load();
  data[key] = safeStorage.encryptString(value.trim()).toString('base64');
  persist(data);
}
function remove(key) {
  validateKey(key);
  assertAvailable();
  const data = load();
  delete data[key];
  persist(data);
}
function environment() {
  assertAvailable();
  const data = load();
  const env = {};
  for (const [key, envKey] of Object.entries(KEY_TO_ENV)) {
    if (typeof data[key] === 'string') {
      env[envKey] = safeStorage.decryptString(Buffer.from(data[key], 'base64'));
    }
  }
  return env;
}
// Drop the now-unnecessary GitHub token when updating from the private preview.
function removeLegacyGithubUpdates() {
  const data = load();
  if (Object.prototype.hasOwnProperty.call(data, 'github_updates')) {
    delete data.github_updates;
    persist(data);
  }
}
function status() {
  const data = load();
  return {
    available: process.platform === 'win32' && safeStorage.isEncryptionAvailable(),
    entries: Object.fromEntries(keys.map(key => [key, typeof data[key] === 'string']))
  };
}
module.exports = { keys, set, remove, environment, status, removeLegacyGithubUpdates };
