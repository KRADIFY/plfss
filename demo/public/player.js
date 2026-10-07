/* Playback and cancellation are independent of the visual tour library. */
(function (root) {
  'use strict';
  class DemoPlayer {
    constructor({steps, voice, onStep, onState = () => {}, onExit = () => {}, onVoiceError = () => {}, clock}) {
      this.steps = steps; this.voice = voice; this.onStep = onStep; this.onState = onState;
      this.onExit = onExit; this.onVoiceError = onVoiceError;
      this.clock = clock || {now: () => Date.now(), set: (fn, ms) => setTimeout(fn, ms), clear: id => clearTimeout(id)};
      this.status = 'stopped'; this.index = 0; this.muted = false; this.token = 0;
      this.timer = null; this.action = null; this.remaining = 0; this.voiceActive = false;
    }
    duration() { return Math.max(6500, this.steps[this.index].text.trim().split(/\s+/).length * 390); }
    emit() { this.onState({status: this.status, index: this.index, total: this.steps.length, muted: this.muted}); }
    clearTimer() { if (this.timer !== null) this.clock.clear(this.timer); this.timer = null; }
    cancel() { this.token++; this.clearTimer(); this.action = null; this.remaining = 0; this.voiceActive = false; this.voice.cancel(); }
    schedule(ms, action) {
      this.clearTimer(); this.remaining = ms; this.action = action; this.deadline = this.clock.now() + ms;
      const token = this.token;
      if (this.status === 'playing') this.timer = this.clock.set(() => {
        if (token !== this.token || this.status !== 'playing') return;
        this.timer = null; this.action = null; this.remaining = 0; action();
      }, ms);
    }
    seek(index, playing = this.status === 'playing') {
      if (!this.steps.length) return;
      this.cancel(); this.index = Math.max(0, Math.min(index, this.steps.length - 1));
      this.status = playing ? 'playing' : 'paused';
      try { this.onStep(this.steps[this.index], this.index, this.steps.length); }
      catch (error) { this.stop(); throw error; }
      this.schedule(500, () => this.narrate()); this.emit();
    }
    narrate() {
      if (this.status !== 'playing') return;
      if (this.muted) return this.schedule(this.duration(), () => this.advance());
      const token = this.token;
      this.voiceActive = true;
      const end = () => {
        if (token !== this.token) return;
        this.voiceActive = false;
        this.schedule(1400, () => this.advance());
      };
      const error = () => {
        if (token !== this.token) return;
        this.voiceActive = false; this.onVoiceError();
        this.schedule(this.duration(), () => this.advance());
      };
      const started = this.voice.speak(this.steps[this.index].text, {end, error}, this.steps[this.index]);
      if (token !== this.token) return;
      if (!started) { error(); return; }
      if (!this.voiceActive) return;
      // A stalled speech engine cannot leave the controls permanently waiting.
      this.schedule(this.duration() * 2 + 20000, () => {
        if (token !== this.token) return;
        this.token++; this.voiceActive = false; this.voice.cancel(); this.onVoiceError();
        this.schedule(1400, () => this.advance());
      });
    }
    play() {
      if (this.status === 'playing') return;
      if (this.status === 'paused') {
        this.status = 'playing';
        if (this.voiceActive) this.voice.resume();
        this.schedule(this.remaining || 500, this.action || (() => this.narrate())); this.emit();
      } else this.seek(this.status === 'ended' ? 0 : this.index, true);
    }
    pause() {
      if (this.status !== 'playing') return;
      if (this.timer !== null) this.remaining = Math.max(0, this.deadline - this.clock.now());
      this.clearTimer(); this.status = 'paused';
      if (this.voiceActive) this.voice.pause();
      this.emit();
    }
    stop() {
      this.cancel(); this.status = 'stopped'; this.index = 0;
      this.onExit('stopped'); this.emit();
    }
    advance() {
      if (this.index < this.steps.length - 1) this.seek(this.index + 1, true);
      else { this.cancel(); this.status = 'ended'; this.onExit('ended'); this.emit(); }
    }
    next() { if (this.index < this.steps.length - 1) this.seek(this.index + 1); }
    previous() { this.seek(this.index - 1); }
    setMuted(muted) {
      this.muted = muted;
      if (this.status === 'playing' || this.status === 'paused') this.seek(this.index);
      else this.emit();
    }
    setSteps(steps) { this.stop(); this.steps = steps; this.emit(); }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = DemoPlayer;
  else root.DemoPlayer = DemoPlayer;
})(typeof window !== 'undefined' ? window : globalThis);
