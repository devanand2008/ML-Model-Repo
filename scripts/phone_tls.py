"""Generate a project-local CA and server certificate; never install system trust."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

ROOT = Path(__file__).resolve().parents[1]


def generate(address, directory=None):
    address = ipaddress.ip_address(address)
    if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified or address.is_link_local:
        raise ValueError('Use the laptop private Wi-Fi IPv4 address')
    directory = directory or ROOT / 'data' / 'phone_tls'
    directory.mkdir(parents=True, exist_ok=True)
    ca_file, ca_key_file = directory/'transitopt-phone-ca.crt', directory/'ca.key'
    now = datetime.now(timezone.utc)
    ca_key = serialization.load_pem_private_key(ca_key_file.read_bytes(), None) if ca_key_file.exists() else rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca = x509.load_pem_x509_certificate(ca_file.read_bytes()) if ca_file.exists() else None
    has_identifier = bool(ca and any(isinstance(extension.value,x509.SubjectKeyIdentifier) for extension in ca.extensions))
    if not has_identifier:
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'TransitOpt Local Phone Camera CA')])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
            .not_valid_after(now+timedelta(days=365)).add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=False,key_cert_sign=True,
                crl_sign=True,content_commitment=False,data_encipherment=False,key_agreement=False,
                encipher_only=False,decipher_only=False),critical=True).sign(ca_key,hashes.SHA256()))
        ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        ca_key_file.write_bytes(ca_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    if ca.not_valid_after_utc <= now+timedelta(days=1):
        raise ValueError('The local CA is expiring; create a new phone_tls directory and trust its new certificate manually')
    key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    certificate = (x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'TransitOpt Phone Camera')]))
        .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(minutes=5)).not_valid_after(min(now+timedelta(days=90),ca.not_valid_after_utc))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(address),x509.DNSName('localhost')]),critical=False)
        .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),critical=False)
        .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=True,key_cert_sign=False,
            crl_sign=False,content_commitment=False,data_encipherment=False,key_agreement=False,
            encipher_only=False,decipher_only=False),critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
        .sign(ca_key,hashes.SHA256()))
    (directory/'server.crt').write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    (directory/'server.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    (directory/'address.txt').write_text(str(address),encoding='ascii')
    return ca.fingerprint(hashes.SHA256()).hex()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('address');args=parser.parse_args()
    print('Local CA SHA256:',generate(args.address))
