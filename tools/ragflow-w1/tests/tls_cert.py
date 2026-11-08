"""A throwaway self-signed certificate for 127.0.0.1, made at test time with the standard library only.

The TLS tests need a server certificate that the system does not trust. Nothing is stored in the
repository: each call makes a new ECDSA P-256 key, valid for two days, in the folder it is given.
Tests only. Plain arithmetic, not constant-time: never use it for anything real.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

# NIST P-256 (SEC 2, secp256r1).
_P = 2 ** 256 - 2 ** 224 + 2 ** 192 + 2 ** 96 - 1
_A = _P - 3
_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
_G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
      0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % _P == 0:
        return None
    if p == q:
        slope = (3 * p[0] * p[0] + _A) * pow(2 * p[1], -1, _P) % _P
    else:
        slope = (q[1] - p[1]) * pow(q[0] - p[0], -1, _P) % _P
    x = (slope * slope - p[0] - q[0]) % _P
    return x, (slope * (p[0] - x) - p[1]) % _P


def _mul(k: int, point=_G):
    result = None
    while k:
        if k & 1:
            result = _add(result, point)
        point = _add(point, point)
        k >>= 1
    return result


# DER -----------------------------------------------------------------------------------------------

def _tlv(tag: int, body: bytes) -> bytes:
    n = len(body)
    if n < 0x80:
        length = bytes([n])
    else:
        size = (n.bit_length() + 7) // 8
        length = bytes([0x80 | size]) + n.to_bytes(size, 'big')
    return bytes([tag]) + length + body


def _seq(*parts: bytes) -> bytes:
    return _tlv(0x30, b''.join(parts))


def _int(value: int) -> bytes:
    return _tlv(0x02, value.to_bytes(value.bit_length() // 8 + 1, 'big'))  # minimal, sign bit clear


def _oid(dotted: str) -> bytes:
    arcs = [int(a) for a in dotted.split('.')]
    body = bytes([40 * arcs[0] + arcs[1]])
    for arc in arcs[2:]:
        group = [arc & 0x7f]
        arc >>= 7
        while arc:
            group.append(0x80 | (arc & 0x7f))
            arc >>= 7
        body += bytes(reversed(group))
    return _tlv(0x06, body)


def _bits(data: bytes, unused: int = 0) -> bytes:
    return _tlv(0x03, bytes([unused]) + data)


def _utc(moment: datetime) -> bytes:
    return _tlv(0x17, moment.strftime('%y%m%d%H%M%SZ').encode('ascii'))


def _extension(oid: str, critical: bool, value: bytes) -> bytes:
    return _seq(_oid(oid), *([_tlv(0x01, b'\xff')] if critical else []), _tlv(0x04, value))


def _pem(label: str, der: bytes) -> str:
    body = base64.b64encode(der).decode('ascii')
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return '\n'.join([f'-----BEGIN {label}-----', *lines, f'-----END {label}-----', ''])


def make_self_signed(folder: Path) -> tuple[Path, Path]:
    """Write cert.pem and key.pem for 127.0.0.1 into `folder`; return their paths."""
    secret = secrets.randbelow(_N - 1) + 1
    x, y = _mul(secret)
    public = b'\x04' + x.to_bytes(32, 'big') + y.to_bytes(32, 'big')
    curve = _oid('1.2.840.10045.3.1.7')               # prime256v1
    algorithm = _seq(_oid('1.2.840.10045.4.3.2'))     # ecdsa-with-SHA256
    name = _seq(_tlv(0x31, _seq(_oid('2.5.4.3'), _tlv(0x0c, b'127.0.0.1'))))
    now = datetime.now(timezone.utc)
    key_id = hashlib.sha1(public).digest()
    extensions = _tlv(0xa3, _seq(
        _extension('2.5.29.19', True, _seq(_tlv(0x01, b'\xff'))),        # basicConstraints CA:TRUE
        _extension('2.5.29.15', True, _bits(b'\x84', unused=2)),         # keyUsage digitalSignature, keyCertSign
        _extension('2.5.29.37', False, _seq(_oid('1.3.6.1.5.5.7.3.1'))),  # extendedKeyUsage serverAuth
        _extension('2.5.29.14', False, _tlv(0x04, key_id)),              # subjectKeyIdentifier
        _extension('2.5.29.35', False, _seq(_tlv(0x80, key_id))),        # authorityKeyIdentifier
        _extension('2.5.29.17', False, _seq(_tlv(0x87, bytes([127, 0, 0, 1])))),  # subjectAltName IP
    ))
    tbs = _seq(_tlv(0xa0, _int(2)), _int(secrets.randbits(63) | 1), algorithm, name,
               _seq(_utc(now - timedelta(days=1)), _utc(now + timedelta(days=1))), name,
               _seq(_seq(_oid('1.2.840.10045.2.1'), curve), _bits(public)), extensions)
    digest = int.from_bytes(hashlib.sha256(tbs).digest(), 'big')
    r = s = 0
    while not (r and s):
        nonce = secrets.randbelow(_N - 1) + 1
        r = _mul(nonce)[0] % _N
        s = pow(nonce, -1, _N) * (digest + r * secret) % _N
    certificate = _seq(tbs, algorithm, _bits(_seq(_int(r), _int(s))))
    key = _seq(_int(1), _tlv(0x04, secret.to_bytes(32, 'big')), _tlv(0xa0, curve), _tlv(0xa1, _bits(public)))
    cert_path, key_path = folder / 'cert.pem', folder / 'key.pem'
    cert_path.write_text(_pem('CERTIFICATE', certificate), encoding='ascii')
    key_path.write_text(_pem('EC PRIVATE KEY', key), encoding='ascii')
    return cert_path, key_path
