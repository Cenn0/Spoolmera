import assert from 'node:assert/strict';
import test from 'node:test';
import { isMeasurementText } from './check-i18n.mjs';

test('measurement scanner accepts units and punctuation', () => {
  for (const value of ['12 kg', '0.5 mm', '28 °C', '1 min', '3 GiB', '12×3', '5 g / 7 mg']) {
    assert.equal(isMeasurementText(value), true, value);
  }
});

test('measurement scanner rejects visible text and invalid suffixes', () => {
  for (const value of ['', 'filament', '1 kgx', '10 seconds', 'mystery h?', 'https://example.com']) {
    assert.equal(isMeasurementText(value), false, value);
  }
});

test('long ambiguous unit-like strings are processed without regex backtracking', () => {
  const candidate = 'm'.repeat(25000) + 'X';
  const before = performance.now();
  assert.equal(isMeasurementText(candidate), false);
  assert.ok(performance.now() - before < 2000, 'unexpectedly slow measurement scanner');
});
