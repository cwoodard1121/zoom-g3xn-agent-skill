"""Push to talk: hold a footswitch (or the button in the app), say it, let go.

The words come from one of two microphones:

    laptop  the computer's own microphone, recorded here from press to release
    phone   a paired phone that records while the switch is held and sends the audio
            to POST /api/talk/audio when it's let go (phones only allow the microphone
            over HTTPS, so this goes through Tailscale)

Speech becomes text on this computer with faster-whisper (no audio leaves it), and the
text goes to Claude, or, while the app's stage view is open, to the stage (it follows
"chorus", "two bars behind", a line of the song, and passes anything else on to Claude).
Each step is an event for the app's talk sheet:

    {"type": "talk", "state": "listening", "mic": "laptop"}
    {"type": "talk", "state": "transcribing"}
    {"type": "talk", "state": "heard", "text": "more gain on the solo"}
    {"type": "talk", "state": "heard", "text": "chorus", "to": "stage", "n": 7}   (the stage takes it;
                                                       n counts, so saying it twice counts twice)
    {"type": "talk", "state": "idle", "problem": "..."}       (nothing heard, or it failed)

Heard words also say how long ago they started being said ("ago", seconds), from where
the speech-to-text puts the first word, so "we're at the chorus" lands where it was said
however long hearing and working it out took.

Or hands free, from this computer's mic and a phone's at once: with "Hey Claude" on, the mic
listens all the time (on this computer, for speech only; nothing is kept) for "Hey Claude", then
for what comes next: "Hey Claude, chorus" in one go, or "Hey Claude", a beat, then "less fizzy".
A phone sends what it hears to POST /api/talk/audio?wake=1. Said once, heard by both, it's
acted on once.

faster-whisper and sounddevice are the `voice` extra; the speech model (about 145 MB
for base.en) downloads from Hugging Face the first time it's used.
"""
import collections
import io
import queue
import re
import threading
import time

SAMPLE_RATE = 16000
MICS = ("laptop", "phone")
MODEL = "base.en"
SHORTEST = 0.3              # seconds; a tap shorter than this is ignored
PHONE_WAIT = 20.0           # seconds to wait for a phone's recording after the switch comes up
STAGE_HOLD = 20.0           # seconds the stage keeps the words after it last said it's open
# "Hey Claude": how speech-to-text tends to write it, and what's said after it.
WAKE = re.compile(r"\b(?:hey|hi|hay|ok|okay|yo)\W+(?:claude|claud|clod|cloud|clyde|clawed|klaud)\b\W*(.*)$", re.I)
AWAKE = 6.0                 # seconds after a bare "Hey Claude" to say the rest
SAME = 4.0                  # seconds: the same words from the other mic in this time are the same words
LEAD = 0.4                  # seconds into a recording people start talking, when there are no word times


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
        return "".join(w for w, _ in self.words(audio)).strip()

    def words(self, audio):
        """[(word, seconds into the audio it starts)]; each word but the first starts with a space."""
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            source = decode(audio) if isinstance(audio, (bytes, bytearray)) else audio
            segments, _ = self._model.transcribe(source, language="en", beam_size=1, vad_filter=True,
                                                 word_timestamps=True)
            out = [(w.word, float(w.start)) for s in segments for w in (s.words or [])]
        if out:
            out[0] = (out[0][0].lstrip(), out[0][1])
        return out


def decode(data):
    """An audio file's bytes (webm, ogg, mp4, wav...) as 16 kHz mono float32 samples. Done here, not
    by faster-whisper, whose own decoding passes PyAV an argument newer PyAVs refuse."""
    import av
    import numpy
    chunks = []
    with av.open(io.BytesIO(data), mode="r") as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(audio=0):
            chunks += [f.to_ndarray().reshape(-1) for f in resampler.resample(frame)]
        chunks += [f.to_ndarray().reshape(-1) for f in resampler.resample(None)]
    return (numpy.concatenate(chunks) if chunks else numpy.zeros(0, numpy.int16)).astype(numpy.float32) / 32768.0


def words_of(transcribe, audio):
    """The words and where each starts, or ([(text, None)]) from a speech-to-text that only gives text."""
    if hasattr(transcribe, "words"):
        return transcribe.words(audio)
    text = transcribe(audio) or ""
    return [(text, None)] if text else []


def starting(words, at):
    """Where the words from character `at` of their text start (None: not known)."""
    n = 0
    for word, start in words:
        n += len(word)
        if n > at:
            return start
    return None


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
        self._began = 0.0                   # when the switch went down (time.monotonic())
        self._awake_until = 0.0             # a bare "Hey Claude" waits for the rest until then
        self._last = ("", 0.0)              # the last words acted on hands free, and when
        self._stage_until = 0.0
        self._said = 0
        self._working = False
        self._lock = threading.Lock()

    def info(self):
        return {"mic": self.mic, "state": self.state, "installed": voice_installed(),
                "input": getattr(self.recorder, "device", None), "inputs": microphones(),
                "wake": bool(getattr(self, "_wake", None))}

    def set_input(self, name):
        """Which of this computer's microphones to record (None = the system default)."""
        if name is not None and name not in microphones():
            raise ValueError("there's no microphone called %r on this computer" % name)
        self.recorder.device = name
        if getattr(self, "_wake", None):
            self.wake(False)
            self.wake(True)
        return self.info()

    def set_mic(self, mic):
        self.mic = check_mic(mic)
        return self.info()

    def wake(self, on, listener=None):
        """Hands free: listen all the time for "Hey Claude" (laptop mic only)."""
        if on and not getattr(self, "_wake", None):
            self._wake = listener or WakeListener(self, device=getattr(self.recorder, "device", None))
            try:
                self._wake.start()
            except Exception as err:
                self._wake = None
                raise ValueError("can't listen for Hey Claude: %s" % err) from err
        elif not on and getattr(self, "_wake", None):
            self._wake.stop()
            self._wake = None
        self.emit(dict(self.info(), type="talk"))
        return self.info()

    def stage(self, open_=True):
        """The app's stage view is open (it says so again every few seconds) or has closed.
        While it's open, the words go to it instead of straight to Claude."""
        self._stage_until = time.monotonic() + STAGE_HOLD if open_ else 0.0

    def to_stage(self):
        return time.monotonic() < self._stage_until

    def said(self, text):
        """Words typed instead of spoken: on to the stage or Claude like heard ones."""
        text = (text or "").strip()
        if not text:
            raise ValueError("say something")
        self._heard(text)
        return text

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
            self._began = time.monotonic()
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

    def audio(self, data, ago=None):
        """A recording sent by a phone (or by the app), started `ago` seconds before it arrived.
        Returns once the words are known."""
        if not data:
            raise ValueError("no audio arrived")
        if ago is not None:
            self._began = time.monotonic() - ago
        with self._lock:
            self._set("transcribing")
        return self._understand(bytes(data))

    def wake_audio(self, data, ago=None):
        """What a phone heard hands free (started `ago` seconds before it arrived): acted on if
        it's "Hey Claude..." or the rest after one. Returns the words."""
        began = time.monotonic() - (ago or 0.0)
        try:
            words = words_of(self.transcribe, bytes(data))
        except Exception:
            return ""
        self.wake_heard(words, began)
        return "".join(w for w, _ in words).strip()

    def awake(self):
        return time.monotonic() < self._awake_until

    def wake_heard(self, words, began):
        """What one stretch of hands-free listening said ([(word, start)], or text), recorded from
        `began` (time.monotonic()): act on it if it's for us."""
        if isinstance(words, str):
            words = [(words, None)] if words.strip() else []
        text = "".join(w for w, _ in words)
        m = WAKE.search(text)
        if self.awake() and text.strip() and not m:          # the rest, after a bare "Hey Claude"
            self._awake_until = 0.0
            self._act(text.strip(), began, starting(words, len(text) - len(text.lstrip())))
            return
        if not m:
            return
        rest = m.group(1).strip(" .,!?")
        if rest:
            self._awake_until = 0.0
            self._act(rest, began, starting(words, m.start(1)))
        elif not self.awake():
            self._awake_until = time.monotonic() + AWAKE
            self.emit({"type": "talk", "state": "listening", "mic": "laptop", "wake": True})
            waiting = threading.Timer(AWAKE + 0.2, self._wake_silent)
            waiting.daemon = True
            waiting.start()

    def _act(self, text, began, start):
        now = time.monotonic()
        said, when = self._last
        if text.lower() == said.lower() and now - when < SAME:   # the other mic heard it too
            return
        self._last = (text, now)
        self._heard(text, now - began - (LEAD if start is None else start))

    def _wake_silent(self):
        if self._awake_until and not self.awake():
            self._awake_until = 0.0
            self.emit({"type": "talk", "state": "idle", "problem": "Didn't hear anything after \"Hey Claude\"."})

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
            words = words_of(self.transcribe, audio)
        except Exception as err:
            self._idle("Couldn't turn that into words: %s" % err)
            return None
        text = "".join(w for w, _ in words).strip()
        if not text:
            self._idle("Didn't catch anything. Hold the switch and try again.")
            return None
        start = words[0][1]
        self._heard(text, time.monotonic() - self._began - (LEAD if start is None else start))
        return text

    def _heard(self, text, ago=None):
        """ago: seconds since they started saying it."""
        more = {} if ago is None else {"ago": round(max(0.0, ago), 2)}
        if self.to_stage():
            self._said += 1
            self._set("heard", text=text, to="stage", n=self._said, **more)
            self._set("idle")
            return
        self._set("heard", text=text, **more)
        try:
            self.send(text)
        except Exception as err:
            self._idle("Claude couldn't take it: %s" % err)
            return
        self._set("idle")

    def _set(self, state, **more):
        self.state = state
        self.emit(dict({"type": "talk", "state": state}, **more))

    def _idle(self, problem):
        self._set("idle", problem=problem)


def check_mic(mic):
    if mic not in MICS:
        raise ValueError("mic must be one of %s" % ", ".join(MICS))
    return mic


class WakeListener:
    """Listens to a microphone all the time for "Hey Claude". Loud stretches (speech, or the band)
    are cut out and turned into words one at a time; anything that doesn't start with the wake
    words is dropped. "Hey Claude, chorus" goes to `talk` at once; a bare "Hey Claude" opens a few
    seconds for the rest (see Talk.wake_heard). Frames come from the mic (start) or a test (feed)."""

    FRAME = 480             # 30 ms at 16 kHz
    LONGEST = 6.0           # seconds: a stretch this long is heard anyway (the band never stops)
    GAP = 0.6               # seconds of quiet that end a stretch
    ABOVE = 10.0            # dB over the room's usual level that counts as speech
    ROOM = 5.0              # seconds of levels the room's usual level is taken from

    def __init__(self, talk, device=None, transcribe=None):
        self.talk, self.device = talk, device
        self.transcribe = transcribe or talk.transcribe
        self.floor = -60.0
        self._levels = collections.deque(maxlen=int(self.ROOM * SAMPLE_RATE / self.FRAME))
        self._run, self._quiet, self._pre = [], 0, []
        self._jobs = queue.Queue(maxsize=1)     # one stretch waiting at most: if busy, drop it
        self._stream = None
        self._thread = threading.Thread(target=self._hear, name="g3xn-wake", daemon=True)
        self._stopped = False

    def start(self):
        import sounddevice
        self._thread.start()
        self._stream = sounddevice.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=self.device,
                                               blocksize=self.FRAME, callback=lambda data, *_: self.feed(data[:, 0].copy()))
        self._stream.start()

    def stop(self):
        self._stopped = True
        stream, self._stream = self._stream, None
        if stream:
            stream.stop()
            stream.close()
        try:
            self._jobs.put_nowait(None)
        except queue.Full:
            pass

    def feed(self, frame):
        """One frame of samples (float32, 16 kHz)."""
        import numpy
        if self.talk.state != "idle":                         # someone's holding the switch
            return
        level = 10 * numpy.log10(float(numpy.mean(frame * frame)) + 1e-12)
        # The room's usual level: low in the last few seconds' levels, so the band bleeding into a
        # mic on you becomes the baseline, and your voice, close to it, stands out above it.
        if self._levels:
            self.floor = float(numpy.percentile(self._levels, 30))
        self._levels.append(level)
        loud = level > self.floor + self.ABOVE
        if self._run or loud:
            self._run.append(frame)
            self._quiet = 0 if loud else self._quiet + 1
            seconds = len(self._run) * self.FRAME / SAMPLE_RATE
            if self._quiet * self.FRAME / SAMPLE_RATE >= self.GAP or seconds >= self.LONGEST:
                stretch = numpy.concatenate(self._pre + self._run)
                began = time.monotonic() - len(stretch) / SAMPLE_RATE
                self._run, self._pre, self._quiet = [], [], 0
                if seconds - self.GAP >= 0.3:
                    try:
                        self._jobs.put_nowait((stretch, began))
                    except queue.Full:
                        pass
        else:
            self._pre = (self._pre + [frame])[-10:]              # 0.3 s before it got loud

    def _hear(self):
        while not self._stopped:
            stretch = self._jobs.get()
            if stretch is None:
                return
            audio, began = stretch
            try:
                words = words_of(self.transcribe, audio)
            except Exception:
                continue
            self.talk.wake_heard(words, began)
