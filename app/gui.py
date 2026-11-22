import asyncio
import logging
import re
import threading
import tkinter as tk
from types import SimpleNamespace

import customtkinter as ctk
from tktimepicker import AnalogPicker, AnalogThemes, constants as time_constants

from telegram import Bot

from .config import settings
from .gui_preferences import GuiPreferences
from .korail_service import KorailService
from .models import ConversationSession, JobStatus, PaymentStatus
from .reservation_service import ReservationService
from .widgets.CTkDatePicker import CTkDatePicker


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
    MENU_ITEMS = ("예약", "알림", "결제", "조회 설정", "실행 로그")
    PAGE_TITLES = {
        "예약": ("열차 예약", "예약 조건을 설정하고 열차를 조회하세요."),
        "알림": ("Telegram 알림", "예약이 완료되면 지정한 채팅으로 결과를 보냅니다."),
        "결제": ("자동 결제", "예약 성공 후 카드 결제를 선택적으로 진행합니다."),
        "조회 설정": ("조회 설정", "예약 가능한 열차를 확인하는 주기와 실행 시간을 설정합니다."),
        "실행 로그": ("실행 로그", "조회, 예약, 결제 처리 내역을 확인합니다."),
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        # GUI uses the current provider directly; account, Telegram, and card
        # values are collected from the form and kept in memory for this run.
        settings.korail_provider = "pykorail"
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.root.title("KORAIL KTX 예약")
        self.root.geometry("1120x820")
        self.root.minsize(980, 700)
        self.runner = _AsyncRunner()
        self.reservation_service = ReservationService()
        self.preferences = GuiPreferences()
        self.saved_preferences = self.preferences.load()
        self.session: ConversationSession | None = None
        self.job = None
        self.notification_config = None
        self.card_payment = None
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
        self.pages = {}
        self.nav_buttons = {}
        self.current_page = None
        self._toast = None
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
        shell = ctk.CTkFrame(self.root, corner_radius=0, fg_color=("#f3f5f8", "#171a21"))
        shell.pack(fill="both", expand=True)
        sidebar = ctk.CTkFrame(shell, width=210, corner_radius=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        ctk.CTkLabel(sidebar, text="KORAIL", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", padx=22, pady=(28, 2))
        ctk.CTkLabel(sidebar, text="열차 예약 도우미", text_color=("gray40", "gray70")).pack(anchor="w", padx=22, pady=(0, 24))
        for item in self.MENU_ITEMS:
            button = ctk.CTkButton(sidebar, text=item, anchor="w", height=42, corner_radius=8,
                                   command=lambda name=item: self.show_page(name))
            button.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[item] = button

        content = ctk.CTkFrame(shell, fg_color="transparent")
        content.pack(side="left", fill="both", expand=True, padx=24, pady=20)
        self.page_header = ctk.CTkLabel(content, text="", font=ctk.CTkFont(size=28, weight="bold"), text_color=("#172033", "#f4f7fb"))
        self.page_header.pack(anchor="w")
        self.page_description = ctk.CTkLabel(content, text="", text_color=("#536174", "#aeb9c8"))
        self.page_description.pack(anchor="w", pady=(4, 18))
        self.page_host = ctk.CTkFrame(content, fg_color="transparent")
        self.page_host.pack(fill="both", expand=True)

        self._build_reservation_page()
        self._build_notification_page()
        self._build_payment_page()
        self._build_runtime_page()
        self._build_log_page()
        self.show_page("예약")

    def _new_page(self, name):
        page = ctk.CTkScrollableFrame(self.page_host, fg_color="transparent")
        self.pages[name] = page
        return page

    @staticmethod
    def _section(parent, title, description=None):
        card = ctk.CTkFrame(parent, corner_radius=12, fg_color=("#ffffff", "#252b36"))
        card.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=17, weight="bold"), text_color=("#172033", "#f4f7fb")).pack(anchor="w", padx=18, pady=(16, 2))
        if description:
            ctk.CTkLabel(card, text=description, text_color=("#536174", "#aeb9c8")).pack(anchor="w", padx=18, pady=(0, 10))
        return card

    def _field(self, parent, label, key, *, placeholder=None, password=False, width=280):
        wrapper = ctk.CTkFrame(parent, fg_color="transparent")
        wrapper.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(wrapper, text=label, width=190, anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 14))
        entry = ctk.CTkEntry(wrapper, width=width, placeholder_text=placeholder or "", show="•" if password else "")
        entry.grid(row=0, column=1, sticky="ew")
        self.entries[key] = entry
        wrapper.pack(fill="x", padx=18, pady=7)
        return entry

    def _build_reservation_page(self):
        page = self._new_page("예약")
        account = self._section(page, "코레일 계정", "저장한 계정 정보는 이 PC의 로컬 설정 파일에만 보관되며, 다른 기기와 공유되지 않습니다.")
        grid = ctk.CTkFrame(account, fg_color="transparent")
        grid.pack(fill="x", padx=18, pady=(0, 14))
        for col in range(2):
            grid.grid_columnconfigure(col, weight=1)
        self.entries["korail_id"] = self._grid_field(grid, "KORAIL ID", "korail_id", 0, 0, "코레일 아이디")
        self.entries["password"] = self._grid_field(grid, "비밀번호", "password", 0, 1, "코레일 비밀번호", True)
        self._load_entry_values("account", ("korail_id", "password"))
        ctk.CTkButton(account, text="계정 정보 저장", width=140, command=self._save_account_preferences).pack(anchor="e", padx=18, pady=(0, 12))

        journey = self._section(page, "여정", "출발일, 구간과 시간대를 입력하세요. 저장한 기본값은 이 PC의 로컬 설정 파일에만 보관됩니다.")
        grid = ctk.CTkFrame(journey, fg_color="transparent")
        grid.pack(fill="x", padx=18, pady=(0, 14))
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, minsize=42)
        grid.grid_columnconfigure(2, weight=1)
        for label, key, row, col, hint in [
            ("출발역", "source", 0, 0, "예: 서울"), ("도착역", "destination", 0, 1, "예: 부산"),
            ("출발일", "date", 1, 0, "YYYYMMDD"), ("승객 수", "passengers", 1, 1, "1~9"),
            ("시작 시간", "start", 2, 0, "HHMM"), ("종료 시간", "max_time", 2, 1, "HHMM 또는 2400"),
        ]:
            if key == "date":
                self.entries[key] = self._grid_date_field(grid, label, row, col)
            else:
                self.entries[key] = self._grid_field(grid, label, key, row, col * 2, hint)
        self.swap_stations_button = ctk.CTkButton(
            grid, text="⇄", width=34, height=32, command=self._swap_stations,
            fg_color="#3b4656", hover_color="#4b5a70",
        )
        self.swap_stations_button.grid(row=0, column=1, padx=2, sticky="ew")
        for col in range(2):
            grid.grid_columnconfigure(col * 2, weight=1)

        self.train_type = tk.StringVar(value="KTX")
        self.seat_option = tk.StringVar(value="일반실 우선")
        self._grid_combo(grid, "열차 종류", self.train_type, ["KTX", "ALL"], 3, 0)
        self._grid_combo(grid, "좌석 옵션", self.seat_option, list(self.seat_options), 3, 2)
        self._load_entry_values("journey", ("date", "source", "destination", "start", "max_time", "passengers"))
        journey_actions = ctk.CTkFrame(journey, fg_color="transparent")
        journey_actions.pack(fill="x", padx=18, pady=(0, 12))
        ctk.CTkButton(journey_actions, text="여정 기본값 저장", width=140, command=self._save_journey_preferences).pack(side="right")
        saved_journey = self.saved_preferences.get("journey", {})
        if saved_journey.get("train_type") in {"KTX", "ALL"}:
            self.train_type.set(saved_journey["train_type"])
        if saved_journey.get("seat_option") in self.seat_options:
            self.seat_option.set(saved_journey["seat_option"])
        self.train_type_combo.bind("<<ComboboxSelected>>", self._on_input_change, add="+")
        self.seat_option_combo.bind("<<ComboboxSelected>>", self._on_input_change, add="+")

        results = self._section(page, "조회 결과", "열차를 조회한 뒤 예약할 항목을 선택하세요.")
        self.train_list = tk.Listbox(results, height=10, selectmode=tk.MULTIPLE, exportselection=False,
                                     font=("Segoe UI", 10), relief="flat", highlightthickness=0)
        self.train_list.pack(fill="x", padx=18, pady=(0, 12))
        self.train_list.bind("<<ListboxSelect>>", lambda _event: self._update_button_states())
        actions = ctk.CTkFrame(results, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(0, 14))
        self.preview_button = ctk.CTkButton(actions, text="열차 조회", command=self.preview)
        self.preview_button.pack(side="left", padx=4)
        self.start_button = ctk.CTkButton(actions, text="선택 열차 예약", command=self.start_reservation, state="disabled")
        self.start_button.pack(side="left", padx=4)
        self.cancel_button = ctk.CTkButton(actions, text="예약 취소", command=self.cancel, fg_color="#a33a3a", hover_color="#852d2d", state="disabled")
        self.cancel_button.pack(side="left", padx=4)
        self.reset_button = ctk.CTkButton(
            actions, text="초기화", command=self.reset_results,
            fg_color="#238636", hover_color="#1b6f2b", state="disabled",
        )
        self.reset_button.pack(side="left", padx=4)
        self.attempt_label = ctk.CTkLabel(actions, textvariable=self.attempt_var)
        self.attempt_label.pack(side="right", padx=8)

    def _grid_field(self, parent, label, key, row, col, hint, password=False):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=col, sticky="ew", padx=6, pady=7)
        box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(box, text=label, width=145, anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 10))
        entry = ctk.CTkEntry(box, placeholder_text=hint, show="•" if password else "")
        entry.grid(row=0, column=1, sticky="ew")
        if key == "passengers":
            validate_digits = (self.root.register(lambda value: not value or (value.isascii() and value.isdigit())), "%P")
            entry.configure(validate="key", validatecommand=validate_digits)
        entry.bind("<KeyRelease>", self._on_input_change, add="+")
        if key in {"start", "max_time"}:
            ctk.CTkButton(
                box, text="시계", width=48, command=lambda field=key: self._open_time_picker(field),
            ).grid(row=0, column=2, padx=(6, 0))
        return entry

    def _grid_date_field(self, parent, label, row, col):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=col * 2, sticky="ew", padx=6, pady=7)
        box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(box, text=label, width=145, anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 10))
        picker = CTkDatePicker(box, fg_color="transparent")
        picker.set_date_format("%Y%m%d")
        picker.set_allow_manual_input(True)
        picker.grid(row=0, column=1, sticky="ew")
        picker.date_entry.configure(placeholder_text="YYYYMMDD")
        picker.date_entry.bind("<KeyRelease>", self._on_input_change, add="+")
        picker.date_entry.bind("<FocusOut>", self._on_input_change, add="+")
        self.date_picker = picker
        return picker

    def _grid_combo(self, parent, label, variable, values, row, col):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=col, sticky="ew", padx=6, pady=7)
        box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(box, text=label, width=145, anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 10))
        combo = ctk.CTkComboBox(box, variable=variable, values=values, state="readonly")
        combo.grid(row=0, column=1, sticky="ew")
        if label == "열차 종류":
            self.train_type_combo = combo
        else:
            self.seat_option_combo = combo

    def _swap_stations(self):
        source = self._entry_value("source")
        destination = self._entry_value("destination")
        self.entries["source"].delete(0, tk.END)
        self.entries["source"].insert(0, destination)
        self.entries["destination"].delete(0, tk.END)
        self.entries["destination"].insert(0, source)
        self._on_input_change()

    def _open_time_picker(self, field: str):
        picker_window = ctk.CTkToplevel(self.root)
        picker_window.title("시간 선택")
        picker_window.resizable(False, False)
        picker_window.transient(self.root)
        picker = AnalogPicker(picker_window, type=time_constants.HOURS24)
        picker.pack(fill="both", expand=True, padx=18, pady=(14, 8))
        AnalogThemes(picker).setDracula()
        current = self._entry_value(field)
        if re.fullmatch(r"\d{4}", current) and current != "2400":
            picker.setHours(int(current[:2]))
            picker.setMinutes(int(current[2:]))
        buttons = ctk.CTkFrame(picker_window, fg_color="transparent")
        buttons.pack(fill="x", padx=18, pady=(0, 16))

        def apply_time(value=None):
            if value is None:
                hour, minute, _period = picker.time()
                value = f"{hour:02d}{minute:02d}"
            entry = self.entries[field]
            entry.delete(0, tk.END)
            entry.insert(0, value)
            picker_window.destroy()
            self._on_input_change()

        if field == "max_time":
            ctk.CTkButton(buttons, text="24:00", width=90, command=lambda: apply_time("2400")).pack(side="left")
        ctk.CTkButton(buttons, text="취소", width=90, fg_color="#4b5563", command=picker_window.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(buttons, text="선택", width=90, command=apply_time).pack(side="right")
        picker_window.geometry("360x410")
        picker_window.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - picker_window.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - picker_window.winfo_height()) // 2
        picker_window.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        picker_window.grab_set()

    def _build_notification_page(self):
        page = self._new_page("알림")
        card = self._section(page, "예약 완료 알림", "알림을 켜면 예약 결과를 Telegram으로 전송합니다. 저장한 알림 설정은 이 PC의 로컬 설정 파일에만 보관되며, 다른 기기와 공유되지 않습니다.")
        self.telegram_notify = tk.BooleanVar(value=False)
        self.telegram_notify_check = ctk.CTkSwitch(card, text="예약 완료 시 Telegram 알림", variable=self.telegram_notify,
                                                    command=self._on_notification_toggle)
        self.telegram_notify_check.pack(anchor="w", padx=18, pady=(8, 14))
        self.telegram_token_entry = self._field(card, "Bot Token", "telegram_token", password=True, width=500)
        self.telegram_chat_id_entry = self._field(card, "Chat ID", "telegram_chat_id", placeholder="숫자형 Chat ID", width=500)
        saved = self.saved_preferences.get("notification", {})
        self.telegram_notify.set(bool(saved.get("enabled", False)))
        self._load_external_entries(saved, {"token": self.telegram_token_entry, "chat_id": self.telegram_chat_id_entry})
        ctk.CTkButton(card, text="알림 설정 저장", width=140, command=self._save_notification_preferences).pack(anchor="e", padx=18, pady=(0, 12))
        self._set_notification_inputs_state()

    def _build_payment_page(self):
        page = self._new_page("결제")
        card = self._section(page, "예약 완료 후 자동 결제", "자동 결제를 켜면 예약 직후 실제 카드 결제가 진행됩니다. 저장한 결제 설정은 이 PC의 로컬 설정 파일에만 보관되며, 다른 기기와 공유되지 않습니다.")
        self.auto_payment = tk.BooleanVar(value=False)
        self.auto_payment_check = ctk.CTkSwitch(card, text="자동 결제 사용", variable=self.auto_payment, command=self._on_payment_toggle)
        self.auto_payment_check.pack(anchor="w", padx=18, pady=(8, 14))
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=(0, 14))
        for col in range(2):
            grid.grid_columnconfigure(col, weight=1)
        self.payment_entries = {}
        for label, key, row, col, masked, hint in [
            ("카드번호", "card_number", 0, 0, False, "숫자 12~19자리"),
            ("카드 비밀번호 앞 2자리", "card_password", 0, 1, True, "숫자 2자리"),
            ("유효기간", "card_expire", 1, 0, False, "YYMM"),
            ("생년월일 / 사업자번호 앞 6자리", "birthday", 1, 1, False, "숫자 6자리"),
            ("할부개월", "installment", 2, 0, False, "0은 일시불, 01~24는 할부"),
        ]:
            self.payment_entries[key] = self._grid_field(grid, label, key, row, col, hint, masked)
        box = ctk.CTkFrame(grid, fg_color="transparent")
        box.grid(row=2, column=1, sticky="ew", padx=6, pady=7)
        box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(box, text="카드 유형", width=145, anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.card_type = tk.StringVar(value="개인")
        self.card_type_combo = ctk.CTkComboBox(box, variable=self.card_type, values=["개인", "법인"], state="readonly")
        self.card_type_combo.grid(row=0, column=1, sticky="ew")
        saved = self.saved_preferences.get("payment", {})
        self.auto_payment.set(bool(saved.get("enabled", False)))
        self._load_external_entries(saved, self.payment_entries)
        if saved.get("card_type") in {"개인", "법인"}:
            self.card_type.set(saved["card_type"])
        ctk.CTkButton(card, text="결제 설정 저장", width=140, command=self._save_payment_preferences).pack(anchor="e", padx=18, pady=(0, 12))
        self._set_payment_inputs_state()

    def _build_runtime_page(self):
        page = self._new_page("조회 설정")
        card = self._section(page, "예약 검색", "좌석을 찾을 때 적용할 반복 간격과 제한 시간을 설정합니다. 저장한 값은 이 PC의 로컬 설정 파일에만 보관됩니다.")
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=(0, 14))
        for col in range(2):
            grid.grid_columnconfigure(col, weight=1)
        self.runtime_vars = {}
        for label, key, row, col in [
            ("조회 주기 (초)", "interval", 0, 0), ("최대 실행 시간 (분)", "max_minutes", 0, 1),
            ("Jitter 최소 (초)", "jitter_min", 1, 0), ("Jitter 최대 (초)", "jitter_max", 1, 1),
        ]:
            field = self._grid_field(grid, label, key, row, col, self.runtime_defaults[key])
            field.insert(0, self.runtime_defaults[key])
            self.entries[key] = field
            self.runtime_vars[key] = field
        self._load_entry_values("runtime", tuple(self.runtime_vars))
        ctk.CTkButton(card, text="조회 설정 저장", width=130, command=self._save_runtime_preferences).pack(anchor="e", padx=18, pady=(0, 12))

    def _load_entry_values(self, section: str, keys: tuple[str, ...]) -> None:
        values = self.saved_preferences.get(section, {})
        if not isinstance(values, dict):
            return
        for key in keys:
            value = values.get(key)
            entry = self.entries.get(key)
            if entry is not None and value is not None:
                if key == "date":
                    entry.date_entry.delete(0, tk.END)
                    entry.date_entry.insert(0, str(value))
                    continue
                entry.delete(0, tk.END)
                entry.insert(0, str(value))

    @staticmethod
    def _load_external_entries(values: dict, entries: dict) -> None:
        for key, entry in entries.items():
            value = values.get(key)
            if value is not None:
                entry.delete(0, tk.END)
                entry.insert(0, str(value))

    def _save_preferences_section(self, section: str, values: dict, label: str) -> None:
        try:
            self.preferences.save_section(section, values)
            self.saved_preferences = self.preferences.load()
            self._append_log(f"{label}을(를) 로컬에 저장했습니다.")
            self._show_toast(f"{label} 저장 완료", "설정이 현재 PC의 로컬 파일에 저장되었습니다. 이 파일은 다른 기기와 자동으로 공유되지 않습니다.", "success")
        except OSError as exc:
            self._show_dialog("저장 실패", f"설정을 저장하지 못했습니다. 파일 접근 권한을 확인하세요.\n{exc}", "error")

    def _save_account_preferences(self) -> None:
        self._save_preferences_section("account", {
            "korail_id": self._entry_value("korail_id"),
            "password": f"secret:{self._entry_value('password')}",
        }, "계정 정보")

    def _save_journey_preferences(self) -> None:
        keys = ("date", "source", "destination", "start", "max_time", "passengers")
        values = {key: self._entry_value(key) for key in keys}
        values.update(train_type=self.train_type.get(), seat_option=self.seat_option.get())
        self._save_preferences_section("journey", values, "여정 기본값")

    def _save_runtime_preferences(self) -> None:
        values = {key: self._entry_value(key) for key in self.runtime_vars}
        self._save_preferences_section("runtime", values, "조회 설정")

    def _save_notification_preferences(self) -> None:
        self._save_preferences_section("notification", {
            "enabled": bool(self.telegram_notify.get()),
            "token": f"secret:{self.telegram_token_entry.get().strip()}",
            "chat_id": self.telegram_chat_id_entry.get().strip(),
        }, "알림 설정")

    def _save_payment_preferences(self) -> None:
        values = {key: f"secret:{entry.get().strip()}" for key, entry in self.payment_entries.items()}
        values.update(enabled=bool(self.auto_payment.get()), card_type=self.card_type.get())
        self._save_preferences_section("payment", values, "결제 설정")

    def _build_log_page(self):
        page = self._new_page("실행 로그")
        card = self._section(page, "작업 내역", "최근 실행 중 발생한 조회·예약 상태를 보여줍니다.")
        self.log = ctk.CTkTextbox(card, height=520, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def show_page(self, name):
        if self.current_page:
            self.pages[self.current_page].pack_forget()
        self.current_page = name
        title, description = self.PAGE_TITLES[name]
        self.page_header.configure(text=title)
        self.page_description.configure(text=description)
        self.pages[name].pack(fill="both", expand=True)
        for item, button in self.nav_buttons.items():
            button.configure(fg_color=("#1f6aa5", "#144870") if item == name else "transparent",
                             text_color=("white", "white") if item == name else ("gray10", "gray90"))
        self._update_button_states()

    def _show_toast(self, title: str, message: str, level: str = "info") -> None:
        if self._toast is not None:
            try:
                self._toast.destroy()
            except tk.TclError:
                pass
        colors = {"success": "#238636", "warning": "#9a6700", "error": "#b42332", "info": "#245ea8"}
        icons = {"success": "✓", "warning": "⚠", "error": "✕", "info": "ℹ"}
        toast_color = colors.get(level, colors["info"])
        toast = ctk.CTkToplevel(self.root)
        toast.overrideredirect(True)
        toast._fade_supported = False
        try:
            toast.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            # Windows Tk supports a transparency key, allowing the rounded card
            # to float without exposing a light rectangular window behind it.
            toast.attributes("-transparentcolor", "#010203")
            toast.configure(fg_color="#010203")
            card_color = toast_color
            toast.attributes("-alpha", 0.0)
            toast._fade_supported = True
        except tk.TclError:
            # On Tk builds without a transparency key, use a matching solid
            # background so the toast still has no contrasting white corners.
            toast.configure(fg_color=toast_color)
            card_color = toast_color
        toast.update_idletasks()
        width, height = 310, 78
        x = self.root.winfo_rootx() + self.root.winfo_width() - width - 24
        y = self.root.winfo_rooty() + 54
        toast.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
        card = ctk.CTkFrame(toast, corner_radius=11, border_width=1,
                            border_color=toast_color, fg_color=card_color)
        card.pack(fill="both", expand=True)
        content = ctk.CTkFrame(card, corner_radius=0, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=12, pady=9)
        ctk.CTkLabel(content, text=icons.get(level, icons["info"]), width=28,
                     font=ctk.CTkFont(size=22, weight="bold"), text_color="white").pack(side="left", anchor="n", padx=(0, 8))
        text_area = ctk.CTkFrame(content, corner_radius=0, fg_color="transparent")
        text_area.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(text_area, text=title, font=ctk.CTkFont(size=14, weight="bold"), text_color="white").pack(anchor="w", pady=(0, 3))
        ctk.CTkLabel(text_area, text=message, text_color="white", justify="left", wraplength=230).pack(anchor="w")
        self._toast = toast
        if toast._fade_supported:
            self._fade_toast(toast, 0.0, 1.0, on_complete=lambda: self.root.after(2600, lambda: self._dismiss_toast(toast)))
        else:
            self.root.after(3000, lambda: self._dismiss_toast(toast))

    def _fade_toast(self, toast, start: float, end: float, *, on_complete=None) -> None:
        steps = 8
        interval_ms = 25

        def animate(step: int) -> None:
            if self._toast is not toast:
                return
            try:
                alpha = start + (end - start) * (step / steps)
                toast.attributes("-alpha", alpha)
            except tk.TclError:
                return
            if step < steps:
                self.root.after(interval_ms, lambda: animate(step + 1))
            elif on_complete is not None:
                on_complete()

        animate(0)

    def _dismiss_toast(self, toast) -> None:
        if self._toast is toast:
            if getattr(toast, "_fade_supported", False):
                self._fade_toast(toast, 1.0, 0.0, on_complete=lambda: self._destroy_toast(toast))
            else:
                self._destroy_toast(toast)

    def _destroy_toast(self, toast) -> None:
        if self._toast is toast:
            self._toast = None
            try:
                toast.destroy()
            except tk.TclError:
                pass

    def _show_dialog(self, title: str, message: str, level: str = "info") -> None:
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(title)
        dialog.geometry("440x210")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dialog.grab_set()
        color = {"error": "#ff6675", "success": "#53c77a", "info": "#75aaff"}.get(level, "#75aaff")
        icon = {"error": "✕", "warning": "⚠", "success": "✓", "info": "ℹ"}.get(level, "ℹ")
        heading = ctk.CTkFrame(dialog, fg_color="transparent")
        heading.pack(fill="x", padx=24, pady=(22, 8))
        ctk.CTkLabel(heading, text=icon, width=28, font=ctk.CTkFont(size=22, weight="bold"), text_color=color).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(heading, text=title, font=ctk.CTkFont(size=19, weight="bold"), text_color=color).pack(side="left", anchor="w")
        ctk.CTkLabel(dialog, text=message, justify="left", wraplength=390).pack(fill="both", expand=True, anchor="w", padx=24, pady=4)
        ctk.CTkButton(dialog, text="확인", width=100, command=dialog.destroy).pack(anchor="e", padx=24, pady=(8, 18))
        dialog.bind("<Return>", lambda _event: dialog.destroy())

    def _entry_value(self, key):
        entry = self.entries[key]
        if key == "date":
            value = entry.get_date().strip()
            if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return value.replace("-", "")
            return value
        return entry.get().strip()

    def _on_notification_toggle(self):
        self._set_notification_inputs_state()
        self._update_button_states()

    def _on_payment_toggle(self):
        self._set_payment_inputs_state()
        self._update_button_states()

    def _set_payment_inputs_state(self):
        state = "normal" if self.auto_payment.get() else "disabled"
        for entry in self.payment_entries.values():
            entry.configure(state=state)
        self.card_type_combo.configure(state="readonly" if self.auto_payment.get() else "disabled")

    def _payment_values(self):
        if not self.auto_payment.get():
            return None
        values = {key: entry.get().strip() for key, entry in self.payment_entries.items()}
        if not values["card_number"].isdigit() or not 12 <= len(values["card_number"]) <= 19:
            raise ValueError("카드번호는 숫자 12~19자리로 입력하세요.")
        if not values["card_password"].isdigit() or len(values["card_password"]) != 2:
            raise ValueError("카드 비밀번호 앞 2자리는 숫자 2자리로 입력하세요.")
        if not re.fullmatch(r"\d{4}", values["card_expire"]) or not 1 <= int(values["card_expire"][2:]) <= 12:
            raise ValueError("카드 유효기간은 YYMM 형식으로 입력하세요.")
        if not re.fullmatch(r"\d{6}", values["birthday"]):
            raise ValueError("생년월일/사업자번호는 숫자 6자리로 입력하세요.")
        if not re.fullmatch(r"0|(?:0[1-9]|1[0-9]|2[0-4])", values["installment"]):
            raise ValueError("할부개월은 0 또는 01~24로 입력하세요.")
        return SimpleNamespace(
            card_number=values["card_number"],
            card_password=values["card_password"],
            card_expire=values["card_expire"],
            birthday=values["birthday"],
            installment=values["installment"],
            card_type="J" if self.card_type.get() == "개인" else "S",
        )

    def _set_notification_inputs_state(self):
        state = "normal" if self.telegram_notify.get() else "disabled"
        self.telegram_token_entry.configure(state=state)
        self.telegram_chat_id_entry.configure(state=state)

    def _notification_values(self):
        if not self.telegram_notify.get():
            return None
        token = self.telegram_token_entry.get().strip()
        chat_id = self.telegram_chat_id_entry.get().strip()
        if not token or not chat_id:
            raise ValueError("텔레그램 알림을 사용하려면 Bot Token과 Chat ID를 입력하세요.")
        if not re.fullmatch(r"-?\d+", chat_id):
            raise ValueError("Telegram Chat ID는 숫자 형식이어야 합니다.")
        return token, int(chat_id)

    def _inputs_complete(self):
        required = ("korail_id", "password", "date", "source", "destination", "start", "max_time", "interval", "jitter_min", "jitter_max", "max_minutes", "passengers")
        return all(self._entry_value(key) for key in required)

    def _reservation_running(self):
        return self.job is not None and self.job.status in {JobStatus.CREATED, JobStatus.RUNNING, JobStatus.RESERVED}

    def _update_button_states(self):
        running = self._reservation_running()
        complete = self._inputs_complete()
        selected = bool(self.train_list.curselection()) if hasattr(self, "train_list") else False
        self.preview_button.configure(state="disabled" if running or not complete else "normal")
        self.start_button.configure(state="disabled" if running or not complete or not self.trains or not selected else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        has_results = bool(self.trains) or bool(self.train_list.size())
        self.reset_button.configure(state="normal" if not running and has_results else "disabled")

    def reset_results(self):
        if self._reservation_running():
            return
        self.trains = []
        self.train_list.delete(0, tk.END)
        self.attempt_var.set("예약 시도: 0회")
        self._append_log("조회 결과와 선택 항목을 초기화했습니다. 새 열차를 조회할 수 있습니다.")
        self._update_button_states()

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
        self._notification_values()
        self._payment_values()
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
            self._show_dialog("입력 오류", str(exc), "error"); return
        self.preview_button.configure(state="disabled")
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
            self._show_dialog("조회 결과", "조건에 맞는 열차가 없습니다.")

    def start_reservation(self):
        try:
            selected = [index + 1 for index in self.train_list.curselection()]
            if not selected:
                raise ValueError("예약할 열차를 목록에서 하나 이상 선택하세요.")
            self.session.selected_train_numbers = [str(getattr(self.trains[index - 1], "train_no", "")) for index in selected]
            self.notification_config = self._notification_values()
            self.card_payment = self._payment_values()
            self.job = self.reservation_service.create(0, self.session, self.card_payment)
            self.attempt_var.set("예약 시도: 0회")
            self.runner.submit(self._start_reservation_async())
            self._update_button_states()
            self._append_log(f"예약을 시작했습니다: {', '.join(map(str, selected))}")
        except (ValueError, TypeError) as exc:
            self._show_dialog("선택 오류", str(exc), "error")

    async def _start_reservation_async(self):
        self.reservation_service.start(self.job, self.notify)

    async def notify(self, job):
        self.root.after(0, self._append_log, f"예약 결과: {job.status.value} - {job.result_message}")
        if job.status == JobStatus.RESERVED and self.notification_config:
            token, chat_id = self.notification_config
            try:
                await self._send_telegram_notification(job, token, chat_id)
                self.root.after(0, self._append_log, "텔레그램 예약 완료 알림을 전송했습니다.")
            except Exception as exc:
                self.root.after(0, self._append_log, f"텔레그램 알림 전송 실패: {exc}")
        self.root.after(0, self._reservation_finished, job)

    async def _send_telegram_notification(self, job, token, chat_id):
        async with Bot(token=token) as bot:
            await bot.send_message(chat_id=chat_id, text=self._telegram_message(job))

    def _telegram_message(self, job):
        session = job.session
        reservation = f"\n예약 번호: {job.reservation_number}" if job.reservation_number else ""
        heading = "⚠️ 예약은 완료되었지만 카드 결제에 실패했습니다." if job.payment_status == PaymentStatus.FAILED else "✅ 코레일 예약이 완료되었습니다."
        return (
            f"{heading}\n"
            f"{job.result_message or ''}{reservation}\n\n"
            f"출발일: {session.departure_date}\n"
            f"출발: {session.source_station}\n"
            f"도착: {session.destination_station}\n"
            f"출발 시간: {session.start_time}\n"
            f"열차: {session.train_type}\n"
            f"좌석: {session.seat_option}\n"
            f"인원: {session.passenger_count}명"
        )

    def _reservation_finished(self, job):
        self._update_button_states()
        if job.status == JobStatus.RESERVED:
            title = "예약 완료"
            level = "warning" if job.payment_status == PaymentStatus.FAILED else "success"
            heading = "예약은 완료됐지만 카드 결제에 실패했습니다." if job.payment_status == PaymentStatus.FAILED else "열차 예약이 완료되었습니다."
            message = f"{heading}\n\n{job.result_message or ''}"
            if job.reservation_number:
                message += f"\n예약 번호: {job.reservation_number}"
        elif job.status == JobStatus.CANCELLED:
            title, level = "예약 취소", "warning"
            message = job.result_message or "예약 작업이 취소되었습니다."
        else:
            title, level = "예약 실패", "error"
            message = job.result_message or "예약 중 오류가 발생했습니다. 실행 로그를 확인하세요."
        self._show_dialog(title, message, level)

    def cancel(self):
        if not self.job or not self._reservation_running():
            return
        self.cancel_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.preview_button.configure(state="disabled")
        self.attempt_var.set("예약 시도: 0회")
        future = self.runner.submit(self.reservation_service.cancel(self.job.job_id))
        future.add_done_callback(lambda _future: self.root.after(0, self._cancel_finished))
        self._append_log("예약 취소를 요청했습니다.")

    def _cancel_finished(self):
        self.attempt_var.set("예약 시도: 0회")
        self._append_log("예약 취소가 완료되었습니다.")
        self._update_button_states()

    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert(tk.END, f"{text}\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def _set_attempt(self, attempt):
        self.attempt_var.set(f"예약 시도: {attempt}회")

    def _show_error(self, title, exc):
        self._update_button_states()
        self._show_dialog(title, str(exc), "error")

    def close(self):
        if self.job and self.job.status == JobStatus.RUNNING:
            self.runner.submit(self.reservation_service.cancel(self.job.job_id))
        self.runner.close()
        self.root.destroy()


def run_gui():
    root = tk.Tk()
    KorailGui(root)
    root.mainloop()
