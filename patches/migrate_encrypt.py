"""One-time script to encrypt existing files and fix permissions."""
import os
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("ENCRYPTION_KEY")
if not key:
    print("ERROR: ENCRYPTION_KEY not set in .env")
    exit(1)

f = Fernet(key.encode())
root = Path("/opt/csl-docs/files")

if not root.exists():
    print(f"No files directory at {root}")
    exit(0)

count = 0
for filepath in root.rglob("*"):
    if filepath.is_file():
        data = filepath.read_bytes()
        # Fernet tokens start with 'gAAAAA'
        if data[:6] == b'gAAAAA':
            print(f"  SKIP (already encrypted): {filepath}")
            continue
        encrypted = f.encrypt(data)
        filepath.write_bytes(encrypted)
        os.chmod(str(filepath), 0o600)
        count += 1
        print(f"  Encrypted: {filepath}")

# Fix directory permissions
for dirpath in root.rglob("*"):
    if dirpath.is_dir():
        os.chmod(str(dirpath), 0o700)

os.chmod(str(root), 0o700)
print(f"\nDone. Encrypted {count} files.")
