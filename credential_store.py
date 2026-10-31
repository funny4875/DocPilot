"""Windows 使用者專屬的加密帳密檔。"""
import json
import os
from pathlib import Path

import win32crypt


APP_DIR = Path(__file__).resolve().parent
STORE = APP_DIR / "accounts.dpapi"
OLD_FILES = (APP_DIR / "temp.txt", APP_DIR / "temp - 複製.txt")


def load_accounts():
    if not STORE.exists():
        return {}
    data = win32crypt.CryptUnprotectData(STORE.read_bytes(), None, None, None, 0)[1]
    accounts = json.loads(data.decode("utf-8"))
    if not isinstance(accounts, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in accounts.items()):
        raise ValueError("加密帳密檔格式錯誤。")
    return accounts


def save_accounts(accounts):
    if not all(k.strip() and v for k, v in accounts.items()):
        raise ValueError("帳號和密碼不能空白。")
    data = json.dumps(accounts, ensure_ascii=False).encode("utf-8")
    encrypted = win32crypt.CryptProtectData(data, None, None, None, None, 0)
    temporary = STORE.with_suffix(".tmp")
    temporary.write_bytes(encrypted)
    if load_encrypted(temporary) != accounts:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("加密帳密驗證失敗，未更新原檔。")
    os.replace(temporary, STORE)


def load_encrypted(path):
    return json.loads(win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1].decode("utf-8"))


def migrate_plaintext():
    accounts = load_accounts()
    imported = 0
    for path in OLD_FILES:
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        if len(lines) < 2 or not lines[0].strip() or not lines[1].strip():
            raise ValueError(f"舊帳密檔格式錯誤：{path.name}；明文檔尚未刪除。")
        account, password = lines[0].strip(), lines[1].strip()
        if account in accounts and accounts[account] != password:
            raise ValueError(f"舊帳密檔帳號重複且密碼不同：{account}；明文檔尚未刪除。")
        if account not in accounts:
            accounts[account] = password
            imported += 1
    if any(path.exists() for path in OLD_FILES):
        save_accounts(accounts)
        if load_accounts() != accounts:
            raise RuntimeError("加密帳密檔回讀失敗；明文檔尚未刪除。")
        for path in OLD_FILES:
            path.unlink(missing_ok=True)
    return imported
