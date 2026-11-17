"""產生線上更新用的 ed25519 簽章金鑰（只需執行一次）。

  私鑰：%USERPROFILE%\\.satdashboard\\update_signing_key.pem（不進版控；遺失就要換公鑰並重發 exe）
  公鑰：src/update_pubkey.hex（內嵌在 exe，用來驗證 manifest.json.sig）

已有私鑰時不覆蓋，只重新匯出公鑰。用法：python scripts/update_keygen.py
"""
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
KEY = Path.home() / ".satdashboard" / "update_signing_key.pem"
PUB = ROOT / "src" / "update_pubkey.hex"


def load_or_create() -> Ed25519PrivateKey:
    if KEY.exists():
        return serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    KEY.parent.mkdir(parents=True, exist_ok=True)
    k = Ed25519PrivateKey.generate()
    KEY.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    print("已產生私鑰：", KEY)
    return k


def main() -> None:
    k = load_or_create()
    raw = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    PUB.write_text(raw.hex() + "\n", encoding="ascii")
    print("公鑰已寫入：", PUB, raw.hex())


if __name__ == "__main__":
    main()
