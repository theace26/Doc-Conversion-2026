/* UI telemetry — fire-and-forget POST /api/telemetry.
 * Spec §13. Failures are logged but never block UI.
 *
 * Usage:
 *   MFTelemetry.emit('ui.layout_mode_selected', { mode: 'minimal' });
 *
 * Safe DOM: this module touches no DOM.
 */
(function (global) {
  'use strict';

  var ENDPOINT = '/api/telemetry';

  function emit(event, props) {
    if (typeof event !== 'string' || event.indexOf('ui.') !== 0) {
      console.warn('mf-telemetry: ignored non-ui event:', event);
      return;
    }
    var body = JSON.stringify({ event: event, props: props || {} });
    try {
      // sendBeacon is best-effort and survives page unload.
      if (navigator.sendBeacon) {
        var blob = new Blob([body], { type: 'application/json' });
        navigator.sendBeacon(ENDPOINT, blob);
        return;
      }
    } catch (e) { /* fall through to fetch */ }
    fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body,
      credentials: 'same-origin',
      keepalive: true
    }).catch(function (e) {
      console.warn('mf-telemetry: emit failed', e);
    });
  }

  global.MFTelemetry = { emit: emit };
})(window);
