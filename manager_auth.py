"""관리자 로그인 비밀번호의 로컬 저장과 검증."""

import hashlib
import hmac
import secrets
from getpass import getpass
from pathlib import Path


HASH_FILE = Path(__file__).resolve().parent / "instance" / "manager_password.hash"
ITERATIONS = 300_000


def hash_manager_password(password):
    if not isinstance(password, str) or not password:
        raise ValueError("비어 있지 않은 비밀번호가 필요합니다.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"v1${salt.hex()}${digest.hex()}"


def verify_manager_password(password, stored_hash):
    if not isinstance(password, str) or not isinstance(stored_hash, str):
        return False
    try:
        version, salt_hex, digest_hex = stored_hash.split("$")
        if version != "v1":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        if len(salt) != 16 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, ITERATIONS
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, UnicodeError):
        return False


if __name__ == "__main__":
    first = getpass("관리자 로그인 비밀번호: ")
    second = getpass("비밀번호 다시 입력: ")
    if not first or first != second:
        raise SystemExit("비밀번호가 비어 있거나 일치하지 않습니다.")
    HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HASH_FILE.write_text(hash_manager_password(first), encoding="utf-8")
    print("관리자 로그인 비밀번호를 로컬에 저장했습니다.")
