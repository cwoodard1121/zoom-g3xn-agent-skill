// The phone remote, from this computer: the address to open on the phone (and a QR code of it),
// the six-digit code that pairs it, and the phones already paired. Same Wi-Fi or a phone hotspot
// works over plain http; with Tailscale on both, the https address works from anywhere, and it's
// the one that lets the phone lend its mic. Only this computer sees the code.
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ApiError } from "../api";
import { api } from "../api";
import type { RemoteInfo } from "../api";
import { usePedal } from "../pedal";
import { Drawer } from "./Drawer";

export const onThisComputer = ["127.0.0.1", "localhost"].includes(location.hostname);

/** The status bar's Phone button, lit while the remote is on, and its sheet. */
export function PhoneButton() {
  const { linked } = usePedal();
  const [info, setInfo] = useRemote(linked);
  const [open, setOpen] = useState(false);
  if (!onThisComputer || !info) return null;
  return (
    <>
      <button className={`status-action phone-button${info.on ? " on" : ""}`} onClick={() => setOpen(true)} aria-haspopup="dialog">
        <span className="phone-led" aria-hidden="true" />
        Phone{info.devices.length ? ` · ${info.devices.length}` : ""}
      </button>
      {open && <PhoneSheet info={info} setInfo={setInfo} onClose={() => setOpen(false)} />}
    </>
  );
}

function useRemote(linked: boolean): [RemoteInfo | null, (i: RemoteInfo) => void] {
  const [info, setInfo] = useState<RemoteInfo | null>(null);
  const { remoteSeen } = usePedal();
  useEffect(() => {
    if (!linked || !onThisComputer) return;
    api.remote().then(setInfo, () => {});
  }, [linked, remoteSeen]);                 // the "remote" event leaves the code out: read it again
  return [info, setInfo];
}

function PhoneSheet({ info, setInfo, onClose }: { info: RemoteInfo; setInfo: (i: RemoteInfo) => void; onClose: () => void }) {
  const { act } = usePedal();
  const addresses = [
    info.tailscale?.https_url && { url: info.tailscale.https_url, how: "Anywhere, over Tailscale (https: the phone's mic works)" },
    info.url && { url: info.url, how: "Same Wi-Fi or this computer's hotspot" },
    info.tailscale?.url && { url: info.tailscale.url, how: "Anywhere, over Tailscale" },
  ].filter((a): a is { url: string; how: string } => !!a);
  const [shown, setShown] = useState(0);
  const address = addresses[Math.min(shown, addresses.length - 1)];
  const [qr, setQr] = useState("");
  useEffect(() => {
    if (!address) return setQr("");
    QRCode.toString(address.url, { type: "svg", margin: 1, errorCorrectionLevel: "M", color: { dark: "#120c00", light: "#ffb000" } }).then(setQr, () => setQr(""));
  }, [address?.url]);

  const left = useCountdown(info.code_expires);
  const run = async (fn: () => Promise<RemoteInfo>) => {
    const next = await act(fn);
    if (next) setInfo(next);
  };

  return (
    <Drawer title="Phone remote" onClose={onClose}>
      <div className="phone">
        <div className="phone-switch">
          <p>{info.on ? "Phones can reach g3xn." : "Off: no phone can reach g3xn."}</p>
          <button className={`button${info.on ? "" : " primary"}`} onClick={() => run(() => api.remoteSwitch(!info.on))}>
            {info.on ? "Turn off" : "Turn on"}
          </button>
        </div>

        {info.on && address && (
          <>
            <ol className="phone-steps">
              <li>On the phone, scan this or open the address.</li>
              <li>Enter the code. The phone stays paired until it's forgotten here.</li>
            </ol>
            <div className="phone-qr" dangerouslySetInnerHTML={{ __html: qr }} role="img" aria-label={`QR code for ${address.url}`} />
            <ul className="phone-addresses" aria-label="Addresses">
              {addresses.map((a, i) => (
                <li key={a.url}>
                  <button aria-pressed={a === address} onClick={() => setShown(i)}>
                    <span className="phone-url">{a.url}</span>
                    <span className="phone-how">{a.how}</span>
                  </button>
                </li>
              ))}
            </ul>
            {info.tailscale?.problem && <p className="phone-problem">Tailscale https: {info.tailscale.problem}</p>}

            <div className="phone-code">
              <span className="phone-code-label">Code</span>
              {info.code && left > 0 ? (
                <>
                  <b className="phone-digits">{info.code.slice(0, 3)} {info.code.slice(3)}</b>
                  <span className="phone-left">{Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}</span>
                </>
              ) : (
                <span className="phone-left">No code open</span>
              )}
              <button className="button" onClick={() => run(api.remoteCode)}>New code</button>
            </div>
          </>
        )}

        <h3 className="phone-title">Paired phones</h3>
        {info.devices.length ? (
          <ul className="phone-devices">
            {info.devices.map((d) => (
              <li key={d.id}>
                <span>
                  <b>{d.name}</b>
                  <small>last seen {ago(d.last_seen)}</small>
                </span>
                <button className="button" onClick={() => window.confirm(`Forget ${d.name}? It will need a new code to come back.`) && run(() => api.remoteForget(d.id))}>
                  Forget
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="phone-none">None yet.</p>
        )}
        <p className="phone-note">
          It's plain http on the local network, so on shared venue Wi-Fi use your phone's hotspot or Tailscale.
        </p>
      </div>
    </Drawer>
  );
}

function useCountdown(until?: number | null) {
  const left = () => (until ? Math.max(0, Math.round(until - Date.now() / 1000)) : 0);
  const [n, setN] = useState(left);
  useEffect(() => {
    setN(left());
    if (!until) return;
    const id = window.setInterval(() => setN(left()), 1000);
    return () => window.clearInterval(id);
  }, [until]);
  return n;
}

function ago(t: number) {
  const s = Date.now() / 1000 - t;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

/** On a phone: the app once it's paired; before that, the screen that takes the code. */
export function PairGate({ children }: { children: ReactNode }) {
  const [paired, setPaired] = useState<boolean | null>(onThisComputer ? true : null);
  useEffect(() => {
    if (onThisComputer) return;
    fetch("/api/status").then((r) => setPaired(r.status !== 401), () => setPaired(true));
  }, []);
  if (paired === null) return null;
  return paired ? <>{children}</> : <PairScreen onPaired={() => location.reload()} />;
}

function PairScreen({ onPaired }: { onPaired: () => void }) {
  const [code, setCode] = useState("");
  const [name, setName] = useState(() => (/iPhone/.test(navigator.userAgent) ? "iPhone" : /Android/.test(navigator.userAgent) ? "Android phone" : "Phone"));
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const send = async (digits: string) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.pair(digits, name);
      onPaired();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Can't reach the computer. Is g3xn still running?");
      setCode("");
    }
    setBusy(false);
  };
  return (
    <main className="pair">
      <p className="pair-mark" aria-hidden="true">G3XN</p>
      <h1 className="pair-title">Pair this phone</h1>
      <p className="pair-help">Enter the code from the Phone sheet on the computer.</p>
      <form
        className="pair-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (code.length === 6) send(code);
        }}
      >
        <input
          className="pair-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          maxLength={6}
          aria-label="Six-digit code"
          placeholder="000000"
          autoFocus
          value={code}
          onChange={(e) => {
            const digits = e.target.value.replace(/\D/g, "").slice(0, 6);
            setCode(digits);
            if (digits.length === 6 && !busy) send(digits);
          }}
        />
        <label className="pair-name">
          <span>Call it</span>
          <input value={name} maxLength={40} onChange={(e) => setName(e.target.value)} />
        </label>
        <button className="button primary" disabled={code.length !== 6 || busy}>{busy ? "Pairing…" : "Pair"}</button>
        {problem && <p className="pair-problem" role="alert">{problem}</p>}
      </form>
    </main>
  );
}
