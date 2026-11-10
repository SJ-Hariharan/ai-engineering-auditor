import { expect, it } from 'vitest';
import { formatCents } from './format';

it('formats', () => {
  expect(formatCents(1234)).toBe('$12.34');
});
