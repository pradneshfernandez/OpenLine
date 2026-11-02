/* A browser "phone line" to OpenLine's /ws, speaking Twilio's media-stream protocol.
 *
 * The mic is band-limited to 300–3400 Hz, resampled to 8 kHz and mu-law encoded in 20 ms frames;
 * the agent's audio comes back the same way, and a "clear" (barge-in) drops what's queued. Used by
 * /phone-sim and /demo.
 *
 *   const line = await PhoneLine.dial({ interviewId, callSid, dsp: true, lossPercent: () => 0,
 *                                       onLevel: (who, peak) => {}, onOpen: () => {}, onClose: (why) => {} });
 *   line.hangUp();
 */
(() => {
const RATE = 8000, FRAME = 160;  // 20 ms of 8 kHz, as Twilio sends

// ---- mu-law (G.711) ----
function linToUlaw(s) {  // s: int16; same algorithm as CPython's audioop.lin2ulaw (14-bit G.711)
  s >>= 2;
  let mask = 0xff;
  if (s < 0) { s = -s; mask = 0x7f; }
  if (s > 8159) s = 8159;
  s += 0x21;
  let seg = 0;
  for (let end = 0x3f; seg < 8 && s > end; seg++, end = (end << 1) | 1);
  if (seg >= 8) return 0x7f ^ mask;
  return ((seg << 4) | ((s >> (seg + 1)) & 0x0f)) ^ mask;
}
const ULAW_TABLE = new Int16Array(256).map((_, u) => {
  u = ~u & 0xff;
  const sign = u & 0x80, exp = (u >> 4) & 7, mant = u & 0x0f;
  const s = (((mant << 3) + 0x84) << exp) - 0x84;
  return sign ? -s : s;
});
const b64 = (bytes) => { let s = ""; for (const b of bytes) s += String.fromCharCode(b); return btoa(s); };
const unb64 = (str) => Uint8Array.from(atob(str), (c) => c.charCodeAt(0));

// ---- audio worklets: uplink (ctx rate -> 8 kHz frames), downlink (8 kHz -> ctx rate) ----
const WORKLET = `
class Uplink extends AudioWorkletProcessor {
  constructor() { super(); this.step = sampleRate / ${RATE}; this.pos = 0; this.prev = 0; this.buf = new Float32Array(${FRAME}); this.n = 0; }
  process(inputs) {
    const x = inputs[0][0];
    if (!x) return true;
    // Input is already low-passed at 3.4 kHz, so linear interpolation is enough to decimate.
    for (let i = 0; i < x.length; i++) {
      while (this.pos <= i) {
        const a = this.pos - (i - 1), s0 = i === 0 ? this.prev : x[i - 1];
        this.buf[this.n++] = s0 + (x[i] - s0) * a;
        if (this.n === ${FRAME}) { this.port.postMessage(this.buf.slice()); this.n = 0; }
        this.pos += this.step;
      }
    }
    this.pos -= x.length; this.prev = x[x.length - 1];
    return true;
  }
}
class Downlink extends AudioWorkletProcessor {
  constructor() {
    super(); this.step = ${RATE} / sampleRate; this.q = []; this.cur = null; this.ci = 0; this.frac = 0; this.last = 0;
    this.port.onmessage = (e) => { if (e.data === "clear") { this.q = []; this.cur = null; } else this.q.push(e.data); };
  }
  next() { if (this.cur && this.ci < this.cur.length) return this.cur[this.ci++]; this.cur = this.q.shift() || null; this.ci = 0; return this.cur ? this.cur[this.ci++] : 0; }
  process(_, outputs) {
    const out = outputs[0][0];
    for (let i = 0; i < out.length; i++) {
      this.frac += this.step;
      while (this.frac >= 1) { this.last = this.next(); this.frac -= 1; }
      out[i] = this.last;
    }
    return true;
  }
}
registerProcessor("uplink", Uplink);
registerProcessor("downlink", Downlink);`;

async function dial({ interviewId, callSid, dsp = true, lossPercent = () => 0,
                      onLevel = () => {}, onOpen = () => {}, onClose = () => {} }) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: {
    channelCount: 1, echoCancellation: dsp, noiseSuppression: dsp, autoGainControl: dsp } });
  const ctx = new AudioContext();
  await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" })));

  // Telephone band: 300–3400 Hz, two poles each side.
  const src = ctx.createMediaStreamSource(stream);
  const filt = (type, frequency) => new BiquadFilterNode(ctx, { type, frequency });
  const up = new AudioWorkletNode(ctx, "uplink");
  const down = new AudioWorkletNode(ctx, "downlink");
  src.connect(filt("highpass", 300)).connect(filt("highpass", 300)).connect(filt("lowpass", 3400))
     .connect(filt("lowpass", 3400)).connect(up);
  down.connect(filt("lowpass", 3400)).connect(ctx.destination);

  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  const sid = "MZsim" + interviewId;
  let seq = 1, started = false, closed = false;

  const finish = (why) => {
    if (closed) return;
    closed = true;
    if (ws.readyState === 1) { try { ws.send(JSON.stringify({ event: "stop", streamSid: sid })); } catch {} ws.close(); }
    stream.getTracks().forEach((t) => t.stop());
    ctx.close();
    onLevel("you", 0); onLevel("agent", 0);
    onClose(why);
  };

  ws.onopen = () => {
    ws.send(JSON.stringify({ event: "connected", protocol: "Call", version: "1.0.0" }));
    ws.send(JSON.stringify({ event: "start", sequenceNumber: String(seq++), streamSid: sid, start: {
      streamSid: sid, accountSid: "ACsim", callSid, tracks: ["inbound"],
      mediaFormat: { encoding: "audio/x-mulaw", sampleRate: RATE, channels: 1 },
      customParameters: { interview_id: String(interviewId) } } }));
    started = true;
    onOpen();
  };

  up.port.onmessage = (e) => {
    if (!started || ws.readyState !== 1) return;
    const f = e.data, bytes = new Uint8Array(FRAME);
    let peak = 0;
    const lost = Math.random() * 100 < lossPercent();  // a lost packet arrives as silence
    for (let i = 0; i < FRAME; i++) {
      const v = lost ? 0 : Math.max(-1, Math.min(1, f[i]));
      peak = Math.max(peak, Math.abs(v));
      bytes[i] = linToUlaw(Math.round(v * 32767));
    }
    onLevel("you", peak);
    ws.send(JSON.stringify({ event: "media", streamSid: sid, sequenceNumber: String(seq++),
      media: { track: "inbound", payload: b64(bytes) } }));
  };

  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.event === "media") {
      const u = unb64(m.media.payload), f = new Float32Array(u.length);
      let peak = 0;
      for (let i = 0; i < u.length; i++) { f[i] = ULAW_TABLE[u[i]] / 32768; peak = Math.max(peak, Math.abs(f[i])); }
      onLevel("agent", peak);
      down.port.postMessage(f, [f.buffer]);
    } else if (m.event === "clear") {
      down.port.postMessage("clear");  // barge-in: drop queued agent audio, like Twilio does
    }
  };
  ws.onclose = () => finish("ended");
  ws.onerror = () => finish("error");
  return { hangUp: () => finish("hung up") };
}

window.PhoneLine = { dial, linToUlaw, ULAW_TABLE };
})();
