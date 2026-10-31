"""本機 Chrome 回歸測試；不連線 CloudOP、不操作正式公文。"""
import builtins
import importlib.util
from pathlib import Path
import tempfile
import time
import sys
from unittest.mock import Mock, patch
from urllib.parse import quote

from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException, StaleElementReferenceException, ElementClickInterceptedException,
)
from selenium.webdriver.common.by import By


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('notice', ROOT / '公告週知.py')
notice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notice)


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', errors='replace')
    # 只對明確未點擊成功的重繪／遮罩錯誤重試，不重送已成功的簽章。
    for error in (StaleElementReferenceException, ElementClickInterceptedException):
        old, fresh = Mock(), Mock()
        old.click.side_effect = error('page transition')
        with patch.object(notice, '_wait', side_effect=[
            ('xpath', old, 'old'), ('xpath', fresh, 'fresh'),
        ]):
            notice._click(Mock(), '確認', timeout=1)
        assert old.click.call_count == fresh.click.call_count == 1
    print('PASS: stale element and overlay retries without duplicate successful clicks')
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--window-size=1280,900')
    driver = webdriver.Chrome(options=options)
    try:
        # 大量無關節點、隱藏重名按鈕、延遲渲染及兩次簽章。
        html = '''<meta charset="utf-8"><div style="display:none"><button>確認</button></div>
        <div id="app"></div><div id="noise"></div><script>
        window.actions=[];
        window.pinEnterCount=0;
        document.addEventListener('keydown', event => {
          if(event.key==='Enter' && event.target.id==='pin') {
            if(event.target.value!=='0001234') throw Error('incorrect PIN on Enter');
            window.pinEnterCount++;
          }
        });
        document.getElementById('noise').innerHTML='<div>無關內容</div>'.repeat(3000);
        function show(n) {
          const ids=['menu','add','simple','addsimple','sign','confirm','tech','flow','sign','template','selectfirst','send'];
          const labels=['文書檔案','新增','簡簽','新增','簽章','確認','技術服務','確定','簽章','流程範本','選取','送出'];
          if(n===12){ document.getElementById('app').innerHTML='<input id="pin" type="password" value="old"><button onclick="actions.push(99)">確認 PIN</button><button id="nextdoc" onclick="actions.push(12)">前往下一筆</button>'; return; }
          document.getElementById('app').innerHTML=(n===4 ? '<div id="item" contenteditable="true"></div>' : '')
            + (n===9 ? '公文流程：已選擇流程範本' : '')
            + '<button id="'+ids[n]+'" onclick="go('+n+')"><span>'+labels[n]+'</span></button>';
          if(n===10) document.getElementById('app').innerHTML+='<button onclick="actions.push(98)">選取</button>';
        }
        function go(n) {
          if(n===4 && !document.getElementById('item').innerText.includes('擬公告網站週知。')) throw Error('missing text');
          actions.push(n);
          document.getElementById('app').innerHTML='載入中';
          setTimeout(()=>show(n+1), 200);
        }
        show(0);
        </script>'''
        driver.get('data:text/html;charset=utf-8,' + quote(html))
        constants = dict(
            MENU_XPATH='menu', ADD_XPATH='add', SIMPLE_SIGN_XPATH='simple',
            ADD_SIMPLE_SIGN_XPATH='addsimple', FIRST_ITEM_XPATH='item',
            SIGN_XPATH='sign', SIGN_CONFIRM_XPATH='confirm',
            TECH_SERVICE_XPATH='missing-tech', FLOW_CONFIRM_XPATH='flow',
            FLOW_TEMPLATE_XPATH='template', FIRST_TEMPLATE_SELECT_XPATH='selectfirst',
            FLOW_SEND_XPATH='send', PIN_INPUT_XPATH='pin',
            NEXTDOC_XPATH='nextdoc',
        )
        for key, value in constants.items():
            setattr(notice, key, f'//*[@id="{value}"]')
        with tempfile.TemporaryDirectory() as directory:
            notice.PIN_PATH = Path(directory) / 'pin.txt'
            notice.PIN_PATH.write_text('0001234\n', encoding='utf-8-sig')
            for name in vars(notice).copy():
                if name.endswith('SCREENSHOT_PATH'):
                    setattr(notice, name, Path(directory) / (name + '.png'))
            started = time.monotonic()
            with patch.object(builtins, 'input', side_effect=AssertionError('不得要求人工 Enter')):
                notice.run_steps(driver)
            assert driver.execute_script('return actions') == list(range(13))
            assert driver.find_element(By.ID, 'pin').get_attribute('value') == '0001234'
            assert driver.execute_script('return pinEnterCount') == 1
            assert len(list(Path(directory).glob('*.png'))) == 0
            print(f'PASS: delayed full flow, text fallback, no screenshots, no input; {time.monotonic()-started:.2f}s')
            print('PASS: first template only, PIN file BOM/leading zeros, replaces old value, exactly one Enter after PIN')
            for value in ('', '\n', '123\n456'):
                notice.PIN_PATH.write_text(value, encoding='utf-8')
                untouched_driver = Mock()
                try:
                    notice.run_steps(untouched_driver)
                    raise AssertionError('invalid PIN file must stop flow')
                except ValueError:
                    assert not untouched_driver.mock_calls
            notice.PIN_PATH.unlink()
            try:
                notice._read_pin()
                raise AssertionError('missing PIN file must fail')
            except RuntimeError:
                pass
            print('PASS: missing/empty/multiline PIN fails before document actions')
            # 後續輪次不顯示 PIN 視窗，且設定檔不存在，也應直接完成。
            no_pin_html = html.replace(
                '<input id="pin" type="password" value="old">',
                '本輪不需 PIN',
            )
            driver.get('data:text/html;charset=utf-8,' + quote(no_pin_html))
            with patch.object(notice, '_read_pin', side_effect=AssertionError('不得讀取 PIN')):
                with patch.object(builtins, 'input', side_effect=AssertionError('不得要求 Enter')):
                    notice.run_steps(driver, wait_for_pin=False)
            assert driver.execute_script('return actions') == list(range(13))
            assert not driver.find_elements(By.ID, 'pin')
            assert driver.execute_script('return pinEnterCount') == 0
            print('PASS: later round completes without PIN file, dialog, or input')

        # 文字 fallback 不讀取 3000 個無關節點，且跳過隱藏同名元素。
        driver.execute_script("document.getElementById('app').innerHTML='<button><span>確認</span></button>'")
        started = time.monotonic()
        target = notice._wait(driver, '確認', xpath='//*[@id="missing"]', exact=True)
        elapsed = time.monotonic() - started
        assert target[0] == 'text-search' and target[1].is_displayed()
        assert elapsed < 5, f'text lookup too slow: {elapsed:.2f}s'
        print(f'PASS: 3000 unrelated nodes + hidden duplicate; lookup={elapsed:.3f}s')

        # 含兩種引號的標籤也必須能安全產生 XPath。
        label = '''測試'與"引號'''
        driver.execute_script("document.getElementById('app').textContent=arguments[0]", label)
        assert notice._find_text(driver, label, exact=True)[1] == label
        print('PASS: quoted XPath label')
        started = time.monotonic()
        try:
            notice._wait(driver, '不存在的按鈕', exact=True, timeout=0.5)
            raise AssertionError('missing target must time out')
        except TimeoutException:
            assert time.monotonic() - started < 2
        print('PASS: missing target timeout')
        driver.execute_script("document.getElementById('app').innerHTML='<button>選取</button>'")
        try:
            notice._click(driver, '選取', xpath='//*[@id="missing-first-row"]',
                          text_fallback=False, timeout=0.5)
            raise AssertionError('must not select another template')
        except TimeoutException:
            pass
        print('PASS: missing first-row XPath cannot fall back to another selection')
    finally:
        driver.quit()


if __name__ == '__main__':
    main()
