/* Apply the saved theme before first paint, without an inline CSP exception. */
(function () {
  var preference = 'system';
  try { var saved = localStorage.getItem('filament-manager-theme');
    if (saved === 'light' || saved === 'dark') preference = saved;
  } catch (_) { /* Storage can be blocked. */ }
  var dark = preference === 'dark' || (preference === 'system' &&
    typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
}());
