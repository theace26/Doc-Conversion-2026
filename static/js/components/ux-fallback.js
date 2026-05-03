/* MFNewUxFallback — call from original-only pages to auto-flip the use_new_ux
 * pref when the user lands here from new-UX context. Prevents the toggle in
 * Display Preferences from claiming "new UX" while showing original-UX content.
 *
 * How it works:
 *   1. If the loaded MFPrefs reports use_new_ux === true, flip it to false.
 *   2. Set the mf_use_new_ux=0 cookie immediately so the NEXT navigation is
 *      correctly dispatched server-side (no stale-cookie bounce).
 *   3. Show a brief toast explaining the switch (uses mf-toast styles from
 *      markflow.css if present; silently swallowed if not).
 *
 * Usage (add at the END of <body>, after app.js / MFPrefs is loaded):
 *
 *   <script src="/static/js/components/ux-fallback.js"></script>
 *   <script>MFNewUxFallback.flag()</script>
 *
 * The call can be made immediately after the script tag because MFPrefs is
 * loaded synchronously by app.js. If MFPrefs hasn't loaded yet (rare race),
 * the call is a no-op and the pref remains unchanged.
 *
 * Safe DOM throughout — no innerHTML used for arbitrary content.
 */
(function (global) {
  'use strict';

  /**
   * flag([reason])
   *
   * If the current user has use_new_ux === true, resets it to false and sets
   * the mf_use_new_ux=0 cookie so the server dispatches to original UX on the
   * next navigation. Shows an optional toast with `reason`.
   *
   * @param {string} [reason] - Human-readable explanation for the toast.
   *   Defaults to a generic "not available in the new UI yet" message.
   */
  function flag(reason) {
    // Guard: MFPrefs must be loaded and the user must actually have new UX on.
    if (!global.MFPrefs || typeof global.MFPrefs.get !== 'function') return;
    if (global.MFPrefs.get('use_new_ux') !== true) return;

    // Flip the pref.
    global.MFPrefs.set('use_new_ux', false);
    if (typeof global.MFPrefs.flush === 'function') global.MFPrefs.flush();

    // Set the cookie immediately so the NEXT request uses the updated value.
    // (MFPrefs.set triggers syncAttrs which calls syncUxCookie, but in case
    // the browser blocks cookie writes from within the prefs module we do it
    // here too as a belt-and-suspenders.)
    try {
      document.cookie = 'mf_use_new_ux=0; path=/; Max-Age=31536000; SameSite=Lax';
    } catch (e) { /* storage blocked — non-fatal */ }

    // Toast: only rendered if mf-toast styles are present (markflow.css).
    try {
      var msg = reason || "This page isn’t available in the new UI yet. Switched back to original UI.";
      var t = document.createElement('div');
      t.className = 'mf-toast mf-toast--info';
      t.textContent = msg;
      document.body.appendChild(t);
      // Trigger visible state on next frame so the CSS transition fires.
      requestAnimationFrame(function () {
        t.classList.add('mf-toast--visible');
      });
      setTimeout(function () {
        t.classList.remove('mf-toast--visible');
        setTimeout(function () {
          if (t.parentNode) t.parentNode.removeChild(t);
        }, 350);
      }, 3500);
    } catch (e) { /* toast styles absent or DOM not ready — non-fatal */ }
  }

  global.MFNewUxFallback = { flag: flag };
})(window);
