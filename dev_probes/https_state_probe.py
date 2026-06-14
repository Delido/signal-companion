"""Throwaway HTTPS probe server: serves a fixed /state over a self-signed cert
on https://127.0.0.1:3443, to test whether the SignalRGB effect (Ultralight)
will fetch a self-signed localhost HTTPS endpoint. Not part of the app."""
import datetime
import json
import ssl
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

STATE = {"connected": True, "health": 42, "team": "CT", "activity": "playing",
         "round_phase": "live", "flashed": 0, "smoked": 0, "burning": 0,
         "bomb": None, "round_kills": 0, "probe": "https-self-signed-works"}


def make_cert():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    san = x509.SubjectAlternativeName([
        x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1")),
        x509.DNSName("localhost"),
    ])
    now = datetime.datetime.utcnow()
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(san, critical=False)
            .sign(key, hashes.SHA256()))
    d = Path(tempfile.mkdtemp())
    cpath, kpath = d / "cert.pem", d / "key.pem"
    cpath.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    kpath.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    return str(cpath), str(kpath)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_GET(self):
        body = json.dumps(STATE).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()


def main():
    cpath, kpath = make_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cpath, kpath)
    httpd = ThreadingHTTPServer(("127.0.0.1", 3443), H)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print("HTTPS probe serving https://127.0.0.1:3443/state (self-signed)")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
