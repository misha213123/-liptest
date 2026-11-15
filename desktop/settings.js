'use strict';
const names = {
  openai: 'OpenAI API Key', hf: 'HF API Key',
  tiktok_client_key: 'TikTok Client Key', tiktok_client_secret: 'TikTok Client Secret',
  instagram_access_token: 'Instagram Access Token',
  cloudflare_tunnel_token: 'Cloudflare Tunnel Token',
  github_updates: 'GitHub — ключ для приватных обновлений (Contents: Read)'
};
let current = null;
const $ = id => document.getElementById(id);
function notice(text) { $('notice').textContent = text; }
function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes <= 0) return '0 МБ';
  if (bytes >= 1024 ** 3) return (bytes / (1024 ** 3)).toFixed(2) + ' ГБ';
  return (bytes / (1024 ** 2)).toFixed(1) + ' МБ';
}
function formatEta(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return 'Время окончания: неизвестно';
  const value = Math.ceil(seconds);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = value % 60;
  return 'Осталось примерно: ' + (hours ? hours + ' ч ' : '') + (minutes ? minutes + ' мин ' : '') + (secs + ' сек');
}
function updateText(state) {
  if (!state || typeof state !== 'object') return;
  const captions = {
    idle: 'Ожидание', unavailable: 'Недоступно', checking: 'Проверка',
    downloading: 'Загрузка', current: 'Последняя версия', ready: 'Готово',
    error: 'Ошибка', needs_auth: 'Нет доступа GitHub',
    deferred: 'Установка отложена', no_release: 'Нет опубликованной версии',
    stalled: 'Загрузка не отвечает'
  };
  $('update-status').textContent = (captions[state.status] || 'Обновления') + ': ' + (state.detail || '');
  const percentage = Number.isFinite(state.percent)
    ? Math.max(0, Math.min(100, state.percent)) : null;
  const showProgress = ['downloading', 'stalled', 'ready', 'deferred'].includes(state.status)
    || (state.status === 'error' && percentage !== null);
  const transfer = $('update-transfer');
  transfer.hidden = !showProgress;
  if (showProgress) {
    const bar = $('update-progress');
    if (percentage === null) bar.removeAttribute('value');
    else bar.value = percentage;
    $('update-percent').textContent = percentage === null
      ? 'Подготовка загрузки…' : percentage.toFixed(1) + '%';
    $('update-speed').textContent = state.status === 'downloading' && state.bytesPerSecond > 0
      ? formatBytes(state.bytesPerSecond) + '/с' : '';
    $('update-size').textContent = formatBytes(state.downloadedBytes) +
      (state.totalBytes > 0 ? ' из ' + formatBytes(state.totalBytes) : ' загружено');
    $('update-eta').textContent = state.status === 'downloading'
      ? formatEta(state.etaSeconds) : state.status === 'stalled'
        ? 'Нет прогресса больше минуты — проверьте интернет.' : '';
  }
  const error = ['error', 'needs_auth', 'stalled'].includes(state.status);
  const errorEl = $('update-error');
  errorEl.hidden = !error;
  if (error) errorEl.textContent = (state.code ? '[' + state.code + '] ' : '') + (state.detail || 'Неизвестная ошибка');
  const checking = ['checking', 'downloading'].includes(state.status);
  $('check-update').disabled = checking;
  $('check-update').textContent = checking
    ? 'Проверка / загрузка…'
    : ['error', 'needs_auth', 'no_release'].includes(state.status) ? 'Повторить проверку'
    : state.status === 'stalled' ? 'Для повтора перезапустите приложение'
    : 'Проверить обновления';
  $('check-update').disabled = checking || state.status === 'stalled';
}

async function refresh() {
  const data = await window.clipStudio.status();
  current = data;
  $('vault-status').textContent = data.available
    ? '✓ Защита Windows активна. Секретные значения нельзя посмотреть после сохранения.'
    : 'Защищённое хранилище недоступно: сохранение ключей отключено.';
  const host = $('secrets');
  host.replaceChildren();
  for (const key of data.keys) {
    const row = document.createElement('div');
    row.className = 'secret';
    const label = document.createElement('label');
    label.textContent = names[key] || key;
    const stored = document.createElement('span');
    stored.className = 'status';
    stored.textContent = data.entries[key] ? 'Сохранено' : 'Не задано';
    label.append(stored);
    const input = document.createElement('input');
    input.type = 'password'; input.autocomplete = 'off';
    input.placeholder = 'Ввести новый ключ (старый скрыт)';
    input.setAttribute('aria-label', names[key] || key);
    const buttons = document.createElement('div'); buttons.className = 'controls';
    const save = document.createElement('button'); save.textContent = 'Сохранить';
    const remove = document.createElement('button'); remove.textContent = 'Удалить'; remove.className = 'secondary';
    save.disabled = !data.available; remove.disabled = !data.available || !data.entries[key];
    save.addEventListener('click', async () => {
      try {
        await window.clipStudio.save(key, input.value);
        input.value = '';
        notice('Ключ сохранён. Перезапусти приложение для применения.');
        await refresh();
      } catch (err) { notice('Ошибка: ' + err.message); }
    });
    remove.addEventListener('click', async () => {
      try {
        await window.clipStudio.remove(key);
        notice('Ключ удалён. Перезапусти приложение для применения.');
        await refresh();
      } catch (err) { notice('Ошибка: ' + err.message); }
    });
    buttons.append(save, remove); row.append(label, input, buttons); host.append(row);
  }
  updateText(data.update);
}
$('check-update').addEventListener('click', async () => {
  try { updateText(await window.clipStudio.checkUpdates()); }
  catch (err) { notice('Ошибка: ' + err.message); }
});
window.clipStudio.onUpdate(updateText);
refresh().catch(err => notice(err.message));
