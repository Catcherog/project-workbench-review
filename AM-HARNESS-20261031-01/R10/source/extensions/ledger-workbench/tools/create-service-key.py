"""Create an owner-only local service key, never print key contents or replace a key."""
import argparse
import os
import secrets
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("path",type=Path)
args=parser.parse_args()
fd=os.open(args.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,"wb") as stream:
    stream.write(secrets.token_bytes(32));stream.flush();os.fsync(stream.fileno())
print(f"Created owner-only key: {args.path}")
