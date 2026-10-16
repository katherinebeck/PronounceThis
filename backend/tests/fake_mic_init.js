(() => {
  const orig = navigator.mediaDevices && navigator.mediaDevices.getUserMedia ? navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices) : null;
  navigator.mediaDevices.getUserMedia = async (c) => {
    if (!c || !c.audio) return orig(c);
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    await ctx.resume();
    const dest = ctx.createMediaStreamDestination();
    const bin = atob(window.__fakeB64 || "");
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    const buf = await ctx.decodeAudioData(u8.buffer);
    window.__fakeDur = buf.duration;
    setTimeout(() => { const s = ctx.createBufferSource(); s.buffer = buf; s.connect(dest); s.start(); }, 400);
    return dest.stream;
  };
})();
