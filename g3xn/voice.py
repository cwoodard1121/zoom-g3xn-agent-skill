"""Push to talk: hold a footswitch (or the button in the app), say it, let go.

The words come from one of two microphones:

    laptop  the computer's own microphone, recorded here from press to release
    phone   a paired phone that records while the switch is held and sends the audio
            to POST /api/talk/audio when it's let go (phones only allow the microphone
            over HTTPS, so this goes through Tailscale)

Speech becomes text on this computer with faster-whisper (no audio leaves it), and the
text goes to Claude. Each step is an event for the app's talk sheet:

    {"type": "talk", "state": "listening", "mic": "laptop"}
    {"type": "talk", "state": "transcribing"}
    {"type": "talk", "state": "heard", "text": "more gain on the solo"}
    {"type": "talk", "state": "idle", "problem": "..."}       (nothing heard, or it failed)

faster-whisper and sounddevice are the `voice` extra; the speech model (about 145 MB
for base.en) downloads from Hugging Face the first time it's used.
"""
import io
import threading

SAMPLE_RATE = 16000
MICS = ("laptop", "phone")
MODEL = "base.en"
SHORTEST = 0.3              # seconds; a tap shorter than this is ignored
PHONE_WAIT = 20.0           # seconds to wait for a phone's recording after the switch comes up


class LaptopMic:
    """Records a microphone on this computer (`device`: its name; None = the system default)
    from start() to stop()."""

    def __init__(self, device=None):
        self.device = device
        self._chunks, self._stream = [], None

    def start(self):
        import sounddevice
        self._chunks = []
        self._stream = sounddevice.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                               device=self.device,
                                               callback=lambda data, *_: self._chunks.append(data.copy()))
        self._stream.start()

    def stop(self):
        """The recording, as 16 kHz mono float32 samples."""
        import numpy
        stream, self._stream = self._stream, None
        if stream:
            stream.stop()
            stream.close()
        return numpy.concatenate(self._chunks)[:, 0] if self._chunks else numpy.zeros(0, "float32")


class Whisper:
    """Speech to text with faster-whisper, loaded the first time it's needed."""

    def __init__(self, model=MODEL):
        self.model_name, self._model = model, None
        self._lock = threading.Lock()

    def __call__(self, audio):
        """audio: float32 samples at 16 kHz, or the bytes of an audio file (webm, ogg, wav...)."""
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            source = io.BytesIO(audio) if isinstance(audio, (bytes, bytearray)) else audio
            segments, _ = self._model.transcribe(source, language="en", beam_size=1, vad_filter=True)
            return " ".join(s.text.strip() for s in segments).strip()


def microphones():
    """The names of this computer's microphones ([] without sounddevice)."""
    try:
        import sounddevice
        default_api = sounddevice.default.hostapi
        return sorted({d["name"] for d in sounddevice.query_devices()
                       if d["max_input_channels"] > 0 and d["hostapi"] == default_api
                       and "Sound Mapper" not in d["name"]})
    except Exception:          # not installed, or no audio system
        return []


def voice_installed():
    try:
        import faster_whisper  # noqa: F401
        import sounddevice  # noqa: F401
        return True
    except (ImportError, OSError):
        return False


class Talk:
    def __init__(self, emit, send, mic="laptop", recorder=None, transcribe=None):
        """emit(event): tell the app. send(text): give the words to Claude.
        recorder / transcribe: the laptop mic and speech-to-text (tests pass fakes)."""
        self.emit, self.send = emit, send
        self.mic = check_mic(mic)
        self.recorder = recorder or LaptopMic()
        self.transcribe = transcribe or Whisper()
        self.state = "idle"
        self._working = False
        self._lock = threading.Lock()

    def info(self):
        return {"mic": self.mic, "state": self.state, "installed": voice_installed(),
                "input": getattr(self.recorder, "device", None), "inputs": microphones()}

    def set_input(self, name):
        """Which of this computer's microphones to record (None = the system default)."""
        if name is not None and name not in microphones():
            raise ValueError("there's no microphone called %r on this computer" % name)
        self.recorder.device = name
        return self.info()

    def set_mic(self, mic):
        self.mic = check_mic(mic)
        return self.info()

    def press(self):
        """The talk switch went down: start listening."""
        with self._lock:
            if self.state != "idle":
                return
            if self.mic == "laptop":
                try:
                    self.recorder.start()
                except Exception as err:                  # no microphone, no sounddevice
                    self._idle("Can't use the laptop microphone: %s" % err)
                    return
            self._set("listening", mic=self.mic)

    def release(self):
        """The talk switch came up: the laptop recording goes to be transcribed now; a
        phone's arrives by itself through audio()."""
        with self._lock:
            if self.state != "listening":
                return
            if self.mic == "phone":
                self._set("transcribing")
                waiting = threading.Timer(PHONE_WAIT, self._phone_silent)
                waiting.daemon = True
                waiting.start()
                return
            try:
                audio = self.recorder.stop()
            except Exception as err:
                self._idle("The recording failed: %s" % err)
                return
            self._set("transcribing")
        if len(audio) < SHORTEST * SAMPLE_RATE:
            self._idle("That was too short to hear anything.")
            return
        threading.Thread(target=self._understand, args=(audio,), name="g3xn-talk", daemon=True).start()

    def audio(self, data):
        """A recording sent by a phone (or by the app). Returns once the words are known."""
        if not data:
            raise ValueError("no audio arrived")
        with self._lock:
            self._set("transcribing")
        return self._understand(bytes(data))

    def _phone_silent(self):
        with self._lock:
            if self.state == "transcribing" and not self._working:
                self._idle("No audio came from the phone. Is the g3xn page open on it?")

    def _understand(self, audio):
        self._working = True
        try:
            return self._understand_now(audio)
        finally:
            self._working = False

    def _understand_now(self, audio):
        try:
            text = self.transcribe(audio)
        except Exception as err:
            self._idle("Couldn't turn that into words: %s" % err)
            return None
        if not text:
            self._idle("Didn't catch anything. Hold the switch and try again.")
            return None
        self._set("heard", text=text)
        try:
            self.send(text)
        except Exception as err:
            self._idle("Claude couldn't take it: %s" % err)
            return text
        self._set("idle")
        return text

    def _set(self, state, **more):
        self.state = state
        self.emit(dict({"type": "talk", "state": state}, **more))

    def _idle(self, problem):
        self._set("idle", problem=problem)


def check_mic(mic):
    if mic not in MICS:
        raise ValueError("mic must be one of %s" % ", ".join(MICS))
    return mic
