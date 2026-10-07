/* Play one prepared recording per step; stale media events cannot advance a tour. */
(function (root) {
  'use strict';
  class RecordedVoice {
    constructor({createAudio, onSpeaking = () => {}}) {
      this.createAudio = createAudio; this.onSpeaking = onSpeaking; this.current = null;
    }
    detach(media) {
      for (const event of ['onplaying', 'onpause', 'onended', 'onerror']) media[event] = null;
    }
    fail(media) {
      if (this.current?.media !== media) return;
      const callbacks = this.current.callbacks;
      this.current = null; this.detach(media); media.pause(); this.onSpeaking(false);
      callbacks.error();
    }
    start(media) {
      try {
        Promise.resolve(media.play()).catch(() => this.fail(media));
      } catch (_) { this.fail(media); }
    }
    speak(recording, callbacks) {
      this.cancel();
      if (!recording?.src) return false;
      const media = this.createAudio(recording.src);
      this.current = {media, callbacks};
      media.preload = 'auto';
      media.onplaying = () => { if (this.current?.media === media) this.onSpeaking(true); };
      media.onpause = () => { if (this.current?.media === media) this.onSpeaking(false); };
      media.onerror = () => this.fail(media);
      media.onended = () => {
        if (this.current?.media !== media) return;
        this.current = null; this.detach(media); this.onSpeaking(false); callbacks.end();
      };
      this.start(media); return true;
    }
    pause() { this.current?.media.pause(); }
    resume() { if (this.current) this.start(this.current.media); }
    cancel() {
      const previous = this.current; this.current = null;
      if (previous) {
        this.detach(previous.media); previous.media.pause();
        previous.media.removeAttribute?.('src'); previous.media.load?.();
      }
      this.onSpeaking(false);
    }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = RecordedVoice;
  else root.RecordedVoice = RecordedVoice;
})(typeof window !== 'undefined' ? window : globalThis);
