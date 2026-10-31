"""Clean CloudOP announcement workflow entry point."""
import sys
import time

from 公告週知 import run_steps
import cloudop_login
import enterFirstDoc


def run(wait_for_pin=True, keep_browser_open=False):
    if wait_for_pin:
        from 公告週知 import _read_pin
        _read_pin()  # missing/empty PIN fails before opening CloudOP
    # Same live driver flows from step 0 into the notice workflow.
    def process_first(current):
        run_steps(current, wait_for_pin=wait_for_pin)
    driver = enterFirstDoc.enter_first_doc(after_first_doc=process_first)
    if not keep_browser_open:
        driver.quit()
        return
    try:
        cloudop_login.log("流程已結束；瀏覽器保留開啟，按 Ctrl+C 結束程式。")
        while driver.window_handles:
            time.sleep(0.5)
    except KeyboardInterrupt:
        cloudop_login.log("收到中斷，關閉 CloudOP 瀏覽器。")
    finally:
        driver.quit()


def main():
    try:
        from pathlib import Path
        app_dir = Path(__file__).resolve().parent
        from credential_store import load_accounts, migrate_plaintext
        migrate_plaintext()
        if len(load_accounts()) != 1:
            print("請使用「啟動多帳號登入.bat」選擇帳號；連續簡簽將於登入驗證後續修。")
            return
        pin_file = app_dir / "pin.txt"
        if not pin_file.exists():
            pin_file.write_text("請填入 PIN", encoding="utf-8")
            print("已建立 pin.txt 範本，請填入一行 PIN 後重新執行。")
            return
        run()
    except Exception as exc:
        print(f"公告週知失敗：{exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
