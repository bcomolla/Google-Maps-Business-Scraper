import tkinter as tk
from tkinter import ttk

import customtkinter as ctk


_COLUMNS = [
    ("num",            "#",               50),
    ("name",           "Business Name",   200),
    ("address",        "Address",         240),
    ("phone",          "Phone",           120),
    ("website",        "Website",         210),
    ("website_status", "Status",          110),
    ("last_evidence_date", "Last Evidence", 120),
    ("rating",         "Rating",          60),
    ("postcode",       "Postcode",        90),
]

_TAG_COLOURS = {
    "No Website": "#FFD7D7",
    "Outdated":   "#FFE5B4",
    "OK":         "#D7FFD7",
    "Unknown":    "#E8E8E8",
}


class ResultsTable(ctk.CTkFrame):
    def __init__(self, parent: ctk.CTk) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._sort_reverse: dict[str, bool] = {}
        self._build_table()

    def _build_table(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Custom.Treeview",
            rowheight=26,
            font=("Segoe UI", 10),
            background="#2B2B2B",
            foreground="#FFFFFF",
            fieldbackground="#2B2B2B",
            bordercolor="#3A3A3A",
        )
        style.configure(
            "Custom.Treeview.Heading",
            font=("Segoe UI", 10, "bold"),
            background="#1F538D",
            foreground="#FFFFFF",
            relief="flat",
        )
        style.map(
            "Custom.Treeview",
            background=[("selected", "#1F538D")],
            foreground=[("selected", "#FFFFFF")],
        )
        style.map(
            "Custom.Treeview.Heading",
            background=[("active", "#2E75B6")],
        )

        col_ids = [c[0] for c in _COLUMNS]
        self._tree = ttk.Treeview(
            self,
            columns=col_ids,
            show="headings",
            style="Custom.Treeview",
            selectmode="browse",
        )

        for col_id, label, width in _COLUMNS:
            self._tree.heading(
                col_id,
                text=label,
                command=lambda c=col_id: self._sort_by_column(c),
            )
            anchor = "center" if col_id in ("num", "rating", "website_status", "postcode") else "w"
            self._tree.column(col_id, width=width, minwidth=40, anchor=anchor, stretch=True)

        self._configure_tags()

        vsb = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

    def _configure_tags(self) -> None:
        for status, colour in _TAG_COLOURS.items():
            tag = status.lower().replace(" ", "_")
            self._tree.tag_configure(tag, background=colour, foreground="#1A1A1A")

    def add_row(self, data: dict) -> None:
        row_num = len(self._rows) + 1
        status = data.get("website_status", "Unknown")
        tag = status.lower().replace(" ", "_")

        values = (
            row_num,
            data.get("name", ""),
            data.get("address", ""),
            data.get("phone", ""),
            data.get("website", ""),
            status,
            data.get("last_evidence_date", ""),
            data.get("rating", ""),
            data.get("postcode", ""),
        )
        iid = self._tree.insert("", "end", values=values, tags=(tag,))
        self._rows.append(data)
        self._tree.see(iid)

    def clear(self) -> None:
        self._tree.delete(*self._tree.get_children())
        self._rows = []

    def get_all_rows(self) -> list[dict]:
        return self._rows

    def _sort_by_column(self, col: str) -> None:
        reverse = self._sort_reverse.get(col, False)
        col_ids = [c[0] for c in _COLUMNS]
        col_idx = col_ids.index(col)

        items = [
            (self._tree.set(iid, col), iid)
            for iid in self._tree.get_children("")
        ]

        try:
            items.sort(key=lambda t: float(t[0]) if t[0] else 0, reverse=reverse)
        except ValueError:
            items.sort(key=lambda t: t[0].lower(), reverse=reverse)

        for pos, (_, iid) in enumerate(items):
            self._tree.move(iid, "", pos)

        self._sort_reverse[col] = not reverse

        label_map = {c[0]: c[1] for c in _COLUMNS}
        arrow = " ↑" if not reverse else " ↓"
        self._tree.heading(col, text=label_map[col] + arrow)
        for other in col_ids:
            if other != col:
                self._tree.heading(other, text=label_map[other])
