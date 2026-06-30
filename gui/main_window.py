import asyncio
import ctypes
import os
import queue
import sys
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from gui.filter_panel import FilterPanel
from gui.results_table import ResultsTable
from scraper.maps_scraper import MapsScraper, ScraperConfig
from exporter.excel_exporter import ExcelExporter


def _run_scraper_thread(
    config: ScraperConfig,
    result_queue: queue.Queue,
    stop_event: threading.Event,
) -> None:
    async def _entry() -> None:
        scraper = MapsScraper(config, result_queue, stop_event)
        await scraper.scrape()

    try:
        asyncio.run(_entry())
    except Exception as exc:
        result_queue.put({"type": "error", "message": f"Fatal error: {exc}"})
    finally:
        result_queue.put({"type": "done"})


def _set_app_icon(window: ctk.CTk) -> None:
    icon_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon.ico"
    )
    if not os.path.exists(icon_path):
        return
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "GoogleMapsBusinessScraper.1.0"
            )
        except Exception:
            pass
    try:
        window.iconbitmap(icon_path)
    except Exception:
        pass


class MainWindow(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Google Maps Business Scraper")
        self.minsize(1100, 700)
        self.geometry("1300x780")
        _set_app_icon(self)

        self._result_queue: queue.Queue = queue.Queue()
        self._stop_event: threading.Event = threading.Event()
        self._scraper_thread: threading.Thread | None = None
        self._all_results: list[dict] = []
        self._is_scraping = False
        self._poll_active = False

        self._build_layout()

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=260)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        self._filter_panel = FilterPanel(
            self,
            start_callback=self.start_scraping,
            stop_callback=self.stop_scraping,
            clear_callback=self.clear_results,
        )
        self._filter_panel.grid(row=0, column=0, sticky="nsew")

        self._results_table = ResultsTable(self)
        self._results_table.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        bottom = ctk.CTkFrame(self, height=44, corner_radius=0)
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew")
        bottom.grid_columnconfigure(1, weight=1)

        self._progress = ctk.CTkProgressBar(bottom, width=260)
        self._progress.set(0)
        self._progress.grid(row=0, column=0, padx=(12, 8), pady=10)

        self._status_label = ctk.CTkLabel(
            bottom, text="Ready.", font=ctk.CTkFont(size=11), anchor="w"
        )
        self._status_label.grid(row=0, column=1, padx=(0, 8), pady=10, sticky="w")

        self._export_btn = ctk.CTkButton(
            bottom,
            text="Export to Excel",
            command=self.export_results,
            state="disabled",
            fg_color="#1565C0",
            hover_color="#0D47A1",
            width=150,
        )
        self._export_btn.grid(row=0, column=2, padx=(8, 12), pady=8)

    def start_scraping(self) -> None:
        config = self._filter_panel.get_config()
        if config is None:
            messagebox.showwarning(
                "Missing input",
                "Please enter at least one postcode.",
            )
            return

        if not config.filter_no_website and not config.filter_outdated:
            messagebox.showwarning(
                "No filter selected",
                "Please tick at least one filter (No website / Outdated website).",
            )
            return

        self._all_results.clear()
        self._results_table.clear()
        self._progress.set(0)
        self._export_btn.configure(state="disabled")
        self._is_scraping = True
        self._filter_panel.set_scraping_state(True)

        self._result_queue = queue.Queue()
        self._stop_event = threading.Event()

        self._scraper_thread = threading.Thread(
            target=_run_scraper_thread,
            args=(config, self._result_queue, self._stop_event),
            daemon=True,
        )
        self._scraper_thread.start()

        if not self._poll_active:
            self._poll_active = True
            self.after(100, self._poll_queue)

    def stop_scraping(self) -> None:
        self._stop_event.set()
        self._status_label.configure(text="Stopping...")

    def clear_results(self) -> None:
        if self._is_scraping:
            return
        self._all_results.clear()
        self._results_table.clear()
        self._progress.set(0)
        self._export_btn.configure(state="disabled")
        self._status_label.configure(
            text="Ready.", text_color=ctk.ThemeManager.theme["CTkLabel"]["text_color"]
        )

    def _poll_queue(self) -> None:
        done = False
        try:
            while True:
                msg = self._result_queue.get_nowait()
                mtype = msg.get("type")
                if mtype == "result":
                    data = msg["data"]
                    self._all_results.append(data)
                    self._results_table.add_row(data)
                elif mtype == "status":
                    self._status_label.configure(text=msg.get("message", ""))
                elif mtype == "progress":
                    self._progress.set(msg.get("value", 0))
                elif mtype == "error":
                    current = self._status_label.cget("text")
                    self._status_label.configure(
                        text=msg.get("message", "Error"), text_color="#FF6B6B"
                    )
                elif mtype == "done":
                    done = True
                    break
        except queue.Empty:
            pass

        if done:
            self._poll_active = False
            self._on_complete()
        else:
            self.after(100, self._poll_queue)

    def _on_complete(self) -> None:
        self._is_scraping = False
        self._filter_panel.set_scraping_state(False)
        self._progress.set(1.0)
        count = len(self._all_results)
        self._status_label.configure(
            text=f"Done — {count} result{'s' if count != 1 else ''} found.",
            text_color=ctk.ThemeManager.theme["CTkLabel"]["text_color"],
        )
        if count > 0:
            self._export_btn.configure(state="normal")

    def export_results(self) -> None:
        if not self._all_results:
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
            title="Save results as...",
        )
        if not path:
            return

        try:
            ExcelExporter(self._all_results).export(path)
            messagebox.showinfo("Exported", f"Results saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
