#!/usr/bin/env node
// Collect verbatim notices from installed production packages in a pinned npm
// lockfile. The output is a fixed local build artifact, never a caller path.
// Use no-follow file descriptors to keep a swapped file from being read.
import {
  closeSync, constants, fstatSync, openSync, readFileSync, renameSync,
  readdirSync, rmSync, writeFileSync,
} from 'node:fs';
import { randomBytes } from 'node:crypto';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packageRoot = join(root, 'node_modules') + sep;
if (process.argv.length !== 2) throw Error('License notice output is fixed; arguments are not accepted.');

function readRegularFile(file) {
  const fd = openSync(file, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = fstatSync(fd);
    if (!info.isFile() || info.size > 1024 * 1024) throw Error('Unsafe or oversized license/metadata file.');
    return readFileSync(fd, { encoding: 'utf8' });
  } finally {
    closeSync(fd);
  }
}

const lock = JSON.parse(readRegularFile(join(root, 'package-lock.json')));
const output = join(root, 'third-party-licenses.txt');
const lines = [
  'Spoolmera compiled frontend: installed production npm package license notices',
  'Dependency list from package-lock.json; notices copied from installed node_modules.',
  'These packages retain their own copyright and license conditions.',
];
let count = 0;
for (const [relative, entry] of Object.entries(lock.packages || {}).sort(([a], [b]) => a.localeCompare(b))) {
  if (!relative.startsWith('node_modules/') || entry.dev === true || entry.devOptional === true) continue;
  const directory = resolve(root, relative);
  if (!directory.startsWith(packageRoot)) throw Error('Unsafe package path in lockfile.');

  // Directories in npm's install tree must not be symlinks. Reject a missing
  // required package, but allow absent optional platform-specific packages.
  let directoryFd;
  try {
    directoryFd = openSync(directory, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  } catch (error) {
    if (entry.optional && error?.code === 'ENOENT') continue;
    throw new Error('Missing or unsafe production npm package: ' + relative, { cause: error });
  } finally {
    if (directoryFd !== undefined) closeSync(directoryFd);
  }

  const meta = JSON.parse(readRegularFile(join(directory, 'package.json')));
  const license = meta.license || entry.license || '';
  if (!meta.name || !meta.version || (entry.version && entry.version !== meta.version)) {
    throw Error('Installed package metadata does not match lockfile: ' + relative);
  }
  if (typeof license !== 'string' || !license) throw Error('Missing license metadata for ' + relative);

  const names = readdirSync(directory).filter(name => /^(license|licence|copying|notice)(?:$|[._-])/i.test(name)).sort();
  if (!names.length) throw Error('Missing bundled license text for ' + relative);
  lines.push('', '='.repeat(72), meta.name + '@' + meta.version, 'Declared license: ' + license);
  for (const name of names) {
    const text = readRegularFile(join(directory, name));
    if (!text.trim()) throw Error('Empty license/notice file for ' + relative);
    lines.push('', '--- ' + relative + '/' + name + ' ---', text.trimEnd());
  }
  count++;
}
if (!count) throw Error('No installed production npm packages found.');

// Atomic rename replaces a symlink at the destination without following it.
const temporary = join(root, '.third-party-licenses.' + randomBytes(12).toString('hex') + '.tmp');
try {
  writeFileSync(temporary, lines.join('\n') + '\n', { flag: 'wx', mode: 0o600 });
  renameSync(temporary, output);
} finally {
  rmSync(temporary, { force: true });
}
console.log('Collected notices for ' + count + ' installed production npm packages.');
