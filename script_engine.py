import json
import math
import time

import win32clipboard
from pathlib import Path

from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from app_paths import DATA_DIR
FOLDER = DATA_DIR
RECORDER = r'''(() => {
 if (window.__docRecorder) return;
 window.__docRecorder = true; window.__docRecording = true;
 function path(el) {
   if (el.id && document.querySelectorAll('[id="' + CSS.escape(el.id) + '"]').length === 1)
     return '//*[@id=' + JSON.stringify(el.id) + ']';
   let parts = [];
   while (el && el.nodeType === 1) {
     let n = 1, s = el.previousElementSibling;
     while (s) { if (s.tagName === el.tagName) n++; s = s.previousElementSibling; }
     parts.unshift(el.tagName.toLowerCase() + '[' + n + ']'); el = el.parentElement;
   }
   return '/' + parts.join('/');
 }
 function record(obj) { console.error('__DOC_ACTION__' + JSON.stringify(obj)); }
 document.addEventListener('click', e => {
   if (window.__docRecording && e.isTrusted && e.target instanceof Element) record({action:'click', xpath:path(e.target)});
 }, true);
 let saved = new WeakMap();
 function saveInput(el) {
   if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return;
   if (['checkbox','radio','file','button','submit'].includes(el.type)) return;
   if (saved.get(el) === el.value) return;
   saved.set(el, el.value);
   record({action:'clear', xpath:path(el)});
   record({action:'send_keys', xpath:path(el), value:el.type === 'password' ? '${PIN}' : el.value});
 }
 document.addEventListener('paste', e => {
   if (!window.__docRecording || !e.isTrusted || !(e.target instanceof Element)) return;
   const el = e.target;
   if (!e.clipboardData || !e.clipboardData.types.includes('text/plain')) {
     record({action:'paste', xpath:path(el), value:'', error:'剪貼簿沒有可錄製的純文字'});
     return;
   }
   if ((el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) && el.value && saved.get(el) !== el.value)
     saveInput(el);
   record({action:'paste', xpath:path(el), value:el.type === 'password' ? '${PIN}' : e.clipboardData.getData('text/plain')});
   el.addEventListener('input', () => { saved.set(el, el.value); }, {once:true});
 }, true);
 document.addEventListener('change', e => {
   if (window.__docRecording && e.isTrusted) saveInput(e.target);
 }, true);
 document.addEventListener('keydown', e => {
   if (window.__docRecording && e.isTrusted && e.key === 'Enter' && e.target instanceof Element)
     { saveInput(e.target); record({action:'key', xpath:path(e.target), value:'ENTER'}); }
 }, true);
})();'''


def parse_script(content):
    steps = []
    for number, line in enumerate(content.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        try:
            step = json.loads(line)
            actions = ('click', 'clear', 'send_keys', 'paste', 'key', 'wait', 'wait_for')
            if not isinstance(step, dict) or step.get('action') not in actions:
                raise ValueError('需指定有效的 action')
            action = step['action']
            if action != 'wait' and (not isinstance(step.get('xpath'), str) or not step['xpath'].strip()):
                raise ValueError('需指定有效的 xpath')
            if 'name' in step and not isinstance(step['name'], str):
                raise ValueError('步驟名稱 name 必須是文字')
            if step.get('error'):
                raise ValueError(step['error'])
            if action in ('send_keys', 'paste', 'key') and not isinstance(step.get('value'), str):
                raise ValueError('需指定文字 value')
            if action == 'key' and step['value'].upper() not in ('ENTER', 'TAB', 'ESCAPE'):
                raise ValueError('key 僅支援 ENTER、TAB、ESCAPE')
            for key in ('seconds', 'timeout'):
                if key in step:
                    val = step[key]
                    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val < 0 or (key == 'timeout' and val == 0):
                        raise ValueError(f'{key} 必須是有效的非負秒數，timeout 須大於 0')
            if action == 'wait' and 'seconds' not in step:
                raise ValueError('wait 需指定 seconds')
            steps.append((number, step))
        except (ValueError, TypeError) as exc:
            raise ValueError(f'第 {number} 行格式錯誤：{exc}') from exc
    if not steps:
        raise ValueError('腳本沒有執行步驟。')
    return steps


def run_script(driver, content, count=1, pin=None, timeout=15, progress=None, start_cycle=1):
    steps = parse_script(content)
    if any(s.get('value') == '${PIN}' for _, s in steps) and pin is None:
        raise ValueError('腳本需要 PIN。')
    for cycle in range(start_cycle, start_cycle + count):
        for number, step in steps:
            try:
                action = step['action']
                if progress:
                    progress(cycle, number, step)
                if action == 'wait':
                    time.sleep(step['seconds'])
                    continue
                wait_seconds = step.get('timeout', timeout)
                def find_ready(d):
                    for element in d.find_elements(By.XPATH, step['xpath']):
                        try:
                            if element.is_displayed() and element.is_enabled():
                                return element
                        except StaleElementReferenceException:
                            continue
                    return False
                try:
                    element = WebDriverWait(driver, wait_seconds).until(find_ready)
                except TimeoutException as exc:
                    raise TimeoutError(f'等待元件逾時（{wait_seconds} 秒），XPath：{step["xpath"]}') from exc
                if action == 'wait_for': continue
                if action == 'click': element.click()
                elif action == 'clear': element.clear()
                elif action == 'send_keys': element.send_keys(pin if step['value'] == '${PIN}' else step['value'])
                elif action == 'paste': paste_text(element, pin if step['value'] == '${PIN}' else step['value'])
                else: element.send_keys(getattr(Keys, step['value'].upper()))
            except Exception as exc:
                label = step.get('name') or step['action']
                raise RuntimeError(f'第 {cycle} 次、第 {number} 行（{label}）失敗：{exc}') from exc


def paste_text(element, value):
    """Replace the clipboard with the exact script text before pasting."""
    element.click()
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(value, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()
    element.send_keys(Keys.CONTROL, 'v')


def click_list(driver, label):
    xpath = '//*[@id="divItemCount"]//*[self::a or self::h5 or self::button or self::span]'
    def locate(d):
        return next((e for e in d.find_elements(By.XPATH, xpath) if label in e.text and e.is_displayed() and e.is_enabled()), False)
    WebDriverWait(driver, 15).until(locate).click()


def start_recording(driver):
    result = driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': RECORDER})
    driver.execute_script(RECORDER + '; window.__docRecording = true;')
    driver.get_log('browser')
    return result['identifier']


def read_recording(driver):
    actions = []
    for entry in driver.get_log('browser'):
        message = entry.get('message', '')
        marker = '__DOC_ACTION__'
        if marker not in message:
            continue
        try:
            quoted = message[message.index('"' + marker):]
            payload = json.loads(quoted)
            actions.append(json.loads(payload[len(marker):]))
        except (ValueError, TypeError):
            continue
    return actions


def stop_recording(driver, identifier):
    driver.execute_cdp_cmd('Page.removeScriptToEvaluateOnNewDocument', {'identifier': identifier})
    driver.execute_script('window.__docRecording = false;')

