// GT:ts_high_complexity|high-complexity|CWE-NA|yes
export function classify(x: number, y: number, z: number) {
  let r = 0;
  if (x === 0) { r += 0; } else if (y === 0 && z !== 0) { r -= 0; }
  if (x === 1) { r += 1; } else if (y === 1 && z !== 1) { r -= 1; }
  if (x === 2) { r += 2; } else if (y === 2 && z !== 2) { r -= 2; }
  if (x === 3) { r += 3; } else if (y === 3 && z !== 3) { r -= 3; }
  if (x === 4) { r += 4; } else if (y === 4 && z !== 4) { r -= 4; }
  if (x === 5) { r += 5; } else if (y === 5 && z !== 5) { r -= 5; }
  if (x === 6) { r += 6; } else if (y === 6 && z !== 6) { r -= 6; }
  if (x === 7) { r += 7; } else if (y === 7 && z !== 7) { r -= 7; }
  if (x === 8) { r += 8; } else if (y === 8 && z !== 8) { r -= 8; }
  if (x === 9) { r += 9; } else if (y === 9 && z !== 9) { r -= 9; }
  if (x === 10) { r += 10; } else if (y === 10 && z !== 10) { r -= 10; }
  if (x === 11) { r += 11; } else if (y === 11 && z !== 11) { r -= 11; }
  if (x === 12) { r += 12; } else if (y === 12 && z !== 12) { r -= 12; }
  if (x === 13) { r += 13; } else if (y === 13 && z !== 13) { r -= 13; }
  if (x === 14) { r += 14; } else if (y === 14 && z !== 14) { r -= 14; }
  if (x === 15) { r += 15; } else if (y === 15 && z !== 15) { r -= 15; }
  if (x === 16) { r += 16; } else if (y === 16 && z !== 16) { r -= 16; }
  if (x === 17) { r += 17; } else if (y === 17 && z !== 17) { r -= 17; }
  return r;
}
