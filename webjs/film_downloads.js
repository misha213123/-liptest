// Safe local-only bridge for browser downloads -> Film & Series Studio.
// Integrates with HDrezka Grabber (or any browser downloader) through finished files.
// No browser extension permissions, tokens, or direct website access are required.
'use strict';
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');

const EXTENSIONS = new Set(['.mp4', '.mkv', '.mov', '.webm', '.m4v']);
const MAX_FILE_BYTES = 8 * 1024 * 1024 * 1024;
const MIN_FILE_BYTES = 1024;
const MIN_QUIET_MS = 12000;
const MAX_SCAN = 1500;
const MAX_RESULTS = 60;

function downloadsRoot() {
  const configured = String(process.env.FILM_DOWNLOADS_DIR || '').trim();
  return path.resolve(configured || path.join(os.homedir(), 'Downloads'));
}
function token(file, stats) {
  return crypto.createHash('sha256')
    .update(file + '\u0000' + stats.size + '\u0000' + stats.mtimeMs)
    .digest('hex').slice(0, 32);
}
function listDownloads(root = downloadsRoot(), now = Date.now()) {
  const base = path.resolve(root);
  if (!fs.existsSync(base)) return { folder: base, files: [], missing: true };
  const files = [];
  const dirs = [{ dir: base, depth: 0 }];
  let checked = 0;
  while (dirs.length && checked < MAX_SCAN) {
    const { dir, depth } = dirs.shift();
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); }
    catch { continue; }
    for (const entry of entries) {
      if (++checked > MAX_SCAN) break;
      if (entry.name.startsWith('.') || entry.isSymbolicLink()) continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        // Support series/season subfolders, but never recursively traverse a disk.
        if (depth < 2) dirs.push({ dir: full, depth: depth + 1 });
        continue;
      }
      if (!entry.isFile() || !EXTENSIONS.has(path.extname(entry.name).toLowerCase())) continue;
      let info;
      try { info = fs.lstatSync(full); }
      catch { continue; }
      if (!info.isFile() || info.isSymbolicLink()) continue;
      if (info.size < MIN_FILE_BYTES || info.size > MAX_FILE_BYTES) continue;
      // In-progress Chrome .crdownload / Firefox .part files never enter the list;
      // additionally require an unchanged modification time before importing.
      if (now - info.mtimeMs < MIN_QUIET_MS) continue;
      files.push({
        id: token(full, info),
        name: path.relative(base, full).replace(/\\/g, '/'),
        bytes: info.size,
        modified_ms: info.mtimeMs,
      });
    }
  }
  files.sort((a, b) => b.modified_ms - a.modified_ms);
  return { folder: base, files: files.slice(0, MAX_RESULTS), missing: false };
}
function importDownload(id, outputDir, root = downloadsRoot(), now = Date.now()) {
  if (!/^[0-9a-f]{32}$/.test(String(id || ''))) {
    throw new Error('Invalid download selection.');
  }
  const folder = path.resolve(root);
  const candidates = listDownloads(folder, now);
  const match = candidates.files.find(f => f.id === id);
  if (!match) throw new Error('File not found or download not yet complete. Refresh the list.');
  const source = path.resolve(folder, ...match.name.split('/'));
  const rel = path.relative(folder, source);
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) {
    throw new Error('File is outside Downloads.');
  }
  const st = fs.lstatSync(source);
  if (!st.isFile() || st.isSymbolicLink() ||
      st.size < MIN_FILE_BYTES || st.size > MAX_FILE_BYTES ||
      now - st.mtimeMs < MIN_QUIET_MS || token(source, st) !== id) {
    throw new Error('File changed during download. Retry when it is complete.');
  }
  // Detect replacement by a symlink or moved parent directory.
  let cursor = path.dirname(source);
  while (cursor !== folder) {
    const stDir = fs.lstatSync(cursor);
    if (!stDir.isDirectory() || stDir.isSymbolicLink()) {
      throw new Error('Downloads subfolder is not a regular directory.');
    }
    const parent = path.dirname(cursor);
    if (parent === cursor) throw new Error('Invalid source path.');
    cursor = parent;
  }
  const ext = path.extname(source).toLowerCase();
  fs.mkdirSync(outputDir, { recursive: true });
  const inputId = crypto.randomBytes(12).toString('hex') + ext;
  const destination = path.join(outputDir, inputId);
  let method = 'hardlink';
  try {
    // Fast on the same drive, no 4K series copied in RAM or sent through HTTP.
    fs.linkSync(source, destination);
  } catch (e) {
    if (!['EXDEV', 'EPERM', 'EACCES', 'ENOTSUP', 'EOPNOTSUPP'].includes(e.code)) throw e;
    method = 'copy';
    fs.copyFileSync(source, destination, fs.constants.COPYFILE_EXCL);
  }
  return {
    ok: true, input_id: inputId, filename: match.name, bytes: st.size, method,
  };
}
module.exports = { downloadsRoot, listDownloads, importDownload };
