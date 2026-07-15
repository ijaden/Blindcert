from __future__ import annotations

import subprocess
import tarfile
import urllib.request
from pathlib import Path


VERSION = "0.9.0"
URL = (
    "https://github.com/TaceoLabs/co-snarks/releases/download/"
    f"co-circom-v{VERSION}/co-circom-x86_64-unknown-linux-gnu.tar.gz"
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    external = root / "external"
    external.mkdir(exist_ok=True)
    archive = external / "co-circom-x86_64-unknown-linux-gnu.tar.gz"
    binary = external / "co-circom"
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    if not binary.exists():
        with tarfile.open(archive) as tf:
            tf.extractall(external)
    binary.chmod(0o755)
    subprocess.run([str(binary), "--version"], check=True)
    print(binary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
