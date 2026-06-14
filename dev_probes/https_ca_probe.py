"""Throwaway probe: generate a local CA, sign a 127.0.0.1 server cert with it,
APPEND the CA to SignalRGB's Ultralight cacert.pem, and serve /state over HTTPS
on https://127.0.0.1:3444. Tests whether trusting our CA via cacert.pem lets the
effect fetch a local HTTPS endpoint. Backs up cacert.pem first. Not shipped."""
import datetime
import glob
import ipaddress
import json
import os
import ssl
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

STATE = {"connected": True, "health": 42, "team": "CT", "activity": "playing",
         "round_phase": "live", "bomb": None, "probe": "https-CA-trust-works"}

MARKER = "SignalCompanion-LocalCA"


def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make_ca():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.utcnow()
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    cert = (x509.CertificateBuilder()
            .subject_name(_name(MARKER)).issuer_name(_name(MARKER))
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True,
                                         crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False,
                                         decipher_only=False), critical=True)
            .add_extension(ski, critical=False)
            .sign(key, hashes.SHA256()))
    return key, cert


def make_server_cert(ca_key, ca_cert):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    san = x509.SubjectAlternativeName([
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        x509.DNSName("localhost")])
    now = datetime.datetime.utcnow()
    ca_ski = ca_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
    cert = (x509.CertificateBuilder()
            .subject_name(_name("127.0.0.1")).issuer_name(ca_cert.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(san, critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return key, cert


def patch_cacert(ca_cert_pem: bytes):
    patched = []
    for p in glob.glob(os.path.join(
            os.environ["LOCALAPPDATA"], "VortxEngine", "app-*", "Signal-x64", "cacert.pem")):
        bak = p + ".signalcompanion.bak"
        if os.path.exists(bak):
            base = Path(bak).read_bytes()              # restore clean base on re-run
        else:
            base = Path(p).read_bytes()
            Path(bak).write_bytes(base)
        Path(p).write_bytes(base + b"\n" + ca_cert_pem)
        patched.append(p + " (appended fresh CA)")
    return patched


def main():
    ca_key, ca_cert = make_ca()
    srv_key, srv_cert = make_server_cert(ca_key, ca_cert)
    ca_pem = ca_cert.public_bytes(serialization.Encoding.PEM)

    print("patching cacert.pem:")
    for line in patch_cacert(ca_pem):
        print("  " + line)

    d = Path(tempfile.mkdtemp())
    chain = (srv_cert.public_bytes(serialization.Encoding.PEM)
             + ca_cert.public_bytes(serialization.Encoding.PEM))
    (d / "chain.pem").write_bytes(chain)
    (d / "key.pem").write_bytes(srv_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(d / "chain.pem"), str(d / "key.pem"))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _cors(self):
            origin = self.headers.get("Origin", "*")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Vary", "Origin")
        def do_GET(self):
            body = json.dumps(STATE).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self._cors(); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
        def do_OPTIONS(self):
            self.send_response(204); self._cors(); self.end_headers()

    httpd = ThreadingHTTPServer(("127.0.0.1", 3444), H)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print("HTTPS-CA probe serving https://127.0.0.1:3444/state")
    print(">>> RESTART SignalRGB so Ultralight reloads cacert.pem, then activate the probe effect.")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
