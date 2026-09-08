// Serialize manual commands and invalidate pending starts on release.
class ManualDrive {
  constructor(disarm, send, onError = () => {}) {
    this.disarm = disarm;
    this.send = send;
    this.onError = onError;
    this.generation = 0;
    this.active = false;
    this.timer = null;
    this.inFlight = null;
    this.stopping = null;
  }

  async start(motion, throttle) {
    if (this.active) return;
    this.active = true;
    const generation = ++this.generation;
    try {
      if (this.stopping) await this.stopping;
      if (!this.active || generation !== this.generation) return;
      await this.disarm();
      if (!this.active || generation !== this.generation) return;
      await this.tick(generation, motion, throttle);
    } catch (error) {
      this.onError(error);
      if (generation === this.generation) await this.stop();
    }
  }

  async tick(generation, motion, throttle) {
    if (!this.active || generation !== this.generation) return;
    try {
      const request = Promise.resolve().then(() => this.send(motion, throttle));
      this.inFlight = request;
      await request;
      if (this.inFlight === request) this.inFlight = null;
      if (this.active && generation === this.generation) {
        this.timer = setTimeout(() => this.tick(generation, motion, throttle), 100);
      }
    } catch (error) {
      this.onError(error);
      if (generation === this.generation) await this.stop();
    }
  }

  stop() {
    this.active = false;
    ++this.generation;
    clearTimeout(this.timer);
    this.timer = null;
    if (this.stopping) return this.stopping;
    const pending = this.inFlight;
    this.stopping = (async () => {
      try { await this.send('stop', 0); } catch (error) { this.onError(error); }
      // A previously transmitted action may arrive after the first STOP.
      if (pending) {
        try { await pending; } catch {}
        try { await this.send('stop', 0); } catch (error) { this.onError(error); }
      }
    })().finally(() => { this.stopping = null; });
    return this.stopping;
  }
}
if (typeof module !== 'undefined') module.exports = {ManualDrive};
