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
function updateText(state) {
  const captions = { idle: 'Ожидание', unavailable: 'Недоступно', checking: 'Проверка',
    downloading: 'Загрузка', current: 'Последняя версия', ready: 'Готово', error: 'Ошибка',
    needs_auth: 'Нужно подключить GitHub', deferred: 'Обновление отложено', no_release: 'Обновлений пока нет' };
  $('update-status').textContent = (captions[state.status] || state.status) + ': ' + (state.detail || '');
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
