#!/usr/bin/env node
// Collect verbatim LICENSE/NOTICE text from installed production npm packages.
// Only reads installed packages within node_modules and only writes one fixed
// build artifact. Untrusted command-line output paths are not accepted.
import { existsSync, lstatSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packageRoot = join(root, 'node_modules') + sep;
if (process.argv.length !== 2) throw Error('License notice output path is fixed; no arguments are accepted.');
const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'));
const output = join(root, 'third-party-licenses.txt');
const lines = [
  'Spoolmera compiled frontend: installed production npm package license notices',
  'Dependency list from package-lock.json; notices copied from installed node_modules.',
  'These packages retain their own copyright and license conditions.'
];
let count = 0;
for (const [relative, entry] of Object.entries(lock.packages || {}).sort(([a], [b]) => a.localeCompare(b))) {
  if (!relative.startsWith('node_modules/') || entry.dev === true || entry.devOptional === true) continue;
  const directory = resolve(root, relative);
  if (!directory.startsWith(packageRoot)) throw Error('Unsafe package path in lockfile.');
  if (!existsSync(directory)) {
    if (entry.optional) continue;
    throw Error('Required production npm package not installed: ' + relative);
  }
  // Do not follow package-directory symlinks outside installed node_modules.
  if (!realpathSync(directory).startsWith(packageRoot)) throw Error('Package directory resolves outside node_modules.');
  const manifest = join(directory, 'package.json');
  if (!lstatSync(manifest).isFile()) throw Error('Unsafe package manifest for ' + relative);
  const meta = JSON.parse(readFileSync(manifest, 'utf8'));
  const license = meta.license || entry.license || '';
  if (typeof license !== 'string' || !license) throw Error('Missing license metadata for ' + relative);
  const names = readdirSync(directory).filter((name) => /^(license|licence|copying|notice)(?:$|[._-])/i.test(name)).sort();
  if (!names.length) throw Error('Missing bundled license text for ' + relative);
  lines.push('', '='.repeat(72), meta.name + '@' + meta.version,
             'Declared license: ' + license);
  for (const name of names) {
    const path = join(directory, name);
    if (!lstatSync(path).isFile()) throw Error('Unsafe license notice file for ' + relative);
    const text = readFileSync(path, 'utf8');
    if (!text.trim() || text.length > 1024 * 1024) throw Error('Invalid notice file for ' + relative);
    lines.push('', '--- ' + relative + '/' + name + ' ---', text.trimEnd());
  }
  count++;
}
if (!count) throw Error('No installed production npm packages found.');
writeFileSync(output, lines.join('\n') + '\n', 'utf8');
console.log('Collected notices for ' + count + ' installed production npm packages.');
