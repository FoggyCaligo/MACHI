(() => {
  "use strict";

  const TARGET_SAMPLE_RATE = 16000;
  const SPEECH_THRESHOLD = 0.018;
  const SILENCE_TO_SEND_MS = 900;
  const MIN_UTTERANCE_MS = 350;
  const MAX_UTTERANCE_MS = 18000;
  const PRE_ROLL_MS = 280;

  const $attachBtn = document.getElementById("attach-btn");
  const $sendBtn = document.getElementById("send-btn");
  const $msgInput = document.getElementById("msg-input");
  const $messages = document.getElementById("messages");
  if (!$attachBtn || !$sendBtn || !$msgInput || !$messages) return;

  const $voiceBtn = document.createElement("button");
  $voiceBtn.id = "voice-mode-btn";
  $voiceBtn.type = "button";
  $voiceBtn.textContent = "🎙️";
  $voiceBtn.title = "음성 모드 확인 중...";
  $voiceBtn.disabled = true;
  $attachBtn.parentElement?.insertBefore($voiceBtn, $attachBtn);

  const state = {
    ready: false,
    prepared: false,
    preparing: false,
    enabled: false,
    busy: false,
    speaking: false,
    stream: null,
    context: null,
    source: null,
    processor: null,
    buffers: [],
    preRoll: [],
    preRollMs: 0,
    speechActive: false,
    utteranceMs: 0,
    silenceMs: 0,
    playback: null,
    playbackUrl: null,
  };

  loadVoiceStatus();

  async function loadVoiceStatus() {
    try {
      const res = await fetch("/voice/status");
      if (!res.ok) throw new Error(`voice status ${res.status}`);
      const data = await res.json();
      state.ready = Boolean(data.ready);
      state.prepared = Boolean(data.prepared);
      $voiceBtn.disabled = !state.ready;
      if (state.ready) {
        $voiceBtn.title = state.prepared
          ? "음성 대화 모드 켜기"
          : "음성 대화 모드 켜기 — 첫 실행 시 모델을 자동 설치합니다";
      } else {
        const missing = [];
        if (!data.stt_library_available) missing.push("faster-whisper");
        if (!data.tts_library_available) missing.push("piper-tts");
        if (!data.stt_configured) missing.push("STT 모델");
        if (!data.tts_configured) missing.push("TTS 모델");
        $voiceBtn.title = `로컬 음성 준비 필요: ${missing.join(" + ")}`;
      }
    } catch (err) {
      state.ready = false;
      $voiceBtn.disabled = true;
      $voiceBtn.title = "음성 상태를 확인할 수 없습니다";
      console.warn("MK4 voice status failed", err);
    }
  }

  $voiceBtn.addEventListener("click", async () => {
    if (!state.ready || state.preparing) return;
    if (state.enabled) {
      await disableVoiceMode();
    } else {
      await enableVoiceMode();
    }
  });

  async function prepareVoiceModels() {
    if (state.prepared) return;
    state.preparing = true;
    updateButtonState();
    try {
      const res = await fetch("/voice/prepare", { method: "POST" });
      const raw = await res.text();
      let data = {};
      try { data = raw ? JSON.parse(raw) : {}; } catch (_) { data = {}; }
      if (!res.ok || !data.ok) throw new Error(data.message || "음성 모델 준비 실패");
      state.prepared = Boolean(data.prepared);
      if (!state.prepared) throw new Error("음성 모델 준비가 완료되지 않았습니다.");
    } finally {
      state.preparing = false;
      updateButtonState();
    }
  }

  async function enableVoiceMode() {
    try {
      await prepareVoiceModels();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextCtor) throw new Error("이 브라우저는 AudioContext를 지원하지 않습니다.");

      const context = new AudioContextCtor();
      if (context.state === "suspended") await context.resume();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);

      state.stream = stream;
      state.context = context;
      state.source = source;
      state.processor = processor;
      state.enabled = true;
      resetVad();

      processor.onaudioprocess = onAudioProcess;
      source.connect(processor);
      processor.connect(context.destination);
      updateButtonState();
    } catch (err) {
      await disableVoiceMode();
      $voiceBtn.title = err?.message || "마이크를 시작할 수 없습니다";
      console.warn("MK4 voice enable failed", err);
    }
  }

  async function disableVoiceMode() {
    state.enabled = false;
    state.busy = false;
    state.speaking = false;
    resetVad();

    if (state.playback) {
      try { state.playback.pause(); } catch (_) {}
      state.playback = null;
    }
    if (state.playbackUrl) {
      URL.revokeObjectURL(state.playbackUrl);
      state.playbackUrl = null;
    }
    if (state.processor) {
      state.processor.onaudioprocess = null;
      try { state.processor.disconnect(); } catch (_) {}
      state.processor = null;
    }
    if (state.source) {
      try { state.source.disconnect(); } catch (_) {}
      state.source = null;
    }
    if (state.stream) {
      state.stream.getTracks().forEach((track) => track.stop());
      state.stream = null;
    }
    if (state.context) {
      try { await state.context.close(); } catch (_) {}
      state.context = null;
    }
    updateButtonState();
  }

  function onAudioProcess(event) {
    if (!state.enabled || state.busy || state.speaking || $sendBtn.disabled) {
      resetVad();
      return;
    }

    const input = event.inputBuffer.getChannelData(0);
    const chunk = new Float32Array(input);
    const chunkMs = (chunk.length / event.inputBuffer.sampleRate) * 1000;
    const rms = rootMeanSquare(chunk);

    const output = event.outputBuffer.getChannelData(0);
    output.fill(0);

    if (!state.speechActive) {
      pushPreRoll(chunk, chunkMs);
      if (rms >= SPEECH_THRESHOLD) {
        state.speechActive = true;
        state.buffers = [...state.preRoll, chunk];
        state.utteranceMs = state.preRollMs + chunkMs;
        state.silenceMs = 0;
        state.preRoll = [];
        state.preRollMs = 0;
      }
      return;
    }

    state.buffers.push(chunk);
    state.utteranceMs += chunkMs;
    if (rms >= SPEECH_THRESHOLD) {
      state.silenceMs = 0;
    } else {
      state.silenceMs += chunkMs;
    }

    if (
      state.utteranceMs >= MAX_UTTERANCE_MS ||
      (state.utteranceMs >= MIN_UTTERANCE_MS && state.silenceMs >= SILENCE_TO_SEND_MS)
    ) {
      const buffers = state.buffers;
      const inputRate = event.inputBuffer.sampleRate;
      resetVad();
      processUtterance(buffers, inputRate);
    }
  }

  function pushPreRoll(chunk, chunkMs) {
    state.preRoll.push(chunk);
    state.preRollMs += chunkMs;
    while (state.preRoll.length > 1 && state.preRollMs > PRE_ROLL_MS) {
      const removed = state.preRoll.shift();
      state.preRollMs -= (removed.length / state.context.sampleRate) * 1000;
    }
  }

  function resetVad() {
    state.buffers = [];
    state.preRoll = [];
    state.preRollMs = 0;
    state.speechActive = false;
    state.utteranceMs = 0;
    state.silenceMs = 0;
  }

  async function processUtterance(buffers, inputRate) {
    if (!state.enabled || state.busy || !buffers.length) return;
    state.busy = true;
    updateButtonState();
    try {
      const merged = mergeFloat32(buffers);
      const downsampled = downsample(merged, inputRate, TARGET_SAMPLE_RATE);
      const wav = encodeWav(downsampled, TARGET_SAMPLE_RATE);
      const form = new FormData();
      form.append("file", new Blob([wav], { type: "audio/wav" }), "speech.wav");
      const res = await fetch("/voice/stt", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.message || "STT 변환 실패");
      const text = String(data.text || "").trim();
      if (!text) throw new Error("STT 결과가 비어 있습니다.");

      $msgInput.value = text;
      $msgInput.dispatchEvent(new Event("input", { bubbles: true }));
      $sendBtn.click();
      waitForChatIdleFallback();
    } catch (err) {
      console.warn("MK4 voice STT failed", err);
      state.busy = false;
      updateButtonState();
    }
  }

  async function waitForChatIdleFallback() {
    const deadline = Date.now() + 180000;
    while (state.enabled && Date.now() < deadline) {
      await sleep(250);
      if (!$sendBtn.disabled && !state.speaking) {
        state.busy = false;
        updateButtonState();
        return;
      }
    }
    if (!state.speaking) {
      state.busy = false;
      updateButtonState();
    }
  }

  const observer = new MutationObserver((records) => {
    if (!state.enabled) return;
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (!(node instanceof HTMLElement)) continue;
        const row = node.matches(".msg-row.MK4") ? node : node.querySelector?.(".msg-row.MK4");
        if (!row) continue;
        const text = row.querySelector(".bubble-text")?.textContent?.trim();
        if (text) speakAssistantText(text);
      }
    }
  });
  observer.observe($messages, { childList: true, subtree: false });

  async function speakAssistantText(text) {
    if (!state.enabled || !text) return;
    state.busy = true;
    state.speaking = true;
    resetVad();
    updateButtonState();
    try {
      const res = await fetch("/voice/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) {
        let message = "TTS 변환 실패";
        try {
          const data = await res.json();
          message = data.message || message;
        } catch (_) {}
        throw new Error(message);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      state.playback = audio;
      state.playbackUrl = url;
      await new Promise((resolve, reject) => {
        audio.addEventListener("ended", resolve, { once: true });
        audio.addEventListener("error", () => reject(new Error("TTS 오디오 재생 실패")), { once: true });
        audio.play().catch(reject);
      });
    } catch (err) {
      console.warn("MK4 voice TTS failed", err);
    } finally {
      if (state.playbackUrl) URL.revokeObjectURL(state.playbackUrl);
      state.playbackUrl = null;
      state.playback = null;
      state.speaking = false;
      await sleep(250);
      state.busy = false;
      resetVad();
      updateButtonState();
    }
  }

  function updateButtonState() {
    $voiceBtn.classList.toggle("active", state.enabled);
    $voiceBtn.classList.toggle("busy", state.preparing || (state.enabled && state.busy && !state.speaking));
    $voiceBtn.classList.toggle("speaking", state.enabled && state.speaking);
    $voiceBtn.disabled = !state.ready || state.preparing;
    if (state.preparing) {
      $voiceBtn.title = "음성 모델을 처음 설치하고 있습니다...";
    } else if (!state.enabled) {
      $voiceBtn.title = state.ready
        ? (state.prepared ? "음성 대화 모드 켜기" : "음성 대화 모드 켜기 — 첫 실행 시 모델을 자동 설치합니다")
        : $voiceBtn.title;
    } else if (state.speaking) {
      $voiceBtn.title = "MK4가 말하는 중 — 클릭하면 음성 모드 종료";
    } else if (state.busy) {
      $voiceBtn.title = "음성을 처리하는 중 — 클릭하면 음성 모드 종료";
    } else {
      $voiceBtn.title = "듣는 중 — 클릭하면 음성 모드 종료";
    }
  }

  function rootMeanSquare(samples) {
    let sum = 0;
    for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
    return Math.sqrt(sum / Math.max(1, samples.length));
  }

  function mergeFloat32(buffers) {
    const total = buffers.reduce((sum, item) => sum + item.length, 0);
    const merged = new Float32Array(total);
    let offset = 0;
    buffers.forEach((item) => {
      merged.set(item, offset);
      offset += item.length;
    });
    return merged;
  }

  function downsample(buffer, inputRate, outputRate) {
    if (outputRate >= inputRate) return buffer;
    const ratio = inputRate / outputRate;
    const outputLength = Math.round(buffer.length / ratio);
    const output = new Float32Array(outputLength);
    for (let i = 0; i < outputLength; i += 1) {
      const start = Math.floor(i * ratio);
      const end = Math.min(buffer.length, Math.floor((i + 1) * ratio));
      let sum = 0;
      let count = 0;
      for (let j = start; j < end; j += 1) {
        sum += buffer[j];
        count += 1;
      }
      output[i] = count ? sum / count : 0;
    }
    return output;
  }

  function encodeWav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    writeAscii(view, 0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeAscii(view, 8, "WAVE");
    writeAscii(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeAscii(view, 36, "data");
    view.setUint32(40, samples.length * 2, true);
    let offset = 44;
    for (let i = 0; i < samples.length; i += 1) {
      const sample = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += 2;
    }
    return buffer;
  }

  function writeAscii(view, offset, text) {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  window.MK4Voice = {
    enable: enableVoiceMode,
    disable: disableVoiceMode,
    get enabled() { return state.enabled; },
    get prepared() { return state.prepared; },
  };
})();
