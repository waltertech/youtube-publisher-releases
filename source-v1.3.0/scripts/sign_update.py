#!/usr/bin/env python3
"""Sign/verify update.json using the EXISTING publisher Ed25519 trust anchor.

Requires cryptography. Private keys remain outside the release directory.
"""
import argparse
import base64
import json
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['sign', 'verify'])
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[1] / 'Resources/update-config.json')
    parser.add_argument('--key', type=Path, help='Ed25519 private key: PEM, 32 raw bytes or base64-encoded 32-byte seed')
    args = parser.parse_args()
    public_bytes = base64.b64decode(json.loads(args.config.read_text())['public_key'], validate=True)
    public = Ed25519PublicKey.from_public_bytes(public_bytes)
    content = args.manifest.read_bytes()
    signature_path = args.manifest.with_suffix('.sig')
    if args.mode == 'sign':
        if not args.key:
            parser.error('sign requires --key')
        data = args.key.read_bytes()
        if data.startswith(b'-----BEGIN'):
            private = serialization.load_pem_private_key(data, password=None)
        else:
            private = Ed25519PrivateKey.from_private_bytes(data if len(data) == 32 else base64.b64decode(data.strip(), validate=True))
        if not isinstance(private, Ed25519PrivateKey):
            raise ValueError('私钥不是 Ed25519')
        actual = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        if actual != public_bytes:
            raise ValueError('私钥与旧客户端内置公钥不匹配，拒绝生成无效更新签名')
        signature_path.write_bytes(base64.b64encode(private.sign(content)))
    public.verify(base64.b64decode(signature_path.read_bytes().strip(), validate=True), content)
    print('PASS: Ed25519 update signature matches existing publisher public key')


if __name__ == '__main__':
    main()
