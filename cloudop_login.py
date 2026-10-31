"""使用 Selenium 與 ddddocr 登入 CloudOP 公文系統。

帳密由呼叫端提供。驗證碼失敗時會重新整理並最多重試兩次。
"""
import argparse
import sys
import time
from pathlib import Path
import ddddocr
ocr_engine = ddddocr.DdddOcr(show_ad=False)
from selenium import webdriver
from selenium.common.exceptions import NoAlertPresentException, UnexpectedAlertPresentException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

LOGIN_URL = "https://www.cloudop.tw/CLOUDWEBAP/"
APP_DIR = Path(__file__).resolve().parent
CAPTCHA_PATH = APP_DIR / "cloudop_captcha.png"
FULL_SCREENSHOT_PATH = APP_DIR / "cloudop_login_screenshot.png"
CAPTCHA_LAST_PATH = APP_DIR / "cloudop_captcha_last.png"
FULL_SCREENSHOT_LAST_PATH = APP_DIR / "cloudop_login_screenshot_last.png"

# 使用者提供的欄位 XPath。
ACCOUNT_XPATH = '//*[@id="userId"]'
PASSWORD_XPATH = '//*[@id="userpd"]'
CAPTCHA_INPUT_XPATH = '//*[@id="txtImgCode"]'
# 若網站 DOM 與預設自動搜尋不同，可用命令列 --captcha-image-xpath / --submit-xpath 覆寫。
CAPTCHA_IMAGE_XPATHS = (
    '//*[@id="imgCode"]',
    '//*[@id="imgCaptcha"]',
    '//*[contains(@src,"ValidateCode") or contains(@src,"validate") or contains(@src,"captcha")]',
    '//img[contains(@id,"Code") or contains(@id,"code") or contains(@id,"Captcha") or contains(@id,"captcha")]',
)
SUBMIT_XPATHS = (
    '//*[@id="btnLogin"]',
    '//*[@id="ImageButton1"]',
    '//input[@type="submit"]',
    '//button[@type="submit"]',
    '//input[contains(@value,"登入") or contains(@value,"登錄")]',
    '//button[contains(normalize-space(.),"登入") or contains(normalize-space(.),"登錄")]',
)
CONFIRM_XPATHS = (
    '//*[@id="92474869-a3db-4ee3-bbf7-44ec10512da4"]',
    '//button[normalize-space(.)="確定"]',
    '//input[@type="button" and @value="確定"]',
)


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def first_visible(driver, xpaths):
    for xpath in xpaths:
        for element in driver.find_elements(By.XPATH, xpath):
            if element.is_displayed() and element.is_enabled():
                return element
    return None


def replace_text(element, value):
    element.click()
    element.send_keys(Keys.CONTROL, "a")
    element.send_keys(value)


def locate_fields(driver, image_xpath=None, submit_xpath=None):
    account = first_visible(driver, (ACCOUNT_XPATH,))
    password = first_visible(driver, (PASSWORD_XPATH,))
    captcha_input = first_visible(driver, (CAPTCHA_INPUT_XPATH,))
    image_xpaths = (image_xpath,) if image_xpath else CAPTCHA_IMAGE_XPATHS
    submit_xpaths = (submit_xpath,) if submit_xpath else SUBMIT_XPATHS
    image = first_visible(driver, image_xpaths)
    submit = first_visible(driver, submit_xpaths)
    return account, password, captcha_input, image, submit


def captcha_ready(driver, image_xpath=None, submit_xpath=None):
    try:
        if driver.execute_script("return document.readyState") != "complete":
            return False
        fields = locate_fields(driver, image_xpath, submit_xpath)
        if any(field is None for field in fields):
            return False
        return bool(driver.execute_script(
            "return arguments[0].complete !== false && "
            "arguments[0].naturalWidth > 0 && arguments[0].naturalHeight > 0;",
            fields[3],
        ))
    except Exception:
        return False


def wait_stable_captcha(driver, image_xpath, submit_xpath, timeout, previous_image=None):
    """等圖片完成載入且連續兩次截圖相同，重試時也必須與前次不同。"""
    def stable(current):
        if not captcha_ready(current, image_xpath, submit_xpath):
            return False
        image = locate_fields(current, image_xpath, submit_xpath)[3]
        first = image.screenshot_as_png
        time.sleep(0.3)
        second = image.screenshot_as_png
        if first == second and second != previous_image:
            return second
        return False
    return WebDriverWait(driver, timeout, poll_frequency=0.2).until(
        stable, message="驗證碼圖片未完成載入，或重新整理後仍是上一張圖片。"
    )


def prepare_manual_login(driver, credentials, image_xpath=None, submit_xpath=None, timeout=20, previous_image=None):
    """填入帳密、辨識當前 CAPTCHA 並提交；回傳提交前的網址。"""
    image_bytes = wait_stable_captcha(
        driver, image_xpath, submit_xpath, timeout, previous_image
    )
    account_el, password_el, captcha_el, image_el, _submit_el = locate_fields(
        driver, image_xpath, submit_xpath
    )
    driver.save_screenshot(str(FULL_SCREENSHOT_PATH))
    CAPTCHA_PATH.write_bytes(image_bytes)
    
    captcha_text = ocr_engine.classification(image_bytes).strip().upper()
    print(f"辨識出的驗證碼：{captcha_text}", flush=True)
    replace_text(account_el, credentials[0])
    replace_text(password_el, credentials[1])
    replace_text(captcha_el, captcha_text)
    time.sleep(1)
    log(f"帳密已填入。完整登入頁截圖：{FULL_SCREENSHOT_PATH}")
    log(f"驗證碼截圖：{CAPTCHA_PATH}")
    login_url = driver.current_url
    _submit_el.click()
    return login_url, image_bytes


def prepare_user_captcha_login(driver, credentials, timeout=20):
    """填入已存帳密並等待使用者自行輸入 CAPTCHA、按登入。"""
    def fields_ready(current):
        return (bool(current.find_elements(By.XPATH, ACCOUNT_XPATH))
                and bool(current.find_elements(By.XPATH, PASSWORD_XPATH))
                and bool(current.find_elements(By.XPATH, CAPTCHA_INPUT_XPATH)))
    WebDriverWait(driver, timeout).until(
        fields_ready,
        message="無法定位登入欄位；請檢查 CloudOP 登入頁。",
    )
    account_el = first_visible(driver, (ACCOUNT_XPATH,))
    password_el = first_visible(driver, (PASSWORD_XPATH,))
    replace_text(account_el, credentials[0])
    replace_text(password_el, credentials[1])
    log("帳密已填入；請在 Chrome 手動輸入 CAPTCHA 並按登入。")

def wait_login_result(driver, timeout, initial_url=None):
    deadline = time.monotonic() + timeout
    if initial_url is None:
        initial_url = driver.current_url
    while time.monotonic() < deadline:
        try:
            alert = driver.switch_to.alert
            message = (alert.text or "").strip()
            alert.accept()
            log(f"網站提示：{message}")
            return False, message or "網站顯示空白提示"
        except NoAlertPresentException:
            pass
        except UnexpectedAlertPresentException:
            time.sleep(0.2)
            continue
        confirm = first_visible(driver, CONFIRM_XPATHS)
        if confirm is not None:
            message = driver.execute_script("""
                let node = arguments[0];
                for (let i = 0; node && i < 5; i++, node = node.parentElement) {
                    const value = (node.innerText || '').trim();
                    if (/驗證碼|驗証碼|圖形碼|captcha/i.test(value)) return value;
                }
                return '';
            """, confirm)
            # 指定的按鈕 ID 是網站驗證碼錯誤提示；其他「確定」須有錯誤文字。
            if message or confirm.get_attribute("id") == "92474869-a3db-4ee3-bbf7-44ec10512da4":
                confirm.click()
                message = message or "驗證碼錯誤"
                log(f"網站提示：{message}")
                return False, message
        try:
            if driver.current_url != initial_url:
                return True, ""
            # 登入後通常會導向系統頁；常見登入表單欄位消失也視為成功。
            if not driver.find_elements(By.XPATH, ACCOUNT_XPATH):
                return True, ""
        except UnexpectedAlertPresentException:
            time.sleep(0.2)
            continue
        time.sleep(0.2)
    return False, "登入結果等待逾時或驗證未通過"


def is_captcha_error(message):
    normalized = message.lower().replace(" ", "")
    return any(word in normalized for word in ("驗證碼", "驗証碼", "驗證(碼)", "圖形碼", "captcha"))


def allow_cloudop_local_network(driver):
    """為 CloudOP 網域授予舊版及新版 Chrome 的本機網路權限。"""
    # 新版 Chromium 將 Local Network Access 拆成 local-network 與
    # loopback-network；保留舊名稱以相容尚未拆分的版本。
    for permission_name in (
        "local-network-access",
        "local-network",
        "loopback-network",
    ):
        driver.execute_cdp_cmd("Browser.setPermission", {
            "permission": {"name": permission_name},
            "setting": "granted",
            "origin": "https://www.cloudop.tw",
        })


def rotate_previous_screenshots():
    """在新登入開始前保留上一輪截圖，並記錄沒有舊檔的情況。"""
    for current, previous in (
        (CAPTCHA_PATH, CAPTCHA_LAST_PATH),
        (FULL_SCREENSHOT_PATH, FULL_SCREENSHOT_LAST_PATH),
    ):
        if current.exists():
            current.replace(previous)
            log(f"已將上一輪截圖移至：{previous}")
        else:
            log(f"找不到上一輪截圖，未建立 {previous.name}：{current}")


def login(credentials, timeout=20, image_xpath=None, submit_xpath=None, allow_local_network=False, manual_captcha=False):
    if len(credentials) != 2 or not all(credentials):
        raise ValueError("請先選擇有效的帳號與密碼。")
    rotate_previous_screenshots()
    # 由 Selenium Manager 依本機 Chrome 版本取得相符的 ChromeDriver。
    driver = webdriver.Chrome()
    try:
        driver.maximize_window()
        if allow_local_network:
            # Chrome 141+ 將 Apps on Device（本機網路存取）設為網站權限提示。
            # 在開啟網站前只授權 CloudOP origin，避免提示阻擋之後的操作。
            allow_cloudop_local_network(driver)
            log("已預先允許 CloudOP 的本機網路與 loopback 權限（僅 https://www.cloudop.tw）。")
        driver.get(LOGIN_URL)
        if manual_captcha:
            prepare_user_captcha_login(driver, credentials, timeout)
        else:
            previous_image = None
            for attempt in range(3):  # 初次提交加上最多兩次重試
                initial_url, previous_image = prepare_manual_login(
                    driver, credentials, image_xpath, submit_xpath, timeout, previous_image
                )
                success, message = wait_login_result(driver, timeout, initial_url)
                if success:
                    log("登入成功。")
                    break
                if not is_captcha_error(message):
                    raise RuntimeError(f"CloudOP 登入失敗：{message}")
                if attempt == 2:
                    raise RuntimeError("驗證碼錯誤，已達最多兩次重試。")
                log(f"驗證碼錯誤，關閉提示後重新載入並辨識（重試 {attempt + 1}/2）。")
                driver.refresh()
        return driver
    except Exception:
        driver.quit()
        raise


def main():
    parser = argparse.ArgumentParser(description="Selenium + ddddocr CloudOP 登入程式")
    parser.add_argument("--hold", type=int, default=1800, help="保留登入頁/瀏覽器秒數（預設 1800）")
    parser.add_argument("--timeout", type=int, default=20, help="等待登入表單秒數")
    parser.add_argument("--captcha-image-xpath", help="覆寫驗證碼圖片 XPath")
    parser.add_argument("--submit-xpath", help="覆寫登入按鈕 XPath")
    args = parser.parse_args()
    from credential_store import load_accounts, migrate_plaintext
    migrate_plaintext()
    accounts = load_accounts()
    if len(accounts) != 1:
        parser.error("命令列登入需剛好一組帳號；多帳號請使用介面。")
    driver = login(next(iter(accounts.items())), args.timeout, image_xpath=args.captcha_image_xpath, submit_xpath=args.submit_xpath)
    try:
        log(f"保留瀏覽器 {max(0, args.hold)} 秒。")
        time.sleep(max(0, args.hold))
    finally:
        driver.quit()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"登入程式錯誤：{exc}", file=sys.stderr)
        raise SystemExit(1)
