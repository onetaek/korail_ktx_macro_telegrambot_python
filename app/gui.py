import asyncio
import logging
import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .config import settings
from .korail_service import KorailService
from .models import ConversationSession, JobStatus
from .reservation_service import ReservationService


class _TextHandler(logging.Handler):
    def __init__(self, write, update_attempt):
        super().__init__()
        self.write = write
        self.update_attempt = update_attempt

    def emit(self, record):
        message = record.getMessage()
        match = re.search(r"Reservation attempt started:.*attempt=(\d+)", message)
        if match:
            self.update_attempt(int(match.group(1)))


class _AsyncRunner:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)


class KorailGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("KORAIL KTX 예약")
        self.root.geometry("760x760")
        self.runner = _AsyncRunner()
        self.reservation_service = ReservationService()
        self.session: ConversationSession | None = None
        self.job = None
        self.trains = []
        self.attempt_var = tk.StringVar(value="예약 시도: 0회")
        self.entries = {}
        self.placeholder_active = {}
        self.placeholders = {
            "korail_id": "코레일 아이디 입력",
            "password": "코레일 비밀번호 입력",
            "date": "예: 20261010",
            "source": "예: 서울",
            "destination": "예: 부산",
            "start": "예: 0900",
            "max_time": "예: 2400",
            "passengers": "예: 1",
        }
        self.runtime_defaults = {
            "interval": "0.5",
            "jitter_min": "0.1",
            "jitter_max": "0.2",
            "max_minutes": "180",
        }
        self.seat_options = {
            "일반실 우선": "GENERAL_FIRST",
            "일반실만": "GENERAL_ONLY",
            "특실 우선": "SPECIAL_FIRST",
            "특실만": "SPECIAL_ONLY",
        }
        self._build_ui()
        logging.getLogger().setLevel(logging.INFO)
        handler = _TextHandler(
            lambda text: self.root.after(0, self._append_log, text),
            lambda attempt: self.root.after(0, self._set_attempt, attempt),
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
        logging.getLogger().addHandler(handler)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)
        form = ttk.LabelFrame(frame, text="예약 조건", padding=8)
        form.pack(fill="x")
        fields = [
            ("KORAIL ID", "korail_id"), ("KORAIL 비밀번호", "password"),
            ("출발일 YYYYMMDD", "date"), ("출발역 코드/명", "source"),
            ("도착역 코드/명", "destination"), ("시작시간 HHMM", "start"),
            ("종료시간 HHMM", "max_time"), ("승객 수", "passengers"),
        ]
        for index, (label, key) in enumerate(fields):
            row, col = divmod(index, 2)
            ttk.Label(form, text=label).grid(row=row, column=col * 2, sticky="w", padx=4, pady=4)
            entry = ttk.Entry(form, width=22)
            entry.grid(row=row, column=col * 2 + 1, padx=4, pady=4)
            self.entries[key] = entry
            self._add_placeholder(entry, key, self.placeholders[key], key == "password")
        ttk.Label(form, text="열차 종류").grid(row=4, column=0, sticky="w", padx=4, pady=4)
        self.train_type = tk.StringVar(value="KTX")
        self.train_type_combo = ttk.Combobox(form, textvariable=self.train_type, values=["KTX", "ALL"], state="readonly", width=19)
        self.train_type_combo.grid(row=4, column=1, padx=4)
        self.train_type_combo.bind("<<ComboboxSelected>>", self._on_input_change, add="+")
        ttk.Label(form, text="좌석 옵션").grid(row=4, column=2, sticky="w", padx=4, pady=4)
        self.seat_option = tk.StringVar(value="일반실 우선")
        self.seat_option_combo = ttk.Combobox(form, textvariable=self.seat_option, values=list(self.seat_options), state="readonly", width=19)
        self.seat_option_combo.grid(row=4, column=3, padx=4)
        self.seat_option_combo.bind("<<ComboboxSelected>>", self._on_input_change, add="+")

        runtime = ttk.LabelFrame(frame, text="조회 설정", padding=8)
        runtime.pack(fill="x", pady=(8, 0))
        runtime_fields = [
            ("조회 주기(초)", "interval"), ("최대 실행(분)", "max_minutes"),
            ("Jitter 최소(초)", "jitter_min"), ("Jitter 최대(초)", "jitter_max"),
        ]
        for index, (label, key) in enumerate(runtime_fields):
            row, col = divmod(index, 2)
            ttk.Label(runtime, text=label).grid(row=row, column=col * 2, sticky="w", padx=4, pady=4)
            entry = ttk.Entry(runtime, width=22)
            entry.grid(row=row, column=col * 2 + 1, padx=4, pady=4)
            entry.insert(0, self.runtime_defaults[key])
            self.entries[key] = entry

        action_buttons = ttk.Frame(frame)
        action_buttons.pack(fill="x", pady=(8, 4))
        self.preview_button = ttk.Button(action_buttons, text="1. 열차 조회", command=self.preview)
        self.preview_button.pack(side="left", padx=4)
        self.start_button = ttk.Button(action_buttons, text="2. 선택 열차 예약 시작", command=self.start_reservation, state="disabled")
        self.start_button.pack(side="left", padx=4)
        self.cancel_button = ttk.Button(action_buttons, text="3. 예약 취소", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=4)
        self.train_list = tk.Listbox(frame, height=10, selectmode=tk.MULTIPLE, exportselection=False)
        self.train_list.pack(fill="x", pady=4)
        ttk.Label(frame, textvariable=self.attempt_var).pack(anchor="w")
        ttk.Label(frame, text="로그").pack(anchor="w")
        self.log = tk.Text(frame, height=14, state="disabled")
        self.log.pack(fill="both", expand=True)
        for entry in self.entries.values():
            entry.bind("<KeyRelease>", self._on_input_change, add="+")
            entry.bind("<FocusOut>", self._on_input_change, add="+")
        self.train_list.bind("<<ListboxSelect>>", lambda _event: self._update_button_states())
        self._update_button_states()

    def _add_placeholder(self, entry, key, text, password=False):
        self.placeholder_active[key] = True
        entry.insert(0, text)
        entry.configure(foreground="gray")
        entry.bind("<FocusIn>", lambda _event: self._clear_placeholder(entry, key, password))
        entry.bind("<FocusOut>", lambda _event: self._restore_placeholder(entry, key, text, password))

    def _clear_placeholder(self, entry, key, password):
        if self.placeholder_active[key]:
            entry.delete(0, tk.END)
            entry.configure(foreground="black", show="*" if password else "")
            self.placeholder_active[key] = False

    def _restore_placeholder(self, entry, key, text, password):
        if not entry.get().strip():
            entry.insert(0, text)
            entry.configure(foreground="gray", show="" if password else "")
            self.placeholder_active[key] = True

    def _entry_value(self, key):
        entry = self.entries[key]
        if self.placeholder_active.get(key, False):
            return ""
        return entry.get().strip()

    def _inputs_complete(self):
        required = ("korail_id", "password", "date", "source", "destination", "start", "max_time", "interval", "jitter_min", "jitter_max", "max_minutes", "passengers")
        return all(self._entry_value(key) for key in required)

    def _reservation_running(self):
        return self.job is not None and self.job.status in {JobStatus.CREATED, JobStatus.RUNNING}

    def _update_button_states(self):
        running = self._reservation_running()
        complete = self._inputs_complete()
        selected = bool(self.train_list.curselection()) if hasattr(self, "train_list") else False
        self.preview_button.config(state="disabled" if running or not complete else "normal")
        self.start_button.config(state="disabled" if running or not complete or not self.trains or not selected else "normal")
        self.cancel_button.config(state="normal" if running else "disabled")

    def _on_input_change(self, _event=None):
        if hasattr(self, "train_list") and self.trains:
            self.trains = []
            self.train_list.delete(0, tk.END)
        self._update_button_states()

    def _make_session(self):
        v = {key: self._entry_value(key) for key in self.entries}
        if not all(v[key] for key in ("korail_id", "password", "date", "source", "destination")):
            raise ValueError("KORAIL 계정과 출발·도착 정보를 입력하세요.")
        if v["source"] == v["destination"]:
            raise ValueError("출발역과 도착역은 달라야 합니다.")
        for key in ("date",):
            if len(v[key]) != 8 or not v[key].isdigit():
                raise ValueError("출발일은 YYYYMMDD 형식이어야 합니다.")
        for key in ("start", "max_time"):
            if v[key] != "2400" and (len(v[key]) != 4 or not v[key].isdigit() or int(v[key][:2]) > 23 or int(v[key][2:]) > 59):
                raise ValueError("시간은 HHMM 형식이어야 합니다.")
        interval = float(v["interval"]); jitter_min = float(v["jitter_min"]); jitter_max = float(v["jitter_max"])
        if interval <= 0 or jitter_min < 0 or jitter_max < jitter_min:
            raise ValueError("조회 주기와 jitter 값을 확인하세요.")
        max_minutes = int(v["max_minutes"]); passengers = int(v["passengers"])
        if max_minutes <= 0 or not 1 <= passengers <= 9:
            raise ValueError("최대 실행 시간과 승객 수를 확인하세요.")
        settings.korail_id = v["korail_id"]
        settings.korail_password = v["password"]
        settings.korail_search_interval_seconds = interval
        settings.korail_search_jitter_min_seconds = jitter_min
        settings.korail_search_jitter_max_seconds = jitter_max
        settings.korail_max_search_minutes = max_minutes
        return ConversationSession(
            departure_date=v["date"], source_station=v["source"], destination_station=v["destination"],
            start_time=v["start"], max_time=v["max_time"], train_type=self.train_type.get(),
            seat_option=self.seat_options[self.seat_option.get()], passenger_count=passengers,
        )

    def preview(self):
        try:
            self.session = self._make_session()
        except (ValueError, TypeError) as exc:
            messagebox.showerror("입력 오류", str(exc)); return
        self.preview_button.config(state="disabled")
        self._append_log("열차 조회를 시작합니다.")
        self.runner.submit(self._preview_async()).add_done_callback(self._preview_done)

    async def _preview_async(self):
        service = KorailService()
        try:
            self.trains = await asyncio.to_thread(service.preview, self.session)
            return [service.train_summary(train) for train in self.trains]
        finally:
            await asyncio.to_thread(service.close)

    def _preview_done(self, future):
        try:
            summaries = future.result()
            self.root.after(0, self._show_trains, summaries)
        except Exception as exc:
            self.root.after(0, self._show_error, "열차 조회 실패", exc)

    def _show_trains(self, summaries):
        self.train_list.delete(0, tk.END)
        for index, summary in enumerate(summaries, 1):
            self.train_list.insert(tk.END, f"{index}. {summary}")
        self._update_button_states()
        self._append_log(f"열차 조회가 완료되었습니다. 조회 결과: {len(summaries)}개")
        if not summaries:
            messagebox.showinfo("조회 결과", "조건에 맞는 열차가 없습니다.")

    def start_reservation(self):
        try:
            selected = [index + 1 for index in self.train_list.curselection()]
            if not selected:
                raise ValueError("예약할 열차를 목록에서 하나 이상 선택하세요.")
            self.session.selected_train_numbers = [str(getattr(self.trains[index - 1], "train_no", "")) for index in selected]
            self.job = self.reservation_service.create(0, self.session)
            self.attempt_var.set("예약 시도: 0회")
            self.runner.submit(self._start_reservation_async())
            self._update_button_states()
            self._append_log(f"예약을 시작했습니다: {', '.join(map(str, selected))}")
        except (ValueError, TypeError) as exc:
            messagebox.showerror("선택 오류", str(exc))

    async def _start_reservation_async(self):
        self.reservation_service.start(self.job, self.notify)

    async def notify(self, job):
        self.root.after(0, self._append_log, f"예약 결과: {job.status.value} - {job.result_message}")
        self.root.after(0, self._reservation_finished)

    def _reservation_finished(self):
        self._update_button_states()

    def cancel(self):
        if not self.job or not self._reservation_running():
            return
        self.cancel_button.config(state="disabled")
        self.start_button.config(state="disabled")
        self.preview_button.config(state="disabled")
        self.attempt_var.set("예약 시도: 0회")
        future = self.runner.submit(self.reservation_service.cancel(self.job.job_id))
        future.add_done_callback(lambda _future: self.root.after(0, self._cancel_finished))
        self._append_log("예약 취소를 요청했습니다.")

    def _cancel_finished(self):
        self.attempt_var.set("예약 시도: 0회")
        self._append_log("예약 취소가 완료되었습니다.")
        self._update_button_states()

    def _append_log(self, text):
        self.log.config(state="normal")
        self.log.insert(tk.END, f"{text}\n")
        self.log.see(tk.END)
        self.log.config(state="disabled")

    def _set_attempt(self, attempt):
        self.attempt_var.set(f"예약 시도: {attempt}회")

    def _show_error(self, title, exc):
        self._update_button_states()
        messagebox.showerror(title, str(exc))

    def close(self):
        if self.job and self.job.status == JobStatus.RUNNING:
            self.runner.submit(self.reservation_service.cancel(self.job.job_id))
        self.runner.close()
        self.root.destroy()


def run_gui():
    root = tk.Tk()
    KorailGui(root)
    root.mainloop()
