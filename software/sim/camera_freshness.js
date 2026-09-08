// Time is local monotonic time; no synchronized Pi/Jetson clock is assumed.
class CameraFreshness {
  constructor(limitMs = 500) {
    this.limitMs = limitMs;
    this.frameId = null;
    this.receivedAt = null;
    this.ageAtReceipt = null;
    this.error = null;
  }

  accept(id, age, now, requestMs) {
    if (id == null || age == null || id === '' || age === '' ||
        !Number.isSafeInteger(Number(id)) || Number(id) < 0 ||
        !Number.isFinite(Number(age)) || Number(age) < 0) {
      this.fail('Missing frame metadata');
      return;
    }
    let ageMs = Number(age) + Math.max(0, requestMs);
    if (Number(id) === this.frameId) {
      ageMs = Math.max(ageMs, this.ageAtReceipt + Math.max(0, now - this.receivedAt));
    }
    this.frameId = Number(id);
    this.ageAtReceipt = ageMs;
    this.receivedAt = now;
    this.error = null;
  }

  fail(message) { this.error = message; }

  snapshot(now) {
    const ageMs = this.receivedAt === null ? null :
      this.ageAtReceipt + Math.max(0, now - this.receivedAt);
    const fresh = ageMs !== null && ageMs <= this.limitMs && !this.error;
    return {
      state: fresh ? 'live' : this.receivedAt === null ? 'unavailable' : 'stale',
      frameId: this.frameId, ageMs,
      reason: this.error || (fresh ? '' : 'No fresh frame'),
    };
  }
}
if (typeof module !== 'undefined') module.exports = {CameraFreshness};
