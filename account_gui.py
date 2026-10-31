"""多帳號 CloudOP 登入介面。"""
import threading
import tkinter as tk
from tkinter import messagebox, ttk, simpledialog
import json
import time
import enterFirstDoc
import script_engine

import cloudop_login
from credential_store import load_accounts, migrate_plaintext, save_accounts


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("公文小幫手：帳號登入")
        self.root.resizable(False, False)
        self.driver = None
        self.pin_entered = tk.BooleanVar(value=False)
        self.busy = False
        self.record_state = "idle"
        self.record_toggle = threading.Event()
        self.accounts = load_accounts()
        imported = migrate_plaintext()
        self.accounts = load_accounts()
        frame = ttk.Frame(root, padding=16)
        frame.grid()
        ttk.Label(frame, text="選擇帳號").grid(row=0, column=0, sticky="w")
        self.choice = ttk.Combobox(frame, width=29, state="readonly")
        self.choice.grid(row=0, column=1, columnspan=2, padx=8)
        self.choice.bind("<<ComboboxSelected>>", self.select_account)
        ttk.Label(frame, text="帳號").grid(row=1, column=0, sticky="w", pady=8)
        self.account = ttk.Entry(frame, width=32)
        self.account.grid(row=1, column=1, columnspan=2, padx=8)
        ttk.Label(frame, text="密碼").grid(row=2, column=0, sticky="w")
        self.password = ttk.Entry(frame, width=32, show="*")
        self.password.grid(row=2, column=1, columnspan=2, padx=8)
        self.save_button = ttk.Button(frame, text="新增／更新", command=self.save)
        self.save_button.grid(row=3, column=0, pady=12)
        self.delete_button = ttk.Button(frame, text="刪除", command=self.delete)
        self.delete_button.grid(row=3, column=1)
        self.login_button = ttk.Button(frame, text="登入", command=self.login)
        self.login_button.grid(row=3, column=2)
        self.status = tk.StringVar(value=f"已匯入 {imported} 組帳密，請選擇帳號。" if imported else "請選擇帳號。")
        ttk.Label(frame, textvariable=self.status, wraplength=340).grid(row=4, column=0, columnspan=3, sticky="w")
        actions = ttk.LabelFrame(frame, text="公文操作", padding=8)
        actions.grid(row=5, column=0, columnspan=3, sticky="ew", pady=8)
        self.counts = {}
        self.action_buttons = []
        for row, (label, method) in enumerate([
            ("點選主辦公文", self.main_docs), ("點選第一則主辦公文", self.first_doc),
            ("公告週知", self.run_named), ("送歸存檔", self.run_named),
            ("點選會辦公文", self.countersign_docs), ("點選第一則會辦公文", self.first_doc),
            ("自動會辦", self.run_named)]):
            button = ttk.Button(actions, text=label)
            button.grid(row=row, column=0, sticky="ew", pady=2)
            self.action_buttons.append(button)
            if method == self.run_named:
                button.configure(command=self.named_command(label))
                count = ttk.Entry(actions, width=6)
                count.insert(0, "1")
                count.grid(row=row, column=1, padx=5)
                ttk.Label(actions, text="次").grid(row=row, column=2)
                self.counts[label] = count
            else:
                button.configure(command=method)
        self.pin_checkbox = ttk.Checkbutton(actions, text="已輸入 PIN", variable=self.pin_entered)
        self.pin_checkbox.grid(row=7, column=0, sticky="w", pady=2)
        ttk.Button(actions, text="腳本編輯／錄製", command=self.open_editor).grid(row=8, column=0, sticky="ew", pady=5)
        self.editor = None
        self.record_stop = threading.Event()
        self.refresh()
        self.update_buttons()
        root.update_idletasks()
        root.geometry(f"+{max(0, root.winfo_screenwidth() - root.winfo_width())}+0")
        root.protocol("WM_DELETE_WINDOW", self.close)

    def refresh(self, selected=""):
        self.choice["values"] = sorted(self.accounts)
        if selected in self.accounts:
            self.choice.set(selected)
            self.select_account()
        else:
            self.choice.set("")
            self.account.delete(0, tk.END)
            self.password.delete(0, tk.END)

    def select_account(self, event=None):
        name = self.choice.get()
        self.account.delete(0, tk.END)
        self.account.insert(0, name)
        self.password.delete(0, tk.END)

    def save(self):
        name, password = self.account.get().strip(), self.password.get()
        if not name or not password:
            messagebox.showerror("資料不足", "請輸入帳號和密碼。")
            return
        original = self.choice.get()
        updated = dict(self.accounts)
        if original and original != name:
            updated.pop(original, None)
        updated[name] = password
        try:
            save_accounts(updated)
            self.accounts = load_accounts()
            self.refresh(name)
            self.status.set(f"已加密儲存帳號：{name}")
        except Exception as exc:
            messagebox.showerror("儲存失敗", str(exc))

    def delete(self):
        name = self.choice.get()
        if not name or not messagebox.askyesno("刪除帳號", f"確定刪除 {name}？"):
            return
        updated = dict(self.accounts)
        updated.pop(name)
        try:
            save_accounts(updated)
            self.accounts = load_accounts()
            self.refresh()
            self.status.set(f"已刪除帳號：{name}")
        except Exception as exc:
            messagebox.showerror("刪除失敗", str(exc))

    def login(self):
        name = self.choice.get()
        if self.busy or name not in self.accounts:
            self.status.set("請先選擇已儲存的帳號。")
            return
        if self.driver:
            self.status.set("目前已有登入的瀏覽器；請先關閉程式再重新登入。")
            return
        self.busy = True
        self.update_buttons()
        self.status.set(f"正在登入 {name}，請稍候……")
        threading.Thread(target=self.login_worker, args=(name, self.accounts[name]), daemon=True).start()

    def login_worker(self, name, password):
        try:
            driver = cloudop_login.login((name, password), allow_local_network=True)
            self.root.after(0, self.login_success, name, driver)
        except Exception as exc:
            self.root.after(0, self.login_failed, str(exc))

    def login_success(self, name, driver):
        self.driver = driver
        self.busy = False
        self.status.set(f"{name} 已登入成功，Chrome 保持開啟。")
        self.update_buttons()

    def login_failed(self, error):
        self.busy = False
        self.update_buttons()
        self.status.set(f"登入失敗：{error}")

    def named_command(self, name):
        from functools import partial
        return partial(self.run_named, name)

    def work(self, label, operation):
        if self.busy:
            messagebox.showinfo("執行中", "請等待目前工作完成。")
            return
        if not self.driver:
            messagebox.showinfo("尚未登入", "請先登入。")
            return
        self.busy = True
        self.update_buttons()
        self.status.set(f"正在執行：{label}")
        def worker():
            try:
                operation()
                self.root.after(0, self.work_done, f"已完成：{label}")
            except Exception as exc:
                self.root.after(0, self.work_done, f"{label}失敗：{exc}")
        threading.Thread(target=worker, daemon=True).start()

    def work_done(self, message):
        self.busy = False
        self.record_state = "idle"
        self.update_buttons()
        if message != "已完成：錄製":
            self.status.set(message)
        if "失敗" in message:
            messagebox.showerror("執行失敗", message)

    def progress(self, cycle, number, step):
        name = step.get("name") or step["action"]
        self.root.after(0, self.status.set, f"第 {cycle} 次、第 {number} 行：{name}")

    def main_docs(self):
        self.work("主辦公文", lambda: script_engine.click_list(self.driver, "主辦公文"))

    def countersign_docs(self):
        self.work("會辦公文", lambda: script_engine.click_list(self.driver, "會辦公文"))

    def first_doc(self):
        self.work("第一則公文", lambda: enterFirstDoc.click_first_document(self.driver, timeout=15))

    def get_pin(self, content):
        if any(step.get("value") == "${PIN}" for _, step in script_engine.parse_script(content)):
            return simpledialog.askstring("PIN", "請輸入 PIN：", show="*", parent=self.root)
        return ""

    def run_content(self, label, content, count):
        try:
            pin = self.get_pin(content)
        except ValueError as exc:
            messagebox.showerror("腳本錯誤", str(exc))
            return
        if pin is None:
            return
        self.work(label, lambda: script_engine.run_script(self.driver, content, count, pin, progress=self.progress))

    def run_named(self, name):
        try:
            count = int(self.counts[name].get())
            if count < 1:
                raise ValueError("次數必須是大於零的整數。")
            track_pin = name in ("公告週知", "自動會辦")
            use_first = not track_pin or not self.pin_entered.get()
            first = (script_engine.FOLDER / (name + "_要輸入pin.script")).read_text(encoding="utf-8-sig") if use_first else None
            remaining = count - (1 if use_first else 0)
            later = (script_engine.FOLDER / (name + ".script")).read_text(encoding="utf-8-sig") if remaining else None
            for content in (first, later):
                if content is not None:
                    script_engine.parse_script(content)
            pin = self.get_pin("\n".join(content for content in (first, later) if content is not None))
        except (OSError, ValueError) as exc:
            messagebox.showerror("無法執行", str(exc))
            return
        if pin is None:
            return
        def run_sequence():
            if first is not None:
                script_engine.run_script(self.driver, first, 1, pin, progress=self.progress)
                if track_pin:
                    self.root.after(0, self.pin_entered.set, True)
            if later is not None:
                script_engine.run_script(self.driver, later, remaining, pin, progress=self.progress, start_cycle=2 if use_first else 1)
        self.work(name, run_sequence)

    def open_editor(self):
        if self.editor and self.editor.winfo_exists():
            self.editor.lift()
            return
        self.editor = tk.Toplevel(self.root)
        self.editor.title("腳本編輯／錄製")
        self.script_name = ttk.Combobox(self.editor, values=["公告週知_要輸入pin", "公告週知", "送歸存檔_要輸入pin", "送歸存檔", "自動會辦_要輸入pin", "自動會辦"], state="readonly")
        self.script_name.set("公告週知_要輸入pin")
        self.script_name.pack(fill="x", padx=8, pady=5)
        text_frame = ttk.Frame(self.editor)
        text_frame.pack(fill="both", expand=True, padx=8)
        self.line_numbers = tk.Canvas(text_frame, width=48, highlightthickness=0, background="#eeeeee")
        self.line_numbers.pack(side="left", fill="y")
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self.script_text = tk.Text(text_frame, width=85, height=22, undo=True, wrap="none", yscrollcommand=self.text_scrolled)
        self.script_text.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.script_text.yview)
        horizontal = ttk.Scrollbar(self.editor, orient="horizontal", command=self.script_text.xview)
        horizontal.pack(fill="x", padx=8)
        self.script_text.configure(xscrollcommand=horizontal.set)
        self.script_text.bind("<<Modified>>", self.text_modified)
        self.script_text.bind("<Configure>", self.draw_lines)
        naming = ttk.Frame(self.editor)
        naming.pack(fill="x", padx=8, pady=5)
        ttk.Label(naming, text="所選步驟名稱").pack(side="left")
        self.step_name = ttk.Entry(naming)
        self.step_name.pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(naming, text="設定名稱", command=self.set_step_name).pack(side="left")
        self.script_text.bind("<ButtonRelease-1>", self.select_step)
        buttons = ttk.Frame(self.editor)
        buttons.pack(fill="x", padx=8, pady=8)
        self.editor_buttons = {}
        for label, command in [("載入", self.load_script), ("儲存", self.save_script),
                               ("執行一次", self.run_editor), ("開始錄製", self.record_start),
                               ("暫停錄製", self.record_pause), ("停止錄製", self.record_end)]:
            button = ttk.Button(buttons, text=label, command=command)
            button.pack(side="left", padx=3)
            self.editor_buttons[label] = button
        self.editor.protocol("WM_DELETE_WINDOW", self.close_editor)
        self.load_script()
        self.update_buttons()
        self.editor.after_idle(self.draw_lines)

    def update_buttons(self):
        def enabled(widget, value):
            widget.state(["!disabled" if value else "disabled"])
        enabled(self.login_button, not self.busy and self.driver is None)
        for widget in (self.save_button, self.delete_button, self.account, self.password, self.choice):
            enabled(widget, not self.busy)
        for button in self.action_buttons:
            enabled(button, not self.busy and self.driver is not None)
        enabled(self.pin_checkbox, not self.busy and self.driver is not None)
        if self.editor and self.editor.winfo_exists():
            for label in ("載入", "儲存"):
                enabled(self.editor_buttons[label], not self.busy)
            enabled(self.editor_buttons["執行一次"], not self.busy and self.driver is not None)
            enabled(self.editor_buttons["開始錄製"], not self.busy and self.driver is not None)
            enabled(self.editor_buttons["暫停錄製"], self.record_state in ("recording", "paused"))
            enabled(self.editor_buttons["停止錄製"], self.record_state in ("recording", "paused"))
            self.editor_buttons["暫停錄製"].configure(text="繼續錄製" if self.record_state == "paused" else "暫停錄製")
            self.script_name.state(["disabled" if self.busy else "!disabled", "readonly"])

    def text_scrolled(self, first, last):
        if hasattr(self, "script_text"):
            self.script_text.after_idle(self.draw_lines)
        if hasattr(self, "editor") and self.editor and self.editor.winfo_exists():
            for widget in self.script_text.master.winfo_children():
                if isinstance(widget, ttk.Scrollbar):
                    widget.set(first, last)

    def text_modified(self, event=None):
        if self.script_text.edit_modified():
            self.script_text.edit_modified(False)
            self.draw_lines()

    def draw_lines(self, event=None):
        if not self.editor or not self.editor.winfo_exists():
            return
        canvas = self.line_numbers
        canvas.delete("all")
        index = self.script_text.index("@0,0")
        while True:
            info = self.script_text.dlineinfo(index)
            if not info:
                break
            canvas.create_text(42, info[1], anchor="ne", text=index.split(".")[0], fill="#666666", font=self.script_text.cget("font"))
            next_index = self.script_text.index(index + "+1line")
            if next_index == index:
                break
            index = next_index

    def select_step(self, event=None):
        line = self.script_text.index("insert").split(".")[0]
        try:
            step = json.loads(self.script_text.get(line + ".0", line + ".end"))
            name = step.get("name", "") if isinstance(step, dict) else ""
        except (ValueError, TypeError):
            name = ""
        self.step_name.delete(0, tk.END)
        self.step_name.insert(0, name)

    def set_step_name(self):
        line = self.script_text.index("insert").split(".")[0]
        try:
            step = json.loads(self.script_text.get(line + ".0", line + ".end"))
            if not isinstance(step, dict) or "action" not in step:
                raise ValueError("請先在文字框選取一行有效的步驟。")
            step["name"] = self.step_name.get().strip()
        except (ValueError, TypeError) as exc:
            messagebox.showerror("無法設定名稱", str(exc), parent=self.editor)
            return
        self.script_text.delete(line + ".0", line + ".end")
        self.script_text.insert(line + ".0", json.dumps({"name": step.get("name", ""), **step}, ensure_ascii=False))
        self.script_text.mark_set("insert", line + ".0")

    def load_script(self):
        path = script_engine.FOLDER / (self.script_name.get() + ".script")
        self.script_text.delete("1.0", tk.END)
        if path.exists():
            lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
            for line in lines:
                try:
                    step = json.loads(line)
                    if isinstance(step, dict) and "action" in step:
                        ending = "\n" if line.endswith("\n") else ""
                        line = json.dumps({"name": step.get("name", ""), **step}, ensure_ascii=False) + ending
                except (ValueError, TypeError):
                    pass
                self.script_text.insert(tk.END, line)

    def save_script(self):
        path = script_engine.FOLDER / (self.script_name.get() + ".script")
        path.write_text(self.script_text.get("1.0", "end-1c"), encoding="utf-8")
        self.status.set(f"已儲存 {path.name}")

    def run_editor(self):
        self.run_content("編輯器腳本", self.script_text.get("1.0", "end-1c"), 1)

    def record_start(self):
        self.record_stop.clear()
        self.record_toggle.clear()
        self.record_state = "starting"
        self.work("錄製", self.record_worker)

    def record_worker(self):
        identifier = script_engine.start_recording(self.driver)
        count = 0
        self.root.after(0, self.record_state_changed, "recording")
        try:
            while not self.record_stop.wait(0.2):
                if self.record_toggle.is_set():
                    self.record_toggle.clear()
                    if identifier is not None:
                        actions = script_engine.read_recording(self.driver)
                        if actions:
                            count += len(actions)
                            self.root.after(0, self.record_append, actions)
                        script_engine.stop_recording(self.driver, identifier)
                        identifier = None
                        self.root.after(0, self.record_state_changed, "paused")
                    else:
                        identifier = script_engine.start_recording(self.driver)
                        self.root.after(0, self.record_state_changed, "recording")
                if identifier is not None:
                    actions = script_engine.read_recording(self.driver)
                    if actions:
                        count += len(actions)
                        self.root.after(0, self.record_append, actions)
            if identifier is not None:
                actions = script_engine.read_recording(self.driver)
                if actions:
                    count += len(actions)
                    self.root.after(0, self.record_append, actions)
        finally:
            if identifier is not None:
                script_engine.stop_recording(self.driver, identifier)
        self.root.after(0, self.record_finished, count)

    def record_state_changed(self, state):
        if self.record_stop.is_set():
            return
        self.record_state = state
        self.status.set("錄製中。" if state == "recording" else "已暫停錄製；按繼續錄製後才會記錄動作。")
        self.update_buttons()

    def record_pause(self):
        self.record_state = "changing"
        self.record_toggle.set()
        self.update_buttons()
        self.status.set("正在切換錄製狀態……")

    def record_append(self, actions):
        if self.editor and self.editor.winfo_exists():
            at_bottom = self.script_text.yview()[1] >= 0.99
            content = self.script_text.get("1.0", "end-1c")
            if content and not content.endswith("\n"):
                self.script_text.insert("end-1c", "\n")
            for action in actions:
                action.setdefault("name", "")
                if action.get("xpath"):
                    action.setdefault("timeout", 5)
                self.script_text.insert("end-1c", json.dumps({"name": action.get("name", ""), **action}, ensure_ascii=False) + "\n")
            if at_bottom:
                self.script_text.see(tk.END)

    def record_finished(self, count):
        self.status.set(f"錄製完成，共 {count} 個步驟；請檢查後儲存。")

    def record_end(self):
        self.record_state = "stopping"
        self.record_stop.set()
        self.update_buttons()

    def close_editor(self):
        if self.busy:
            messagebox.showinfo("執行中", "請先停止錄製或等待腳本執行完成。")
            return
        self.editor.destroy()
        self.editor = None

    def close(self):
        if self.busy:
            messagebox.showinfo("登入中", "請等待登入結果後再關閉。")
            return
        if self.driver:
            self.driver.quit()
        self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    try:
        App(window)
        window.mainloop()
    except Exception as exc:
        messagebox.showerror("啟動失敗", str(exc))
        window.destroy()
