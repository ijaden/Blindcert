from __future__ import annotations

import hashlib
import subprocess
import tarfile
import urllib.request
from pathlib import Path


VERSION = "0.4.3"
SHA256 = "4b5f4f7a79f31365288fe4498ba2b70afc314c028696929c8d259ef50ab2e759"
URL = f"https://github.com/data61/MP-SPDZ/releases/download/v{VERSION}/mp-spdz-{VERSION}.tar.xz"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    external = root / "external"
    external.mkdir(exist_ok=True)
    archive = external / f"mp-spdz-{VERSION}.tar.xz"
    target = external / f"mp-spdz-{VERSION}"
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != SHA256:
        raise RuntimeError(f"MP-SPDZ archive sha256 mismatch: {digest}")
    if not target.exists():
        with tarfile.open(archive) as tf:
            tf.extractall(external)
    subprocess.run(["Scripts/tldr.sh"], cwd=target, check=True)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
