"""登入 CloudOP，進入「主辦公文」並開啟清單第一則公文。
可供其他 Python 流程匯入：
    import enterFirstDoc
    driver = enterFirstDoc.enter_first_doc()
呼叫端使用完 driver 後應自行呼叫 driver.quit()。

也可直接執行本檔；瀏覽器會保持開啟，按 Ctrl+C 結束。
"""
import sys
import time
from selenium.webdriver.common.by import By
import cloudop_login

MAIN_DOCS_SEARCH_XPATH = (
    '//*[@id="divItemCount"]//*[self::a or self::h5 or self::button or self::span]'
    '[contains(normalize-space(string(.)), "主辦公文")]'
)
MAIN_DOCS_FALLBACK_XPATH = '//*[@id="divItemCount"]/a[2]/h5[1]'
FIRST_DOCUMENT_XPATH = '//*[@id="dg"]/tbody/tr[1]/td[3]/a'


def find_and_click_main_documents(driver, timeout=600):
    """等待登入完成，以文字搜尋「主辦公文」並點擊。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            alert = driver.switch_to.alert
            message = (alert.text or "").strip()
            cloudop_login.log(f"登入頁提示：{message}（請在 Chrome 處理提示後繼續）")
            time.sleep(0.2)
            continue
        except Exception:
            pass

        try:
            if driver.find_elements(By.XPATH, cloudop_login.ACCOUNT_XPATH):
                time.sleep(0.2)
                continue

            candidates = driver.find_elements(By.XPATH, MAIN_DOCS_SEARCH_XPATH)
            if not candidates:
                candidates = driver.find_elements(By.XPATH, MAIN_DOCS_FALLBACK_XPATH)
            for element in candidates:
                label = " ".join((element.text or "").split())
                if "主辦公文" in label and element.is_displayed() and element.is_enabled():
                    element.click()
                    cloudop_login.log(f"已搜尋並點擊「主辦公文」：{label}")
                    return
        except Exception as exc:
            cloudop_login.log(f"等待登入或尋找「主辦公文」：{exc}")
        time.sleep(0.2)

    raise TimeoutError("等待登入完成或尋找「主辦公文」逾時。")


def click_first_document(driver, timeout=120):
    """等待第一列公文連結載入，確認可見後點擊。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            for element in driver.find_elements(By.XPATH, FIRST_DOCUMENT_XPATH):
                if element.is_displayed() and element.is_enabled():
                    title = " ".join((element.text or "").split())
                    cloudop_login.log(f"找到表格第一則公文：{title or '（連結文字空白）'}")
                    element.click()
                    cloudop_login.log("已點選表格第一則公文。")
                    return
        except Exception as exc:
            cloudop_login.log(f"等待第一則公文連結：{exc}")
        time.sleep(0.2)

    raise TimeoutError("等待表格第一則公文逾時，未能點選。")


def enter_first_doc(
    login_timeout=20,
    main_docs_timeout=600,
    document_timeout=120,
    driver=None,
    after_first_doc=None,
    credentials=None,
):
    """登入並開啟第一則公文；可接收既有 driver 並以 callback 傳遞 driver。

    ``after_first_doc`` 若提供，會在 step 0 完成後以仍開啟的 driver 呼叫，
    讓後續操作在同一個 Selenium 執行程序及瀏覽器工作階段中執行。
    ``driver`` 若提供，則直接沿用該 driver，不重新登入。
    """
    owns_driver = driver is None
    if owns_driver:
        if credentials is None:
            from credential_store import load_accounts, migrate_plaintext
            migrate_plaintext()
            accounts = load_accounts()
            if len(accounts) != 1:
                raise RuntimeError("請先在多帳號介面選擇帳號登入。")
            credentials = next(iter(accounts.items()))
        driver = cloudop_login.login(
            credentials,
            timeout=login_timeout,
            allow_local_network=True,
            manual_captcha=False,
        )
    try:
        if driver.find_elements(By.XPATH, cloudop_login.ACCOUNT_XPATH):
            cloudop_login.log("登入頁仍顯示帳號欄位，等待登入完成，再搜尋「主辦公文」。")
        find_and_click_main_documents(driver, timeout=main_docs_timeout)
        cloudop_login.log("已開啟主辦公文，等待表格載入。")
        click_first_document(driver, timeout=document_timeout)
        cloudop_login.log("已開啟第一則公文。")
        if after_first_doc is not None:
            after_first_doc(driver)
        return driver
    except Exception:
        if owns_driver:
            driver.quit()
        raise

def main():
    driver = enter_first_doc()
    try:
        cloudop_login.log("瀏覽器保持開啟；按 Ctrl+C 結束本程式並關閉瀏覽器。")
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        cloudop_login.log("收到中斷指令，關閉瀏覽器。")
    finally:
        driver.quit()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"enterFirstDoc 錯誤：{exc}", file=sys.stderr)
        raise SystemExit(1)
