import { describe, expect, it } from 'vitest';
import { summary, total } from './cart';

describe('cart', () => {
  it('totals lines', () => {
    expect(total([{ sku: 'a', qty: 2, priceCents: 150 }])).toBe(300);
  });
  it('summarises', () => {
    expect(summary([{ sku: 'a', qty: 1, priceCents: 100 }])).toBe('1 lines, $1.00');
  });
});
