import re
from typing import Callable

import customtkinter as ctk

from scraper import ScraperConfig

_SUNSHINE_COAST_POSTCODES: list[str] = [
    "4515", "4518", "4519",
    "4550", "4551", "4552", "4553", "4554", "4555",
    "4556", "4557", "4558", "4559", "4560", "4561",
    "4562", "4563", "4564", "4565", "4566", "4567", "4568",
    "4572", "4573", "4575",
]

_BRISBANE_POSTCODES: list[str] = [
    "4000", "4005", "4006", "4007", "4008", "4009",
    "4010", "4011", "4012", "4013", "4014", "4017", "4018", "4019",
    "4030", "4031", "4032", "4034", "4035", "4036", "4037",
    "4051", "4053", "4054", "4055", "4059", "4060", "4061",
    "4064", "4065", "4066", "4067", "4068", "4069",
    "4070", "4072", "4073", "4074", "4075", "4076", "4077", "4078",
    "4101", "4102", "4103", "4104", "4105", "4106", "4107", "4108", "4109", "4110",
    "4111", "4112", "4113", "4114", "4115", "4116", "4117", "4118",
    "4120", "4121", "4122", "4123", "4124",
    "4127", "4128", "4129", "4130", "4131", "4132", "4133",
    "4151", "4152", "4153", "4154", "4155", "4156", "4157", "4158", "4159",
    "4160", "4161", "4163", "4164", "4165",
    "4169", "4170", "4171", "4172", "4173", "4174", "4179",
]

# All region postcodes in one set — used to separate manual entries from
# auto-filled ones when toggling regions on/off.
_ALL_REGION_POSTCODES: set[str] = set(_SUNSHINE_COAST_POSTCODES + _BRISBANE_POSTCODES)


class FilterPanel(ctk.CTkFrame):
    def __init__(
        self,
        parent: ctk.CTkFrame,
        start_callback: Callable,
        stop_callback: Callable,
        clear_callback: Callable,
    ) -> None:
        super().__init__(parent, width=260, corner_radius=0)
        self._start_cb = start_callback
        self._stop_cb = stop_callback
        self._clear_cb = clear_callback
        self.grid_propagate(False)
        self._build_widgets()

    def _build_widgets(self) -> None:
        self.grid_rowconfigure(14, weight=1)

        title = ctk.CTkLabel(
            self,
            text="Search Filters",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        title.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        ctk.CTkLabel(
            self, text="Postcodes", font=ctk.CTkFont(size=12)
        ).grid(row=3, column=0, padx=16, pady=(4, 2), sticky="w")
        ctk.CTkLabel(
            self,
            text="(comma or newline separated)",
            font=ctk.CTkFont(size=10),
            text_color="gray",
        ).grid(row=4, column=0, padx=16, pady=(0, 2), sticky="w")
        self._postcodes = ctk.CTkTextbox(self, width=228, height=90)
        self._postcodes.grid(row=5, column=0, padx=16, pady=(0, 6), sticky="w")

        # ── Quick-fill region checkboxes ──────────────────────────────
        ctk.CTkLabel(
            self,
            text="Quick fill:",
            font=ctk.CTkFont(size=10),
            text_color="gray",
        ).grid(row=6, column=0, padx=16, pady=(0, 2), sticky="w")

        region_frame = ctk.CTkFrame(self, fg_color="transparent")
        region_frame.grid(row=7, column=0, padx=16, pady=(0, 8), sticky="w")

        self._sc_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            region_frame,
            text="Sunshine Coast",
            variable=self._sc_var,
            command=self._on_region_toggle,
            checkbox_width=16,
            checkbox_height=16,
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))

        self._brisbane_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            region_frame,
            text="Brisbane",
            variable=self._brisbane_var,
            command=self._on_region_toggle,
            checkbox_width=16,
            checkbox_height=16,
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=1, sticky="w")

        # ── Separator ─────────────────────────────────────────────────
        ctk.CTkFrame(self, height=1, fg_color="#3A3A3A").grid(
            row=8, column=0, padx=16, pady=8, sticky="ew"
        )

        ctk.CTkLabel(self, text="Filter Results", font=ctk.CTkFont(size=12)).grid(
            row=9, column=0, padx=16, pady=(4, 4), sticky="w"
        )

        self._no_website_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self,
            text="No website",
            variable=self._no_website_var,
            checkbox_width=18,
            checkbox_height=18,
        ).grid(row=10, column=0, padx=16, pady=(0, 4), sticky="w")

        self._outdated_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self,
            text="Outdated website",
            variable=self._outdated_var,
            checkbox_width=18,
            checkbox_height=18,
        ).grid(row=11, column=0, padx=16, pady=(0, 8), sticky="w")

        vcmd = (self.register(self._validate_int), "%P")

        year_frame = ctk.CTkFrame(self, fg_color="transparent")
        year_frame.grid(row=12, column=0, padx=16, pady=(0, 8), sticky="w")
        ctk.CTkLabel(year_frame, text="Outdated before:", font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, sticky="w"
        )
        self._threshold_year = ctk.CTkEntry(
            year_frame, width=72, validate="key", validatecommand=vcmd
        )
        self._threshold_year.insert(0, "2010")
        self._threshold_year.grid(row=0, column=1, padx=(8, 0))

        max_frame = ctk.CTkFrame(self, fg_color="transparent")
        max_frame.grid(row=13, column=0, padx=16, pady=(0, 8), sticky="w")
        ctk.CTkLabel(max_frame, text="Max results/postcode:", font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, sticky="w"
        )
        self._max_results = ctk.CTkEntry(
            max_frame, width=56, validate="key", validatecommand=vcmd
        )
        self._max_results.insert(0, "20")
        self._max_results.grid(row=0, column=1, padx=(8, 0))

        ctk.CTkFrame(self, height=1, fg_color="#3A3A3A").grid(
            row=15, column=0, padx=16, pady=8, sticky="ew"
        )

        self._start_btn = ctk.CTkButton(
            self,
            text="Start Scraping",
            command=self._start_cb,
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            width=228,
        )
        self._start_btn.grid(row=16, column=0, padx=16, pady=(4, 4))

        self._stop_btn = ctk.CTkButton(
            self,
            text="Stop",
            command=self._stop_cb,
            fg_color="#C62828",
            hover_color="#8E0000",
            state="disabled",
            width=228,
        )
        self._stop_btn.grid(row=17, column=0, padx=16, pady=(0, 4))

        self._clear_btn = ctk.CTkButton(
            self,
            text="Clear",
            command=self._clear_cb,
            fg_color="gray40",
            hover_color="gray30",
            width=228,
        )
        self._clear_btn.grid(row=18, column=0, padx=16, pady=(0, 16))

        self._all_inputs = [
            self._postcodes,
            self._threshold_year,
            self._max_results,
        ]

    # ── Region quick-fill ─────────────────────────────────────────────

    def _on_region_toggle(self) -> None:
        # Build the set of postcodes for all currently checked regions
        active_region: set[str] = set()
        if self._sc_var.get():
            active_region.update(_SUNSHINE_COAST_POSTCODES)
        if self._brisbane_var.get():
            active_region.update(_BRISBANE_POSTCODES)

        # Preserve any postcodes the user typed manually (not from any region)
        raw = self._postcodes.get("1.0", "end")
        manual = [
            p.strip()
            for p in re.split(r"[,\n]+", raw)
            if p.strip() and p.strip() not in _ALL_REGION_POSTCODES
        ]

        # Combine manual entries + active region postcodes (sorted numerically)
        combined = manual + sorted(active_region, key=int)

        self._postcodes.delete("1.0", "end")
        if combined:
            self._postcodes.insert("1.0", "\n".join(combined))

    # ── Validation ────────────────────────────────────────────────────

    def _validate_int(self, value: str) -> bool:
        return value == "" or value.isdigit()

    def get_config(self) -> ScraperConfig | None:
        raw_postcodes = self._postcodes.get("1.0", "end")
        postcodes = list(
            dict.fromkeys(
                p.upper()
                for p in re.split(r"[,\n]+", raw_postcodes)
                if p.strip()
            )
        )
        if not postcodes:
            return None

        try:
            threshold = int(self._threshold_year.get() or "2010")
        except ValueError:
            threshold = 2010

        try:
            max_results = int(self._max_results.get() or "20")
        except ValueError:
            max_results = 20

        return ScraperConfig(
            postcodes=postcodes,
            filter_no_website=self._no_website_var.get(),
            filter_outdated=self._outdated_var.get(),
            threshold_year=threshold,
            max_results_per_postcode=max(1, max_results),
        )

    def set_scraping_state(self, active: bool) -> None:
        state = "disabled" if active else "normal"
        for widget in self._all_inputs:
            widget.configure(state=state)
        self._sc_var.set(False) if active else None
        self._brisbane_var.set(False) if active else None
        self._start_btn.configure(state="disabled" if active else "normal")
        self._stop_btn.configure(state="normal" if active else "disabled")
        self._clear_btn.configure(state="disabled" if active else "normal")
