export function a() {
  try {
    JSON.parse('{');
  // GT:ts_empty_catch|empty-catch|CWE-NA|yes
  } catch (e) {}
}
