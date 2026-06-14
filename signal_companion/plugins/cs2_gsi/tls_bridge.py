"""HTTPS state bridge for the SignalRGB effect.

A SignalRGB effect runs in Ultralight from a *public* https origin
(`signalrgbmarketplace.pages.dev`). From there it CANNOT reach the plain-HTTP
receiver on localhost: http→ from https is mixed-content blocked, self-signed
https is rejected (Ultralight trusts only its bundled `cacert.pem`), and a
public→private fetch is gated by Private Network Access.

The combination that actually works (confirmed live):
  1. serve `/state` over **HTTPS**,
  2. with a cert chained to a **local CA appended to Ultralight's cacert.pem**,
  3. and send **`Access-Control-Allow-Private-Network: true`** (+ CORS).

This module generates/reuses that CA + server cert, patches every Ultralight
`cacert.pem` it can find (idempotent, keeps a `.bak`), and runs the HTTPS
GET-/state server. SignalRGB must be restarted once after a fresh patch so
Ultralight reloads the bundle. Requires the `cryptography` package; if it's
missing the bridge disables itself (the rest of the plugin still runs).
"""
import datetime
import glob
import ipaddress
import json
import logging
import os
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CA_CN = "SignalCompanion CS2 Local CA"

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False


def available():
    return _HAS_CRYPTO


# ── certificate generation (CA + 127.0.0.1 server cert) ──────────────────────
def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _make_ca():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    cert = (x509.CertificateBuilder()
            .subject_name(_name(CA_CN)).issuer_name(_name(CA_CN))
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True,
                                         crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False,
                                         decipher_only=False), critical=True)
            .add_extension(ski, critical=False)
            .sign(key, hashes.SHA256()))
    return key, cert


def _make_server(ca_key, ca_cert):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)
    san = x509.SubjectAlternativeName([
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        x509.DNSName("localhost")])
    ca_ski = ca_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
    cert = (x509.CertificateBuilder()
            .subject_name(_name("127.0.0.1")).issuer_name(ca_cert.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(san, critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return key, cert


def ensure_certs(cert_dir) -> dict:
    """Generate the CA + server cert once and reuse them. Returns paths + the CA
    PEM bytes, or {} if cryptography is unavailable."""
    if not _HAS_CRYPTO:
        return {}
    d = Path(cert_dir)
    d.mkdir(parents=True, exist_ok=True)
    ca_pem_p, chain_p, key_p = d / "ca.pem", d / "server_chain.pem", d / "server_key.pem"
    if not (ca_pem_p.exists() and chain_p.exists() and key_p.exists()):
        ca_key, ca_cert = _make_ca()
        srv_key, srv_cert = _make_server(ca_key, ca_cert)
        ca_pem = ca_cert.public_bytes(serialization.Encoding.PEM)
        ca_pem_p.write_bytes(ca_pem)
        chain_p.write_bytes(srv_cert.public_bytes(serialization.Encoding.PEM) + ca_pem)
        key_p.write_bytes(srv_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
        logging.info(f"[cs2/tls] generated local CA + server cert in {d}")
    return {"ca_pem": ca_pem_p.read_bytes(), "chain": str(chain_p), "key": str(key_p)}


# ── trust: append our CA to Ultralight's cacert.pem ──────────────────────────
def _cacert_paths():
    bases = []
    for env in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env)
        if base:
            bases.append(os.path.join(base, "VortxEngine", "app-*", "Signal-x64", "cacert.pem"))
    out = []
    for pat in bases:
        out.extend(glob.glob(pat))
    return out


def patch_cacert(ca_pem: bytes) -> list:
    """Append our CA to every Ultralight cacert.pem (idempotent; keeps a .bak and
    rebuilds from it each time so SignalRGB updates that replace the bundle get
    re-trusted on our next run). Returns the paths that now trust our CA."""
    done = []
    block = b"\n# SignalCompanion CS2 Local CA\n" + ca_pem
    for p in _cacert_paths():
        try:
            bak = p + ".signalcompanion.bak"
            if os.path.exists(bak):
                base = Path(bak).read_bytes()
            else:
                base = Path(p).read_bytes()
                Path(bak).write_bytes(base)
            if ca_pem in base:                       # bundle already shipped it (unlikely)
                done.append(p)
                continue
            desired = base + block
            if Path(p).read_bytes() != desired:
                Path(p).write_bytes(desired)
                logging.info(f"[cs2/tls] trusted local CA in {p}")
            done.append(p)
        except Exception:
            logging.exception(f"[cs2/tls] could not patch {p}")
    return done


# ── HTTPS GET /state server (CORS + Private Network Access) ──────────────────
class HttpsStateServer(threading.Thread):
    def __init__(self, host, port, chain_path, key_path, get_state):
        super().__init__(daemon=True, name="CS2HttpsState")
        self.host, self.port = host, port
        self.chain_path, self.key_path = chain_path, key_path
        self.get_state = get_state
        self._httpd = None

    def run(self):
        get_state = self.get_state

        class H(BaseHTTPRequestHandler):
            # HTTP/1.1 keep-alive so the effect reuses one TLS connection for its
            # ~10 polls/s instead of a fresh (expensive, flaky) TLS handshake
            # each time — that unreliability is why the effect only reacted now
            # and then.
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _cors(self):
                origin = self.headers.get("Origin", "*")
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "*")
                # Cache the (Private Network Access) preflight so most GETs skip it.
                self.send_header("Access-Control-Max-Age", "600")
                self.send_header("Vary", "Origin")

            def do_GET(self):
                body = json.dumps(get_state()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._cors()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()

        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(self.chain_path, self.key_path)
            self._httpd = ThreadingHTTPServer((self.host, self.port), H)
            self._httpd.socket = ctx.wrap_socket(self._httpd.socket, server_side=True)
        except OSError:
            logging.exception(f"[cs2/tls] could not bind https {self.host}:{self.port}")
            return
        logging.info(f"[cs2/tls] HTTPS state server on https://{self.host}:{self.port}")
        try:
            self._httpd.serve_forever(poll_interval=0.5)
        except Exception:
            logging.exception("[cs2/tls] https server loop crashed")

    def stop(self):
        if self._httpd:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
