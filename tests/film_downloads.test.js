'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {listDownloads, importDownload} = require('../webjs/film_downloads');

function fixture(fn) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'film-download-test-'));
  try {
    const downloads = path.join(root, 'Downloads');
    const output = path.join(root, 'film_inputs');
    fs.mkdirSync(downloads);
    return fn(downloads, output);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}
function createFinished(folder, name, bytes = 4096) {
  const pathTo = path.join(folder, name);
  fs.writeFileSync(pathTo, Buffer.alloc(bytes, 7));
  const old = (Date.now() - 60_000) / 1000;
  fs.utimesSync(pathTo, old, old);
  return pathTo;
}

test('finds completed videos and ignores incomplete downloads and other files', () => fixture((dir) => {
  createFinished(dir, 'Show.S01E02.mkv');
  createFinished(dir, 'Video.MP4');
  createFinished(dir, 'video.mp4.crdownload');
  createFinished(dir, 'not-a-video.txt');
  createFinished(dir, 'tiny.mov', 5);
  fs.writeFileSync(path.join(dir, 'active.mp4'), Buffer.alloc(4096));
  const data = listDownloads(dir);
  assert.deepEqual(new Set(data.files.map(f => f.name)), new Set(['Show.S01E02.mkv', 'Video.MP4']));
  assert.ok(data.files.every(f => /^[a-f0-9]{32}$/.test(f.id)));
}));

test('finds nested season folders and filters symlink files if supported', () => fixture((dir) => {
  const season = path.join(dir, 'Series', 'Season 1');
  fs.mkdirSync(season, {recursive:true});
  const file = createFinished(season, 'Episode 01.mp4');
  try { fs.symlinkSync(file, path.join(dir, 'alias.mp4')); } catch {}
  const files = listDownloads(dir).files;
  assert.equal(files.length, 1);
  assert.equal(files[0].name, 'Series/Season 1/Episode 01.mp4');
}));

test('imports selected video into film_inputs with expected id and content', () => fixture((dir, output) => {
  createFinished(dir, 'episode.mp4');
  const file = listDownloads(dir).files[0];
  const result = importDownload(file.id, output, dir);
  assert.equal(result.ok, true);
  assert.match(result.input_id, /^[a-f0-9]{24}\.mp4$/);
  assert.ok(fs.existsSync(path.join(output, result.input_id)));
  assert.equal(fs.statSync(path.join(output, result.input_id)).size, file.bytes);
  assert.ok(['copy', 'hardlink'].includes(result.method));
}));

test('invalid ids and changed/unfinished files cannot be imported', () => fixture((dir, output) => {
  createFinished(dir, 'clip.webm');
  const record = listDownloads(dir).files[0];
  assert.throws(() => importDownload('../clip.webm', output, dir), /Invalid download selection/);
  assert.throws(() => importDownload('0'.repeat(32), output, dir), /File not found/);
  fs.appendFileSync(path.join(dir, 'clip.webm'), Buffer.from([123]));
  assert.throws(() => importDownload(record.id, output, dir), /File not found/);
}));

test('missing Downloads directory returns empty non-fatal response', () => {
  const missing = path.join(os.tmpdir(), 'missing-film-downloads-' + Date.now() + '-not-created');
  const listed = listDownloads(missing);
  assert.equal(listed.missing, true);
  assert.deepEqual(listed.files, []);
});
