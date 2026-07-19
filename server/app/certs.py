"""自签 HTTPS 证书（design/03 §7.1，mkcert 思路的内置实现，无外部工具依赖）。

首次启动生成根 CA（10 年）与站点证书（SAN = localhost + 探测到的局域网 IP +
CASHFLOW_EXTRA_HOSTS 追加的域名/公网 IP）。手机一次性信任根 CA 后，扫描框
（getUserMedia 实时取景）即可在 https://<IP>:8443 使用。
IP 变化时只重签站点证书，根 CA 不变——已信任过的手机无需重复操作。
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import os
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

CA_NAME = "Cashflow Companion 本地根证书"


def lan_ips() -> list[str]:
    """探测本机 IPv4 局域网地址（UDP 假连接取路由源地址 + 主机名解析兜底）。"""
    ips: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("223.5.5.5", 80))   # 不真正发包，只为取本机路由源 IP
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def _san_hosts() -> tuple[list[str], list[str]]:
    """返回 (DNS 名列表, IP 列表)，含 CASHFLOW_EXTRA_HOSTS（逗号分隔）。"""
    dns = ["localhost"]
    ips = ["127.0.0.1"] + lan_ips()
    for host in os.environ.get("CASHFLOW_EXTRA_HOSTS", "").split(","):
        host = host.strip()
        if not host:
            continue
        try:
            ipaddress.ip_address(host)
            if host not in ips:
                ips.append(host)
        except ValueError:
            if host not in dns:
                dns.append(host)
    return dns, ips


def _write_key_cert(key, cert, key_path: Path, cert_path: Path) -> None:
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _load_or_create_ca(cert_dir: Path):
    ca_key_path, ca_cert_path = cert_dir / "ca.key", cert_dir / "ca.crt"
    if ca_key_path.exists() and ca_cert_path.exists():
        key = serialization.load_pem_private_key(ca_key_path.read_bytes(), None)
        cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
        if cert.not_valid_after_utc > dt.datetime.now(dt.timezone.utc):
            return key, cert
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=False, content_commitment=False,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True, crl_sign=True,
                encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    _write_key_cert(key, cert, ca_key_path, ca_cert_path)
    return key, cert


def _leaf_sans(cert: x509.Certificate) -> set[str]:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return set()
    return {str(v) for v in san.value.get_values_for_type(x509.DNSName)} | \
           {str(v) for v in san.value.get_values_for_type(x509.IPAddress)}


def ensure_certs(cert_dir: str | Path) -> tuple[Path, Path]:
    """确保证书就绪，返回 (站点证书路径, 站点私钥路径)。幂等，可反复调用。"""
    cert_dir = Path(cert_dir)
    cert_dir.mkdir(parents=True, exist_ok=True)
    ca_key, ca_cert = _load_or_create_ca(cert_dir)

    dns, ips = _san_hosts()
    wanted = set(dns) | set(ips)
    leaf_cert_path, leaf_key_path = cert_dir / "server.crt", cert_dir / "server.key"
    if leaf_cert_path.exists() and leaf_key_path.exists():
        leaf = x509.load_pem_x509_certificate(leaf_cert_path.read_bytes())
        now = dt.datetime.now(dt.timezone.utc)
        if (_leaf_sans(leaf) >= wanted
                and leaf.not_valid_after_utc > now + dt.timedelta(days=7)
                and leaf.issuer == ca_cert.subject):
            return leaf_cert_path, leaf_key_path

    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    san = x509.SubjectAlternativeName(
        [x509.DNSName(d) for d in dns]
        + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips])
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cashflow-lan")]))
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=825))   # iOS 对叶证书有效期上限约束
            .add_extension(san, critical=False)
            .add_extension(x509.ExtendedKeyUsage(
                [x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write_key_cert(key, cert, leaf_key_path, leaf_cert_path)
    return leaf_cert_path, leaf_key_path
