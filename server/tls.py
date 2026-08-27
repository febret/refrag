"""Generate Refrag's local self-signed HTTPS certificate."""

from datetime import datetime, timedelta, timezone
import ipaddress
import os
import socket
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def certificate_names():
    dns_names = {"localhost", socket.gethostname()}
    ip_addresses = {ipaddress.ip_address("127.0.0.1")}
    try:
        for info in socket.getaddrinfo(
                socket.gethostname(), None, family=socket.AF_INET):
            ip_addresses.add(ipaddress.ip_address(info[4][0]))
    except socket.gaierror:
        pass
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 80))
        ip_addresses.add(ipaddress.ip_address(probe.getsockname()[0]))
    except OSError:
        pass
    finally:
        probe.close()
    for value in os.environ.get("REFRAG_SSL_HOSTS", "").split(","):
        value = value.strip()
        if not value:
            continue
        try:
            ip_addresses.add(ipaddress.ip_address(value))
        except ValueError:
            dns_names.add(value)
    names = [x509.DNSName(name) for name in sorted(dns_names)]
    names.extend(x509.IPAddress(address) for address in sorted(
        ip_addresses, key=str))
    return names


def generate_certificate(cert_path, key_path):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Refrag Local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Refrag"),
    ])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName(certificate_names()),
            critical=False)
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True)
        .sign(key, hashes.SHA256())
    )
    with open(key_path, "wb") as key_file:
        key_file.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()))
    if os.name != "nt":
        os.chmod(key_path, 0o600)
    with open(cert_path, "wb") as cert_file:
        cert_file.write(certificate.public_bytes(serialization.Encoding.PEM))


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m server.tls CERT_PATH KEY_PATH")
    generate_certificate(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
