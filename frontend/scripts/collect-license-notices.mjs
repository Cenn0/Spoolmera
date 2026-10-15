#!/usr/bin/env node
// Collect the exact LICENSE/NOTICE text of installed production npm packages.
// Fails if an installed production dependency lacks verifiable bundled notices.
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'));
const dest = process.argv[2] || 'third-party-licenses.txt';
const output = isAbsolute(dest) ? dest : resolve(process.cwd(), dest);
const lines = [
  'Spoolmera compiled frontend: installed production npm package license notices',
  'Dependency list from package-lock.json; notices copied from installed node_modules.',
  'These packages retain their own copyright and license conditions.'
];
let count = 0;
for (const [relative, entry] of Object.entries(lock.packages || {}).sort(([a], [b]) => a.localeCompare(b))) {
  if (!relative.startsWith('node_modules/') || entry.dev === true || entry.devOptional === true) continue;
  const directory = resolve(root, relative);
  if (!directory.startsWith(root + '/')) throw Error('Unsafe package path in lockfile.');
  if (!existsSync(directory)) {
    if (entry.optional) continue;
    throw Error('Required production npm package not installed: ' + relative);
  }
  const meta = JSON.parse(readFileSync(join(directory, 'package.json'), 'utf8'));
  const license = meta.license || entry.license || '';
  if (typeof license !== 'string' || !license) throw Error('Missing license metadata for ' + relative);
  const names = readdirSync(directory).filter((name) => /^(license|licence|copying|notice)(?:$|[._-])/i.test(name)).sort();
  if (!names.length) throw Error('Missing bundled license text for ' + relative);
  lines.push('', '='.repeat(72), meta.name + '@' + meta.version,
             'Declared license: ' + license);
  for (const name of names) {
    const path = join(directory, name);
    const text = readFileSync(path, 'utf8');
    if (!text.trim() || text.length > 1024 * 1024) throw Error('Invalid notice file for ' + relative);
    lines.push('', '--- ' + relative + '/' + name + ' ---', text.trimEnd());
  }
  count++;
}
if (!count) throw Error('No installed production npm packages found.');
writeFileSync(output, lines.join('\n') + '\n', 'utf8');
console.log('Collected notices for ' + count + ' installed production npm packages.');
