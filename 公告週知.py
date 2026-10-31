"""CloudOP 公告週知的正式流程模組。

執行前請確認目前第一則公文正是要處理的文件。流程中的簽章/PIN
操作會依設定執行，不會等待人工輸入 Enter。
"""
import time
from pathlib import Path

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

import cloudop_login
import enterFirstDoc


MENU_XPATH = '//*[@id="roeApp"]/div[1]/header/div[2]/div[1]/button/span'
ADD_XPATH = '//*[@id="roeApp"]/div[1]/header/div[2]/div[1]/div/a[1]'
SIMPLE_SIGN_XPATH = ('//*[@id="roeApp"]/div[1]/div[10]/div/div/div[2]/div/div/div[2]'
                     '/table/tbody/tr[2]/td[4]/div')
ADD_SIMPLE_SIGN_XPATH = '//*[@id="roeApp"]/div[1]/div[10]/div/div/div[2]/div[2]/button'
FIRST_ITEM_XPATH = '//*[@id="擬辦"]/div[2]/div/div[2]'
SIGN_XPATH = '//*[@id="roeApp"]/div[1]/main/div[3]/div[1]/div/div[2]/div[2]/div[2]/button[2]'
SIGN_CONFIRM_XPATH = '/html/body/div[2]/div/div[3]/button[1]'
TECH_SERVICE_XPATH = '//*[@id="roeApp"]/div[1]/div[10]/div/div/div[2]/div[2]/table/tbody/tr[3]/td[2]/div'
FLOW_CONFIRM_XPATH = '//*[@id="roeApp"]/div[1]/div[10]/div/div/div[2]/div[3]/button'
FLOW_TEMPLATE_XPATH = '//*[@id="roeApp"]/div[1]/div[10]/div/div/div[2]/div/div[1]/div[1]/div[1]/button'
FIRST_TEMPLATE_SELECT_XPATH = '//*[@id="roeApp"]/div[1]/div[10]/div/div/div[2]/div/div[1]/div/table/tbody/tr[1]/td[3]/button'
FLOW_SEND_XPATH = '//*[@id="roeApp"]/div[1]/div[10]/div/div/div[2]/div/div[2]/div/button'
PIN_INPUT_XPATH = '/html/body/div[2]/div/div[2]/input[1]'
NEXTDOC_XPATH = '/html/body/div[2]/div/div[3]/button[3]'
PIN_PATH = Path(__file__).with_name('pin.txt')


def _visible_enabled(element):
    try:
        return element.is_displayed() and element.is_enabled()
    except Exception:
        return False


def _xpath_literal(value):
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return "concat(" + ', "\'", '.join("'" + part + "'" for part in value.split("'")) + ")"


def _find_text(driver, label, exact=False):
    literal = _xpath_literal(label)
    condition = f"normalize-space(.)={literal}" if exact else f"contains(normalize-space(.), {literal})"
    nodes = driver.find_elements(
        By.XPATH,
        "//*[self::button or self::a or self::span or self::div or self::td]"
        f"[{condition}][not(.//*[{condition}])]",
    )
    matches = []
    for node in nodes:
        try:
            text = " ".join((node.text or "").split())
            if (text == label if exact else label in text) and _visible_enabled(node):
                matches.append((len(text), node, text))
        except StaleElementReferenceException:
            continue
    return min(matches, default=(None, None, None), key=lambda row: row[0] or 0)[1:]


def _target(driver, label, xpath=None, exact=False, text_fallback=True):
    try:
        if xpath:
            for element in driver.find_elements(By.XPATH, xpath):
                if _visible_enabled(element):
                    return ("xpath", element, xpath)
        if text_fallback:
            element, text = _find_text(driver, label, exact)
            if element is not None:
                return ("text-search", element, text)
    except StaleElementReferenceException:
        return False
    return False


def _wait(driver, label, xpath=None, exact=False, timeout=12, text_fallback=True):
    return WebDriverWait(driver, timeout, poll_frequency=0.15).until(
        lambda current: _target(current, label, xpath, exact, text_fallback),
        message=f"找不到可操作的「{label}」",
    )


def _click(driver, label, xpath=None, exact=False, timeout=12, text_fallback=True):
    deadline = time.monotonic() + timeout
    while True:
        remain = deadline - time.monotonic()
        if remain <= 0:
            raise TimeoutError(f"等待點擊「{label}」逾時。")
        method, element, detail = _wait(
            driver, label, xpath, exact, remain, text_fallback
        )
        try:
            element.click()
            cloudop_login.log(f"已點擊「{label}」({method})。")
            return
        except (StaleElementReferenceException, ElementClickInterceptedException):
            time.sleep(min(0.08, max(0, deadline - time.monotonic())))


def _type_first_item(driver, value):
    _, item, _ = _wait(driver, "擬辦第一項", FIRST_ITEM_XPATH)
    editor = item
    if (item.get_attribute("contenteditable") or "").lower() != "true":
        children = item.find_elements(
            By.XPATH, ".//*[@contenteditable='true'] | .//textarea | .//input"
        )
        if children:
            editor = children[0]
    editor.click()
    editor.send_keys(value)
    WebDriverWait(driver, 5, poll_frequency=0.15).until(
        lambda _: value in ((editor.get_attribute("value") or "")
                            + (editor.get_attribute("innerText") or "")
                            + (editor.text or "")),
        message="擬辦第一項未確認到輸入文字。",
    )


def _read_pin():
    try:
        pin = PIN_PATH.read_text(encoding="utf-8-sig").strip()
    except OSError:
        raise RuntimeError("找不到 pin.txt，尚未開始公文操作。") from None
    if not pin or len(pin.splitlines()) != 1:
        raise ValueError("pin.txt 必須包含一行非空白 PIN。")
    return pin


def _flow_and_pin(driver, pin):
    _click(driver, "流程範本", FLOW_TEMPLATE_XPATH, text_fallback=False)
    _click(driver, "第一個選取", FIRST_TEMPLATE_SELECT_XPATH, text_fallback=False)
    WebDriverWait(driver, 10, poll_frequency=0.15).until(
        lambda current: any(_visible_enabled(item) for item in current.find_elements(
            By.XPATH, FLOW_SEND_XPATH
        )),
        message="流程範本選取後送出按鈕尚未就緒。",
    )
    _click(driver, "送出", FLOW_SEND_XPATH, text_fallback=False)
    
    field = WebDriverWait(driver, 12, poll_frequency=0.15).until(
        lambda current: next((e for e in current.find_elements(By.XPATH, PIN_INPUT_XPATH)
                              if _visible_enabled(e)), False),
        message="等待 PIN 輸入欄位逾時。",
    )
    field.clear()
    field.send_keys(pin)
    WebDriverWait(driver, 5, poll_frequency=0.15).until(
        lambda current: current.find_element(By.XPATH, PIN_INPUT_XPATH).get_attribute("value") == pin,
        message="PIN 欄位輸入未完成。",
    )
    field.send_keys(Keys.ENTER)
    cloudop_login.log("已填入 PIN 並由 Selenium 送出 Enter。")


def run_steps(driver, wait_for_pin=True):
    """在已開啟的公文上執行公告週知步驟；不建立第二個 driver。"""
    pin = _read_pin() if wait_for_pin else None
    driver.maximize_window()
    driver.implicitly_wait(0)

    _click(driver, "文書檔案", MENU_XPATH)
    _click(driver, "新增", ADD_XPATH, exact=True)
    _click(driver, "簡簽", SIMPLE_SIGN_XPATH)
    _click(driver, "新增", ADD_SIMPLE_SIGN_XPATH, exact=True)
    _wait(driver, "擬辦第一項", FIRST_ITEM_XPATH, timeout=12)
    cloudop_login.log("簡簽編輯畫面已開啟。")

    _type_first_item(driver, "擬公告網站週知。")
    _click(driver, "簽章", SIGN_XPATH)
    _wait(driver, "確認", SIGN_CONFIRM_XPATH, exact=True, timeout=10)
    _click(driver, "確認", SIGN_CONFIRM_XPATH, exact=True)

    _click(driver, "技術服務", TECH_SERVICE_XPATH)
    _click(driver, "確定", FLOW_CONFIRM_XPATH, exact=True)
    _click(driver, "簽章", SIGN_XPATH)
    WebDriverWait(driver, 20, poll_frequency=0.2).until(
        lambda current: ("公文流程" in current.find_element(By.TAG_NAME, "body").text
                         or "目前無設定流程請設定流程" in current.find_element(By.TAG_NAME, "body").text),
        message="簽章後未出現流程設定畫面。",
    )
    body = driver.find_element(By.TAG_NAME, "body").text
    if "目前無設定流程請設定流程" in body:
        raise RuntimeError("系統提示目前無設定流程；停止後續流程送出。")
    if wait_for_pin:
        _flow_and_pin(driver, pin)
    else:
        _click(driver, "流程範本", FLOW_TEMPLATE_XPATH, text_fallback=False)
        _click(driver, "第一個選取", FIRST_TEMPLATE_SELECT_XPATH, text_fallback=False)
        _click(driver, "送出", FLOW_SEND_XPATH, text_fallback=False)
#     _click(driver, "前往下一筆", NEXTDOC_XPATH, exact=True)


def run(wait_for_pin=True):
    if wait_for_pin:
        _read_pin()
    return enterFirstDoc.enter_first_doc(
        after_first_doc=lambda driver: run_steps(driver, wait_for_pin=wait_for_pin)
    )


if __name__ == "__main__":
    run()
