import json
import ctypes
import math
import time

import win32clipboard
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

FOLDER = Path(__file__).resolve().parent
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


def run_script(driver, content, count=1, pin=None, timeout=5, progress=None, start_cycle=1):
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
                element = WebDriverWait(driver, step.get('timeout', timeout)).until(
                    lambda d: next((e for e in d.find_elements(By.XPATH, step['xpath']) if e.is_displayed() and e.is_enabled()), False))
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
    """Save clipboard data before temporarily replacing it with paste text."""
    user32 = ctypes.windll.user32
    kernel = ctypes.windll.kernel32
    kernel.GlobalSize.argtypes = [ctypes.c_void_p]
    kernel.GlobalSize.restype = ctypes.c_size_t
    kernel.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = ctypes.c_void_p
    kernel.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    backup = []
    win32clipboard.OpenClipboard()
    try:
        fmt = 0
        while True:
            fmt = win32clipboard.EnumClipboardFormats(fmt)
            if not fmt:
                break
            # GDI and metafile handles are not global memory and cannot be copied safely here.
            if fmt in (2, 3, 9, 14):
                raise RuntimeError('剪貼簿包含圖片或其他無法安全還原的格式；請先複製純文字再執行。')
            handle = user32.GetClipboardData(fmt)
            size = kernel.GlobalSize(handle) if handle else 0
            ptr = kernel.GlobalLock(handle) if size else None
            if not ptr:
                raise RuntimeError(f'無法備份剪貼簿格式 {fmt}，已停止貼上。')
            try:
                backup.append((fmt, ctypes.string_at(ptr, size)))
            finally:
                kernel.GlobalUnlock(handle)
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(value, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()
    try:
        element.click()
        element.send_keys(Keys.CONTROL, 'v')
    finally:
        win32clipboard.OpenClipboard()
        try:
            unchanged = (win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT) and
                         win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) == value)
            if unchanged:
                win32clipboard.EmptyClipboard()
                for fmt, data in backup:
                    handle = kernel.GlobalAlloc(2, len(data))
                    if not handle:
                        raise RuntimeError('還原剪貼簿時記憶體不足。')
                    ptr = kernel.GlobalLock(handle)
                    if not ptr:
                        kernel.GlobalFree(handle)
                        raise RuntimeError('無法還原剪貼簿。')
                    ctypes.memmove(ptr, data, len(data))
                    kernel.GlobalUnlock(handle)
                    if not user32.SetClipboardData(fmt, handle):
                        kernel.GlobalFree(handle)
                        raise RuntimeError(f'無法還原剪貼簿格式 {fmt}。')
        finally:
            win32clipboard.CloseClipboard()


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

