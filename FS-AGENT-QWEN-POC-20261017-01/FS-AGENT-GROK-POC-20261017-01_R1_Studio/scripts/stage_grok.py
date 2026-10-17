#!/usr/bin/env python3
"""Download an official pinned macOS arm64 binary; never execute it or touch personal installs."""
import argparse
import base64
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tarfile
import urllib.request
from pathlib import Path

VERSION = "1.0.62"
NAME = "@xai-official/grok-darwin-arm64"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.output.is_symlink() or any(args.output.iterdir()):
        raise RuntimeError("output must be an empty, non-symlink directory")
    url = f"https://registry.npmjs.org/@xai-official%2Fgrok-darwin-arm64/{VERSION}"
    with urllib.request.urlopen(url, timeout=30) as response:
        meta = json.load(response)
    if meta["name"] != NAME or meta["version"] != VERSION:
        raise RuntimeError("release metadata mismatch")
    tarball = meta["dist"]["tarball"]
    if not tarball.startswith("https://registry.npmjs.org/@xai-official/"):
        raise RuntimeError("unexpected download host")
    cache = args.output.parent / "cache"
    cache.mkdir(mode=0o700, exist_ok=True)
    archive = cache / f"grok-darwin-arm64-{VERSION}.tgz"
    if not archive.exists():
        partial = archive.with_suffix(".part")
        with urllib.request.urlopen(tarball, timeout=60) as response, partial.open("wb") as stream:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 400 * 1024 * 1024:
                    raise RuntimeError("archive exceeds size bound")
                stream.write(chunk)
                if size % (8 * 1024 * 1024) == 0:
                    print(f"Downloaded {size // (1024 * 1024)} MiB", flush=True)
        os.replace(partial, archive)
    with archive.open("rb") as stream:
        actual = "sha512-" + base64.b64encode(hashlib.file_digest(stream, "sha512").digest()).decode()
    if actual != meta["dist"]["integrity"]:
        raise RuntimeError("npm integrity mismatch")
    with tarfile.open(archive, mode="r:gz") as tar:
        # Version 1.0.62 publishes a Brotli-compressed Mach-O, not an executable member.
        member = tar.getmember("package/bin/grok.br")
        if not member.isfile() or member.size > 400 * 1024 * 1024:
            raise RuntimeError("binary is not a regular file")
        compressed = cache / f"grok-{VERSION}.br"
        with tar.extractfile(member) as source, compressed.open("wb") as target:
            shutil.copyfileobj(source, target)
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required only to decompress the official Brotli binary")
    target = args.output / "grok"
    with target.open("wb") as stream:
        subprocess.run([node, "-e",
            "process.stdout.write(require('node:zlib').brotliDecompressSync(require('node:fs').readFileSync(process.argv[1]), {maxOutputLength:536870912}))",
            str(compressed.resolve())], stdout=stream, check=True, timeout=90)
    with target.open("rb") as stream:
        if struct.unpack("<II", stream.read(8)) != (0xFEEDFACF, 0x0100000C):
            raise RuntimeError("downloaded binary is not a macOS arm64 executable")
        stream.seek(0)
        binary_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    target.chmod(0o700)
    receipt = {"publisher": "@xai-official", "package_name": NAME, "package_version": VERSION,
               "metadata_url": url, "tarball_url": tarball, "npm_integrity": actual,
               "archive_member": member.name, "binary_sha256": binary_sha256,
               "binary_size": target.stat().st_size, "binary_executed": False}
    (args.output / "release.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
