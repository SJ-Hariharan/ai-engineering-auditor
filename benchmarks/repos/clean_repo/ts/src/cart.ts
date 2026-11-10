import { formatCents } from './format';

export interface Line {
  sku: string;
  qty: number;
  priceCents: number;
}

export function total(lines: Line[]): number {
  return lines.reduce((sum, l) => sum + l.qty * l.priceCents, 0);
}

export function summary(lines: Line[]): string {
  return `${lines.length} lines, ${formatCents(total(lines))}`;
}
