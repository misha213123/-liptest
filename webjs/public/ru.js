'use strict';
/* Russian UI pack: translates labels/attributes without touching API payloads or IDs. */
(() => {
  const entries = [
    ['AUTO CLIPPER', 'GTA 6 CLIP STUDIO'],
    ['Logout','Выход'],['Library Sesi','Мои проекты'],['Create Clip','Создать клипы'],
    ['Antrean Tasks','Очередь задач'],['AI Story','AI-монтаж'],['FB Auto Upload','Публикация в Facebook'],
    ['Cookies YouTube','Доступ к YouTube'],['Settings & AI','Настройки и AI'],['Engine Status','Состояние системы'],
    ['AI Proxy','AI-сервис'],['Buat Klip Baru','Создать клипы'],['Total Sesi Video','Всего видео'],
    ['Total Klip Jadi','Готовых клипов'],['Story Clips','AI-клипы'],
    ['Facebook Upload','Публикации Facebook'],['Skor Viral Tertinggi','Лучшие по оценке AI'],
    ['Story Output Terbaru','Последние AI-клипы'],['Daftar Sesi Video','Список проектов'],
    ['Semua status','Все статусы'],['Selesai','Завершено'],['Processing','Обработка'],
    ['Downloading','Загрузка'],['Error','Ошибка'],['Terbaru','Сначала новые'],['Terlama','Сначала старые'],
    ['Klip terbanyak','Больше клипов'],['Skor viral tertinggi','Лучшие оценки'],
    ['Task berjalan...','Выполняются задачи...'],['Prev','Назад'],['Next','Вперёд'],
    ['Hapus Terpilih','Удалить выбранные'],['Batal','Отмена'],['Detail Klip','Детали клипа'],
    ['Render Ulang Klip','Повторный рендер'],['Mulai Render','Начать рендер'],
    ['Momen Highlight AI','AI-моменты'],['Workflow','Обработка видео'],
    ['URL Video (YouTube, TikTok, IG, X)','Ссылка на видео (YouTube, TikTok, Instagram, X)'],
    ['GET','Анализировать'],['Lihat Log Proses','Показать журнал обработки'],['Template','Шаблон'],
    ['Config','Параметры'],['Simpan','Сохранить'],['Output & Efek','Экспорт и эффекты'],
    ['Intro Hook','Вступление'],['Cover Thumbnail','Обложка'],['Watermark Logo','Водяной знак'],
    ['Credit Channel','Указать автора'],['Bakar Subtitle','Встроить субтитры'],
    ['Akselerasi GPU','Ускорение видеокартой'],['Layout & Crop','Кадрирование и формат'],
    ['Rasio Layar (Aspect Ratio)','Соотношение сторон'],
    ['9:16 (Vertikal TikTok, Reels, Shorts)','9:16 (Reels, TikTok, Shorts)'],
    ['4:5 (Portrait Feed Instagram, FB)','4:5 (посты Instagram, Facebook)'],
    ['3:4 (Portrait Tablet, Feed)','3:4 (вертикальное видео)'],
    ['1:1 (Persegi Square Feed)','1:1 (квадрат)'],
    ['16:9 (Landscape YouTube, Standard)','16:9 (горизонтальное YouTube)'],
    ['Mode Smart Crop (Portrait)','Режим умного кадрирования'],['Crop (Auto Follow Face)','Кадрирование с отслеживанием лица'],
    ['Blur (Padding Atas/Bawah)','Размытый фон сверху и снизу'],['Subtitle & Typography','Субтитры и оформление'],
    ['Gaya Animasi Subtitle','Анимация субтитров'],['Pop Highlight (Default)','Выделение слов (по умолчанию)'],
    ['Karaoke (Kata per Kata)','Караоке (по словам)'],
    ['Sync Offset Audio (Detik)','Сдвиг субтитров (сек.)'],
    ['Daftar Job','Список задач'],['Semua job berjalan & terakhir','Текущие и последние задачи'],
    ['auto-refresh 1.5s','Автообновление каждые 1,5 сек.'],
    ['Job','Задача'],['Sesi','Проект'],['Status','Статус'],['Progress','Прогресс'],
    ['Durasi','Длительность'],['Log','Журнал'],['Aksi','Действие'],['Tutup','Закрыть'],
    ['Tidak ada job aktif atau terakhir saat ini.','Пока нет задач.'],
    ['Pilih template bawaan','Выбрать готовый шаблон'],['AI & Engine','AI и движок'],
    ['Server AI','Сервер AI'],['checking…','проверка…'],['Base URL','Адрес сервера'],
    ['API Key','API-ключ'],['Model','Модель'],['Fetch','Обновить'],
    ['Tes Koneksi','Проверить соединение'],['Pencari Momen','Поиск лучших моментов'],
    ['Temperature','Температура модели'],['Bahasa Subtitle','Язык субтитров'],
    ['Prompt','Инструкция для AI'],['Subtitle Engine','Движок субтитров'],
    ['Model Size','Размер модели'],['Video & Tracking','Видео и отслеживание'],
    ['Render Config','Параметры рендера'],['Kualitas & Format','Качество и формат'],
    ['Resolusi','Разрешение'],['Rasio Video','Формат видео'],
    ['Portrait Mode','Вертикальный режим'],['Face Follow','Отслеживание лица'],
    ['Deteksi Wajah','Распознавание лица'],['Style & Preview','Оформление и предпросмотр'],
    ['Subtitle Style','Стиль субтитров'],['Bakar Sub','Встроить субтитры'],
    ['Animasi Subtitle','Анимация субтитров'],['Font Preset (Typography)','Стиль шрифта'],
    ['Sync Offset (detik)','Смещение синхронизации (сек.)'],['Preview Subtitle','Предпросмотр субтитров'],
    ['KATA PERTAMA','ПЕРВОЕ СЛОВО'],['KATA AKTIF','АКТИВНОЕ СЛОВО'],['KATA AKHIR','ПОСЛЕДНЕЕ СЛОВО'],
    ['Intro Hook Style','Оформление вступления'],['Tampilkan Intro','Показывать вступление'],
    ['Box Mode','Вид плашки'],['Teks Fit','По ширине текста'],['Full Width','На всю ширину'],
    ['Half Screen','На половину экрана'],['Font Size','Размер шрифта'],
    ['Corner Radius','Скругление'],['Opacity BG (%)','Непрозрачность фона (%)'],
    ['Duration (s)','Длительность (сек.)'],['Glitch','Глитч'],
    ['Font Color','Цвет текста'],['BG Color','Цвет фона'],
    ['Template Viral','Вирусный шаблон'],['Preview','Предпросмотр'],
    ['INI THUMBNAIL VIRAL!','ВИРУСНАЯ ОБЛОЖКА!'],
    ['Image Watermark','Картинка водяного знака'],['posisi fix kanan atas','Фиксированное положение: сверху справа'],
    ['Aktif','Включено'],['Upload','Загрузить'],
    ['Scale (0.01–1)','Размер (0.01–1)'],['Opacity (0–1)','Непрозрачность (0–1)'],
    ['Preview (kanan atas 0.85/0.05)','Предпросмотр (сверху справа)'],
    ['9:16 Video','Видео 9:16'],['Reset','Сбросить'],
    ['Story Clip Mode','Режим AI-клипов'],
    ['Multi-source narrative → hook + highlight 9:16 (faster-whisper lokal).','Монтаж из нескольких источников с AI-анализом, 9:16 и локальными субтитрами.'],
    ['JSON Raw','Исходный JSON'],['Simpan & Validasi','Сохранить и проверить'],
    ['Simpan sources.json','Сохранить источники'],['Simpan story_recipe.json','Сохранить сценарий'],
    ['Sumber Video','Источники видео'],['Tambah Sumber','Добавить источник'],
    ['Platform: youtube / tiktok / instagram / gdrive / local. Speaker opsional (A/B…).','Источники: YouTube, TikTok, Instagram, Drive или файл. Можно указать спикеров A/B.'],
    ['Tambah Clip','Добавить клип'],['Rasio','Формат'],
    ['Whisper Model','Модель Whisper'],['Resolusi Download','Качество загрузки'],
    ['skip download','Пропустить загрузку'],['RUN STORY','Запустить AI-монтаж'],
    ['Cancel','Отмена'],['Hasil Story Clip','Готовые AI-клипы'],
    ['Facebook Reels Uploader','Публикация Facebook Reels'],
    ['Upload clip dari render_manifest.json ke Page Facebook (jadwal otomatis, rate limit 30/24 jam).','Публикация клипов по расписанию из render_manifest.json (до 30 за 24 часа).'],
    ['Page ID','ID страницы'],['Access Token (Page)','Токен страницы'],
    ['Graph Version','Версия Graph API'],['Interval (jam)','Интервал (часы)'],
    ['test mode (validasi token saja)','Тестовый режим (только проверка токена)'],
    ['Simpan Config','Сохранить настройки'],['Manifest','Манифест'],
    ['UPLOAD','Опубликовать'],['Cookies yt-dlp','Cookies для yt-dlp'],
    ['Kelola file cookies.txt Netscape untuk autentikasi YouTube saat download. Export dari ekstensi browser (mis. "Get cookies.txt LOCALLY") lalu upload & test.','Управление cookies.txt для авторизованной загрузки YouTube. Экспортируйте cookies из браузера и проверьте их.'],
    ['Memuat…','Загрузка…'],['Hapus','Удалить'],['Upload cookies.txt','Загрузить cookies.txt'],
    ['Klik atau taruh file','Нажмите или перетащите файл'],['di sini','сюда'],
    ['Format Netscape, export dari ekstensi browser','Формат Netscape (экспорт из браузера)'],
    ['Test cookies','Проверить cookies'],['Test','Проверить'],
    ['Memuat detail sesi…','Загрузка проекта…'],['Sumber Video:','Источник видео:'],
    ['Highlight','Интересные моменты'],['Cari Ulang','Повторить поиск'],
    ['Pilih Semua','Выбрать всё'],['Proses Terpilih','Обработать выбранное'],
    ['Klip Hasil Render','Готовые клипы'],['Render Ulang','Повторный рендер'],
    ['Buka Create untuk pilih momen & render ulang','Откройте создание клипов, чтобы выбрать моменты и повторить рендер'],
    ['Render Ulang → Create','Повторный рендер → Создать'],
    ['Memuat detail klip…','Загрузка клипа…'],['Informasi Klip','Информация о клипе'],
    ['Judul','Название'],['Waktu & Durasi','Время и длительность'],
    ['Thumbnail Teks','Текст обложки'],['Ukuran File','Размер файла'],
    ['Hashtags','Хештеги'],['Deskripsi','Описание'],['Sumber Video YouTube:','Исходник YouTube:'],
    ['Transkrip Momen','Расшифровка момента'],['Analisis AI','Анализ AI'],
    ['Iskan Clip','Вход в Clip Studio'],['Panel admin : akses terbatas','Личный доступ'],
    ['Masuk','Войти'],['Masukkan password admin.','Введите пароль администратора.'],
    ['Belum ada klip dengan skor viral.','Нет клипов с оценкой AI.'],
    ['Belum ada output story.','Пока нет AI-клипов.'],['Tidak ada sesi.','Пока нет проектов.'],
    ['Pilih sesi','Выберите проект'],['Buka Sesi','Открыть проект'],['Hapus','Удалить'],
    ['Metadata Klip','Метаданные клипа'],['Waktu','Время'],['Channel','Канал'],
    ['File Utama','Основной файл'],['Sumber:','Источник:'],
    ['Subtitle Editor Studio (SRT)','Редактор субтитров (SRT)'],
    ['Simpan Perubahan SRT','Сохранить изменения SRT'],
    ['Render berjalan...','Рендер выполняется...'],
    ['Render selesai!','Рендер завершён!'],
    ['Lihat hasil','Посмотреть результат'],
    ['Highlight tidak ditemukan.','Интересные моменты не найдены.'],
    ['highlight ditemukan, pilih untuk dirender:','моментов найдено, выберите для рендера:'],
    ['Re-generate','Повторный анализ'],['Gagal','Ошибка'],['STOP','Остановить'],
    ['COMPLETED','Завершено'],['PROCESSING','В процессе'],
    ['memuat...','загрузка...'],['Checking...','Проверка...'],
    ['Cari judul sesi atau klip...','Поиск по названию проекта или клипа...'],
    ['Ketik untuk mencari model…','Введите название модели…'],
    ['(tidak diubah)','(без изменений)'],['Toggle dark mode','Переключить тему'],
    ['Menu Utama','Главное меню'],['Paste','Вставить']
  ];
  const dictionary = new Map(entries);
  const reEmoji = /^[\s\u{1F000}-\u{1FAFF}\u2600-\u27BF\uFE0F\u200D\u{1F3FB}-\u{1F3FF}⚡🎬📐🖼️💬🔍⚙️📋🏷️📼📝🎙📦🖥️▶️⏹💾↺↻＋🗑️]+/u;
  const normalize = str => str.replace(/&amp;/g, '&').trim().replace(/\s+/g, ' ');
  function translate(value) {
    const normalized = normalize(value);
    if (!normalized) return value;
    const direct = dictionary.get(normalized);
    if (direct) return value.replace(normalized, direct);
    const prefix = (normalized.match(reEmoji) || [''])[0];
    const core = normalized.slice(prefix.length).replace(/^[\s:·—-]+/,'').trim();
    const replacement = dictionary.get(core);
    return replacement ? value.replace(core, replacement) : value;
  }
  function apply(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      const parent = node.parentElement;
      if (!parent || /^(SCRIPT|STYLE|CODE|PRE|TEXTAREA)$/.test(parent.tagName)) return;
      const next = translate(node.nodeValue);
      if (next !== node.nodeValue) node.nodeValue = next;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    if (/^(SCRIPT|STYLE|TEXTAREA|CODE|PRE)$/.test(node.tagName)) return;
    for (const attr of ['placeholder','title','aria-label','alt']) {
      if (node.hasAttribute(attr)) {
        const before = node.getAttribute(attr);
        const after = translate(before);
        if (before !== after) node.setAttribute(attr, after);
      }
    }
    // Child text nodes only; never replace innerHTML or remove controls/events.
    for (const child of node.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) apply(child);
      else if (child.nodeType === Node.ELEMENT_NODE) apply(child);
    }
  }
  function start() {
    document.documentElement.lang = 'ru';
    document.title = 'GTA 6 Clip Studio';
    apply(document.body);
    const observer = new MutationObserver(records => {
      for (const record of records) {
        if (record.type === 'characterData') apply(record.target);
        for (const node of record.addedNodes) apply(node);
      }
    });
    observer.observe(document.body, { childList:true, subtree:true, characterData:true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once:true });
  else start();
})();
