# Hakim + Pipecat

STT and TTS services that let a [Pipecat](https://docs.pipecat.ai/) voice agent use Hakim for
realtime Arabic-first speech-to-text and text-to-speech.

**This integration talks directly to Hakim's public REST/WebSocket API** — the same one at
`https://tryhakim.ai/docs`. It does not depend on the `hakim` Python package; that SDK is not
published yet, so this code speaks the wire protocol itself over the `websockets` library Pipecat
already depends on.

```
.
├── README.md                  ← you are here
├── requirements.txt
├── .env.example
├── hakim_pipecat/
│   ├── __init__.py             exports HakimSTTService, HakimTTSService
│   ├── stt.py                  WSS /v1/audio/transcriptions/stream
│   ├── tts.py                  WSS /v1/audio/speech/stream
│   └── _common.py              shared auth/URL helpers
└── examples/
    ├── voice_agent_local.py     full local-audio Pipecat pipeline example
    └── smoke_test.py            connectivity check, no Pipecat dependency
```

---

## 1. Architecture

- `HakimSTTService` subclasses Pipecat's `WebsocketSTTService` and opens one persistent WebSocket
  to `WSS /v1/audio/transcriptions/stream`. Audio frames are forwarded continuously as
  `input_audio_buffer.append`; Pipecat's own VAD (not Hakim) decides when the user's turn ends —
  on `VADUserStoppedSpeakingFrame` the service sends `input_audio_buffer.commit`, and the next
  `transcription.done` becomes the finalized `TranscriptionFrame`. `transcription.delta` frames
  become `InterimTranscriptionFrame`s in the meantime.
- `HakimTTSService` subclasses Pipecat's `InterruptibleTTSService` (the base for providers with no
  mid-utterance cancel message and no word timestamps) and opens one persistent WebSocket to
  `WSS /v1/audio/speech/stream`. Each sentence Pipecat sends to `run_tts` becomes one
  `speech.create` request on the same socket — no new TCP/TLS handshake per utterance.
- Both services reconnect automatically on connection errors (inherited from Pipecat's
  `WebsocketService` base) and are `**kwargs`-transparent, so any options that base class accepts
  (e.g. `keepalive_timeout`, `stt_ttfb_timeout`) work unmodified.

Neither service depends on the Hakim SDK — only on the HTTP/WebSocket surface itself.

---

## 2. Requirements

- Python ≥ 3.10
- A Hakim API key with `stt:write` and `tts:write` scopes (Dashboard → Settings → API keys)
- `pipecat-ai` ≥ 0.0.105 (install separately — this repo does not vendor it)

```bash
pip install -r requirements.txt
# the example agent also needs an LLM plugin and its dependency:
pip install "pipecat-ai[openai]" "pipecat-ai[silero]"
```

---

## 3. Quickstart

```bash
cp .env.example .env
# fill in HAKIM_API_KEY, HAKIM_VOICE, OPENAI_API_KEY
```

Sanity-check connectivity first (isolates "Hakim reachability" from "Pipecat wiring" when
debugging):

```bash
python examples/smoke_test.py "مرحبا بالعالم"
```

Then run the full local-audio agent (talks over your machine's default microphone/speakers):

```bash
python examples/voice_agent_local.py
```

### Minimal usage

```python
from hakim_pipecat import HakimSTTService, HakimTTSService

stt = HakimSTTService(api_key=os.environ["HAKIM_API_KEY"])
tts = HakimTTSService(api_key=os.environ["HAKIM_API_KEY"], voice="cmokbc2b1001pvu39wmj61b7h")

pipeline = Pipeline([transport.input(), stt, user_aggregator, llm, tts, transport.output(), assistant_aggregator])
```

`api_key` can also be omitted and read from the `HAKIM_API_KEY` environment variable.

---

## 4. Configuration reference

### `HakimSTTService`

| Param                | Default          | Notes                                                                                 |
| -------------------- | ---------------- | ------------------------------------------------------------------------------------- |
| `api_key`            | `$HAKIM_API_KEY` |                                                                                       |
| `language`           | `Language.AR`    | Passed through `settings=HakimSTTService.Settings(language=...)` for runtime updates. |
| `input_audio_format` | `"pcm16"`        | `"pcm16" \| "opus" \| "mulaw"` — matches Pipecat's default transport audio format.    |
| `sample_rate`        | `16000`          | Must match the sample rate of frames actually sent.                                   |
| `region`             | `"auto"`         | `"auto" \| "de" \| "uae" \| "ksa"`.                                                   |
| `base_url`           | —                | Overrides `region` entirely (staging/self-hosted).                                    |
| `settings`           | —                | `HakimSTTService.Settings(timestamps=..., diarize=..., partials=...)`.                |

The model is always `hakim-arab-v2` — Hakim's Arabic-first acoustic profile, the only model this
endpoint accepts.

### `HakimTTSService`

| Param          | Default           | Notes                                                                                                              |
| -------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------ |
| `voice`        | _(required)_      | Hakim voice id or slug — Dashboard → Voices.                                                                       |
| `api_key`      | `$HAKIM_API_KEY`  |                                                                                                                    |
| `model`        | `"hakim-fast-v1"` | `"hakim-fast-v1"` (sub-120ms TTFB) \| `"hakim-v2"` (quality + non-verbal tags) \| `"hakim-v3"` (+ `voice_prompt`). |
| `cfg`          | `3.0`             | Classifier-free-guidance weight, `0.0`–`10.0`.                                                                     |
| `voice_prompt` | `None`            | Free-form voice description; only honoured on `hakim-v3`.                                                          |
| `region`       | `"auto"`          | Same as above.                                                                                                     |
| `base_url`     | —                 | Same as above.                                                                                                     |

Sample rate is fixed at 24 kHz mono PCM — the realtime endpoint's engine-native rate; it isn't
configurable on this surface.

---

## 5. Regions

Hakim runs a primary plane plus regional deployments. Pin a region if your infra is colocated with
one of them, to avoid an extra inter-region hop:

| `region=`          | Host                                       |
| ------------------ | ------------------------------------------ |
| `"auto"` (default) | `api.tryhakim.ai` — closest healthy region |
| `"de"`             | `de.api.tryhakim.ai` (Frankfurt)           |
| `"uae"`            | `uae.api.tryhakim.ai`                      |
| `"ksa"`            | `ksa.api.tryhakim.ai`                      |

`base_url` overrides the table entirely, for staging or self-hosted deployments.

---

## 6. Known limits

- **STT diarization** only works on stereo audio with one speaker per channel (e.g. call
  recordings) — mono `diarize=True` transcribes without speaker labels.
- **TTS format is locked** to PCM-S16LE @ 24 kHz mono on the streaming surface. If you need mp3 /
  opus / another sample rate, call Hakim's batch TTS HTTP endpoint directly outside Pipecat.
- **No mid-utterance cancel** — Hakim's realtime TTS has no documented "stop this utterance"
  message, so interruption is handled by reconnecting the socket (via `InterruptibleTTSService`)
  rather than cancelling in place. In practice this is only noticeable as a brief gap on barge-in.

---

## 7. Troubleshooting

| Symptom                               | Likely cause                              | Fix                                                                                                                                                                                     |
| ------------------------------------- | ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ValueError: Hakim API key not set`   | `HAKIM_API_KEY` missing/empty             | Set the env var or pass `api_key=` explicitly.                                                                                                                                          |
| Connection rejected immediately (401) | Bad/revoked API key                       | Regenerate the key in the Hakim dashboard.                                                                                                                                              |
| ... (403)                             | Key lacks `stt:write` / `tts:write` scope | Check the key's scopes in the dashboard.                                                                                                                                                |
| ... (429)                             | Rate limit hit                            | Back off; check your plan's rate limit.                                                                                                                                                 |
| STT never finalizes                   | No VAD in the pipeline                    | Hakim's STT relies on Pipecat's own VAD to send `input_audio_buffer.commit` — make sure a `vad_analyzer` (e.g. `SileroVADAnalyzer`) is wired in, as in `examples/voice_agent_local.py`. |
| Audio choppy / gaps between sentences | Each sentence opening a _new_ connection  | This shouldn't happen through `HakimTTSService` — the socket is persistent across sentences within a session.                                                                           |
| Garbled/silent audio                  | Sample rate mismatch                      | STT: confirm `sample_rate` matches what your transport actually sends. TTS: the service always requests 24 kHz — don't resample its output before your transport plays it.              |

Run `examples/smoke_test.py` first for any "no audio" / "no transcript" report — it isolates
whether the problem is network/auth (visible without Pipecat at all) or pipeline wiring.

Every Hakim response includes an `X-Request-Id` header (HTTP) or `request_id` field (WS frames) —
include it when filing a support ticket.

---

## License

MIT — see [LICENSE](./LICENSE).
