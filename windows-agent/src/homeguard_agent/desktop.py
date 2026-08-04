from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import webbrowser
import logging

import uvicorn

from .config import Settings
from .instance_lock import SingleInstanceLock
from .logging_config import configure_logging, install_exception_hooks
from .runtime import Runtime
from .model_install import install_face_models

logger = logging.getLogger(__name__)


class DesktopApp:
    def __init__(self) -> None:
        self.settings = Settings()
        self.settings.ensure_directories()
        configure_logging(self.settings.logs_dir, debug=self.settings.debug)
        install_exception_hooks()
        self.lock = SingleInstanceLock(self.settings.data_dir / "homeguard.lock")
        self.lock.acquire()
        self.runtime = Runtime(self.settings)

        self.root = tk.Tk()
        self.root.title("HomeGuard Agent")
        self.root.geometry("760x560")
        self.root.minsize(680, 500)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self._server: uvicorn.Server | None = None
        self._server_thread: threading.Thread | None = None
        self._tray = None
        self._pairing_offer = None
        self._pairing_qr_photo = None

        self.status_var = tk.StringVar(value="Starting…")
        self.camera_var = tk.StringVar(value="Camera: starting")
        self.detector_var = tk.StringVar(value=f"Detector: {self.runtime.detector.name}")
        self.fps_var = tk.StringVar(value="Capture 0.0 FPS · AI 0.0 FPS")
        self.last_event_var = tk.StringVar(value="Last event: none")
        self.queue_var = tk.StringVar(value="Cloud queue: 0")
        self.disk_var = tk.StringVar(value="Disk: checking")
        self.pairing_status_var = tk.StringVar(value="Generate a temporary code to pair your phone.")
        self._build_ui()

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        header = ttk.Frame(self.root, padding=(20, 16))
        header.pack(fill="x")
        ttk.Label(header, text="HomeGuard", font=("Segoe UI", 24, "bold")).pack(side="left")
        self.state_badge = ttk.Label(header, text="STARTING")
        self.state_badge.pack(side="right")

        tabs = ttk.Notebook(self.root)
        tabs.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        dashboard = ttk.Frame(tabs, padding=18)
        pairing = ttk.Frame(tabs, padding=18)
        whitelist = ttk.Frame(tabs, padding=18)
        events = ttk.Frame(tabs, padding=18)
        logs = ttk.Frame(tabs, padding=18)
        settings = ttk.Frame(tabs, padding=18)
        tabs.add(dashboard, text="Dashboard")
        tabs.add(pairing, text="Pair phone")
        tabs.add(whitelist, text="Whitelist")
        tabs.add(events, text="Events")
        tabs.add(logs, text="Debug logs")
        tabs.add(settings, text="Settings")

        status = ttk.LabelFrame(dashboard, text="System status", padding=16)
        status.pack(fill="x")
        for variable in (
            self.status_var,
            self.camera_var,
            self.detector_var,
            self.fps_var,
            self.last_event_var,
            self.queue_var,
            self.disk_var,
        ):
            ttk.Label(status, textvariable=variable).pack(anchor="w", pady=2)

        controls = ttk.LabelFrame(dashboard, text="Local controls", padding=16)
        controls.pack(fill="x", pady=14)
        row1 = ttk.Frame(controls)
        row1.pack(fill="x")
        ttk.Button(row1, text="Resume camera", command=self.resume_camera).pack(side="left", padx=(0, 8))
        ttk.Button(row1, text="Privacy pause", command=self.pause_camera).pack(side="left", padx=(0, 8))
        ttk.Button(row1, text="Open API docs", command=self.open_docs).pack(side="left")
        row2 = ttk.Frame(controls)
        row2.pack(fill="x", pady=(12, 0))
        tk.Button(
            row2,
            text="EMERGENCY DISABLE",
            command=self.emergency_disable,
            bg="#b91c1c",
            fg="white",
            activebackground="#991b1b",
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=8,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(row2, text="Clear emergency locally", command=self.clear_emergency).pack(side="left")

        ttk.Label(
            dashboard,
            text=(
                "Emergency disable persists after restart and cannot be cleared from the phone.\n"
                "Closing this window keeps HomeGuard running in the tray."
            ),
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        pairing_header = ttk.LabelFrame(pairing, text="One-time QR pairing", padding=16)
        pairing_header.pack(fill="x")
        ttk.Label(
            pairing_header,
            text="The QR code expires after two minutes and cannot be reused. The phone receives its own revocable credential.",
            wraplength=650,
            justify="left",
        ).pack(anchor="w")
        self.pairing_qr_label = ttk.Label(pairing_header)
        self.pairing_qr_label.pack(pady=12)
        ttk.Label(pairing_header, textvariable=self.pairing_status_var, wraplength=650).pack(anchor="center")
        pair_buttons = ttk.Frame(pairing_header)
        pair_buttons.pack(pady=(12, 0))
        ttk.Button(pair_buttons, text="Generate new QR", command=self.generate_pairing_offer).pack(side="left", padx=4)
        ttk.Button(pair_buttons, text="Copy temporary link", command=self.copy_pairing_link).pack(side="left", padx=4)

        devices_box = ttk.LabelFrame(pairing, text="Paired phones", padding=16)
        devices_box.pack(fill="both", expand=True, pady=(14, 0))
        self.device_tree = ttk.Treeview(devices_box, columns=("name", "paired", "seen", "state"), show="headings", height=7)
        for name, width in zip(("name", "paired", "seen", "state"), (180, 160, 160, 100)):
            self.device_tree.heading(name, text=name.title())
            self.device_tree.column(name, width=width, anchor="w")
        self.device_tree.pack(fill="both", expand=True)
        ttk.Button(devices_box, text="Revoke selected phone", command=self.revoke_selected_device).pack(anchor="e", pady=(10, 0))

        whitelist_box = ttk.LabelFrame(whitelist, text="Local face whitelist", padding=16)
        whitelist_box.pack(fill="both", expand=True)
        self.whitelist_status_var = tk.StringVar()
        ttk.Label(
            whitelist_box,
            textvariable=self.whitelist_status_var,
            wraplength=650,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))
        self.whitelist_tree = ttk.Treeview(whitelist_box, columns=("name", "samples"), show="headings", height=10)
        self.whitelist_tree.heading("name", text="Person")
        self.whitelist_tree.heading("samples", text="Samples")
        self.whitelist_tree.column("name", width=300, anchor="w")
        self.whitelist_tree.column("samples", width=100, anchor="center")
        self.whitelist_tree.pack(fill="both", expand=True)
        whitelist_buttons = ttk.Frame(whitelist_box)
        whitelist_buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(whitelist_buttons, text="Enroll current face", command=self.enroll_current_face).pack(side="left", padx=(0, 8))
        ttk.Button(whitelist_buttons, text="Test current face", command=self.test_current_face).pack(side="left", padx=(0, 8))
        ttk.Button(whitelist_buttons, text="Remove selected", command=self.remove_selected_person).pack(side="left", padx=(0, 8))
        ttk.Button(whitelist_buttons, text="Install face models", command=self.install_face_models).pack(side="right")

        columns = ("time", "result", "confidence", "status")
        self.event_tree = ttk.Treeview(events, columns=columns, show="headings", height=16)
        for name, width in zip(columns, (180, 150, 110, 160)):
            self.event_tree.heading(name, text=name.title())
            self.event_tree.column(name, width=width, anchor="w")
        self.event_tree.pack(fill="both", expand=True)
        ttk.Button(events, text="Refresh events", command=self._refresh_events).pack(anchor="e", pady=(10, 0))

        self.log_text = tk.Text(logs, wrap="none", font=("Consolas", 9), state="disabled")
        self.log_text.pack(fill="both", expand=True)
        log_buttons = ttk.Frame(logs)
        log_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(log_buttons, text="Refresh", command=self._refresh_logs).pack(side="left")
        ttk.Button(log_buttons, text="Open log folder", command=self.open_log_folder).pack(side="left", padx=8)

        settings_box = ttk.LabelFrame(settings, text="Diagnostics", padding=16)
        settings_box.pack(fill="x")
        ttk.Label(settings_box, text=f"Data folder: {self.settings.data_dir.resolve()}").pack(anchor="w")
        ttk.Label(settings_box, text=f"API: {self.settings.api_host}:{self.settings.api_port}").pack(anchor="w")
        ttk.Label(settings_box, text=f"Version: {self.runtime.VERSION}").pack(anchor="w")
        ttk.Label(settings_box, text=f"Detection zone: {self.settings.detection_zone}").pack(anchor="w")
        ttk.Label(settings_box, text=f"Exclusion zones: {len(self.settings.exclusion_zones)}").pack(anchor="w")

    def start(self) -> None:
        self.runtime.start()
        config = uvicorn.Config(
            self.runtime.app,
            host=self.settings.api_host,
            port=self.settings.api_port,
            log_level="debug" if self.settings.debug else "info",
            access_log=False,
            log_config=None,
        )
        self._server = uvicorn.Server(config)
        self._server_thread = threading.Thread(target=self._server.run, name="api-server", daemon=True)
        self._server_thread.start()
        self._start_tray()
        self.generate_pairing_offer()
        self._refresh_status()
        self.root.mainloop()

    def _start_tray(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            return
        image = Image.new("RGB", (64, 64), "#111827")
        draw = ImageDraw.Draw(image)
        draw.ellipse((12, 12, 52, 52), fill="#22c55e")
        draw.ellipse((25, 25, 39, 39), fill="#111827")
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda: self.root.after(0, self.show_window)),
            pystray.MenuItem("Privacy pause", lambda: self.root.after(0, self.pause_camera)),
            pystray.MenuItem("Resume camera", lambda: self.root.after(0, self.resume_camera)),
            pystray.MenuItem("Quit", lambda: self.root.after(0, self.quit)),
        )
        self._tray = pystray.Icon("HomeGuard", image, "HomeGuard Agent", menu)
        threading.Thread(target=self._tray.run, name="system-tray", daemon=True).start()

    def _refresh_status(self) -> None:
        camera = self.runtime.camera
        state = self.runtime.state_store.snapshot()
        if state.emergency_disabled:
            badge = "EMERGENCY DISABLED"
        elif state.privacy_paused:
            badge = "PRIVACY PAUSED"
        elif camera.active:
            badge = "ACTIVE"
        else:
            badge = "WAITING FOR CAMERA"
        self.state_badge.configure(text=badge)
        self.status_var.set(f"API: http://{self.settings.api_host}:{self.settings.api_port}")
        self.camera_var.set(
            "Camera: active" if camera.active else f"Camera: inactive{f' · {camera.last_error}' if camera.last_error else ''}"
        )
        self.fps_var.set(f"Capture {camera.fps:.1f} FPS · AI {camera.inference_fps:.1f} FPS")
        self.last_event_var.set(
            f"Last event: {camera.last_event_at.astimezone().strftime('%Y-%m-%d %H:%M:%S') if camera.last_event_at else 'none'}"
        )
        self.queue_var.set(f"Cloud queue: {self.runtime.database.upload_queue_depth()}")
        self.disk_var.set(f"Free disk: {self.runtime.maintenance.disk_free_mb:,} MB")
        self._refresh_events()
        self._refresh_devices()
        self._refresh_whitelist()
        self._refresh_logs()
        self.root.after(2000, self._refresh_status)

    def _refresh_events(self) -> None:
        existing = set(self.event_tree.get_children())
        records = self.runtime.database.list_events(limit=100)
        wanted = set()
        for event in records:
            wanted.add(event.id)
            values = (
                event.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                event.person_name or event.face_result.value,
                f"{event.person_confidence * 100:.0f}%",
                event.notification_status,
            )
            if event.id in existing:
                self.event_tree.item(event.id, values=values)
            else:
                self.event_tree.insert("", "end", iid=event.id, values=values)
        for item in existing - wanted:
            self.event_tree.delete(item)

    def _refresh_whitelist(self) -> None:
        if not hasattr(self, "whitelist_tree"):
            return
        engine = self.runtime.face_engine
        if engine is None or not engine.available:
            reason = getattr(engine, "unavailable_reason", "Face whitelist disabled") if engine else "Face whitelist disabled"
            self.whitelist_status_var.set(
                f"Face recognition is unavailable: {reason}. People will be treated as unknown. Install the two local models to enable it."
            )
        else:
            self.whitelist_status_var.set(
                "Face recognition is active. It is conservative: unclear or unmatched faces are treated as unknown. Raw enrollment photos are not saved."
            )
        existing = set(self.whitelist_tree.get_children())
        people = self.runtime.face_whitelist.people()
        wanted = set(people)
        for name, samples in people.items():
            if name in existing:
                self.whitelist_tree.item(name, values=(name, samples))
            else:
                self.whitelist_tree.insert("", "end", iid=name, values=(name, samples))
        for item in existing - wanted:
            self.whitelist_tree.delete(item)

    def enroll_current_face(self) -> None:
        engine = self.runtime.face_engine
        if engine is None or not engine.available:
            messagebox.showerror("HomeGuard", "Install the YuNet and SFace models first.")
            return
        name = simpledialog.askstring("Enroll face", "Person name:", parent=self.root)
        if not name:
            return
        frame = self.runtime.camera.snapshot_frame()
        if frame is None:
            messagebox.showerror("HomeGuard", "No camera frame is available.")
            return
        embedding = engine.extract_embedding(frame)
        if embedding is None:
            messagebox.showerror("HomeGuard", "No clear face was found. Face the camera and try again.")
            return
        try:
            count = self.runtime.face_whitelist.enroll(name, embedding)
        except ValueError as exc:
            messagebox.showerror("HomeGuard", str(exc))
            return
        self._refresh_whitelist()
        messagebox.showinfo("HomeGuard", f"Saved sample {count} for {name.strip()}. Add 3–5 varied samples for better reliability.")

    def test_current_face(self) -> None:
        engine = self.runtime.face_engine
        frame = self.runtime.camera.snapshot_frame()
        if engine is None or not engine.available or frame is None:
            messagebox.showerror("HomeGuard", "Face models and an active camera are required.")
            return
        match = engine.recognize(frame)
        if not match.usable_face:
            messagebox.showwarning("HomeGuard", "No clear face was found. This would be treated as unknown.")
        elif match.matched:
            messagebox.showinfo("HomeGuard", f"Matched {match.person_name} · similarity {match.similarity:.3f}")
        else:
            messagebox.showwarning("HomeGuard", f"Face is unknown · best similarity {match.similarity:.3f}")

    def remove_selected_person(self) -> None:
        selected = self.whitelist_tree.selection()
        if not selected:
            messagebox.showinfo("HomeGuard", "Select a person first.")
            return
        name = selected[0]
        if messagebox.askyesno("Remove person", f"Remove {name} and all local embeddings?"):
            self.runtime.face_whitelist.remove(name)
            self._refresh_whitelist()

    def install_face_models(self) -> None:
        target_dir = self.settings.data_dir / "models"

        def run_install() -> None:
            try:
                install_face_models(target_dir)
                self.runtime.reload_face_engine()
                self.root.after(0, self._refresh_whitelist)
                self.root.after(0, lambda: messagebox.showinfo("HomeGuard", "Face models installed and loaded."))
            except Exception as exc:
                logger.exception("Face model installation failed")
                self.root.after(0, lambda: messagebox.showerror("HomeGuard", f"Model installation failed: {exc}"))

        threading.Thread(target=run_install, name="model-installer", daemon=True).start()


    def _refresh_logs(self) -> None:
        path = self.settings.logs_dir / "homeguard.log"
        if not path.exists():
            return
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", "\n".join(lines))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def open_docs(self) -> None:
        webbrowser.open(f"http://127.0.0.1:{self.settings.api_port}/docs")

    def open_log_folder(self) -> None:
        webbrowser.open(self.settings.logs_dir.resolve().as_uri())

    def generate_pairing_offer(self) -> None:
        try:
            import qrcode
            from PIL import ImageTk

            offer = self.runtime.pairing.create_offer()
            image = qrcode.make(offer.uri).convert("RGB").resize((230, 230))
            self._pairing_qr_photo = ImageTk.PhotoImage(image)
            self.pairing_qr_label.configure(image=self._pairing_qr_photo)
            self._pairing_offer = offer
            local_expiry = offer.expires_at.astimezone().strftime("%H:%M:%S")
            self.pairing_status_var.set(f"Scan now · expires at {local_expiry} · {offer.base_url}")
        except Exception as exc:
            logger.exception("Failed generating pairing QR")
            messagebox.showerror("HomeGuard", f"Could not generate pairing QR: {exc}")

    def copy_pairing_link(self) -> None:
        if self._pairing_offer is None:
            self.generate_pairing_offer()
        if self._pairing_offer is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self._pairing_offer.uri)
        messagebox.showinfo("HomeGuard", "Temporary one-time pairing link copied.")

    def _refresh_devices(self) -> None:
        if not hasattr(self, "device_tree"):
            return
        existing = set(self.device_tree.get_children())
        wanted = set()
        for device in self.runtime.database.list_paired_devices():
            device_id = str(device["id"])
            wanted.add(device_id)
            state = "revoked" if device.get("revoked_at") else "active"
            values = (
                device.get("name") or "Android phone",
                str(device.get("created_at") or "")[:19].replace("T", " "),
                str(device.get("last_seen_at") or "")[:19].replace("T", " "),
                state,
            )
            if device_id in existing:
                self.device_tree.item(device_id, values=values)
            else:
                self.device_tree.insert("", "end", iid=device_id, values=values)
        for item in existing - wanted:
            self.device_tree.delete(item)

    def revoke_selected_device(self) -> None:
        selected = self.device_tree.selection()
        if not selected:
            messagebox.showinfo("HomeGuard", "Select a paired phone first.")
            return
        device_id = selected[0]
        if messagebox.askyesno("Revoke phone", "This phone will immediately lose access. Continue?"):
            if self.runtime.database.revoke_paired_device(device_id):
                logger.warning("Phone revoked locally", extra={"device_id": device_id})
                self._refresh_devices()


    def pause_camera(self) -> None:
        self.runtime.camera.pause()

    def resume_camera(self) -> None:
        try:
            self.runtime.camera.resume()
        except PermissionError:
            messagebox.showerror("HomeGuard", "Emergency disable must be cleared locally first.")

    def emergency_disable(self) -> None:
        if not messagebox.askyesno(
            "Emergency disable",
            "Disable camera, detection, streaming, and remote audio until cleared locally?",
        ):
            return
        self.runtime.camera.emergency_disable("Desktop emergency button")
        self.runtime.audio.stop()
        messagebox.showwarning("HomeGuard", "Emergency disable is active and will survive restart.")

    def clear_emergency(self) -> None:
        if not self.runtime.state_store.snapshot().emergency_disabled:
            messagebox.showinfo("HomeGuard", "Emergency disable is not active.")
            return
        if messagebox.askyesno("Clear emergency", "Re-enable camera and remote features on this PC?"):
            self.runtime.camera.clear_emergency_locally()

    def hide_window(self) -> None:
        if self._tray is None:
            self.quit()
        else:
            self.root.withdraw()

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def quit(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        self.runtime.stop()
        self.lock.release()
        if self._tray is not None:
            self._tray.stop()
        self.root.destroy()


def main() -> None:
    try:
        DesktopApp().start()
    except RuntimeError as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("HomeGuard", str(exc))
        root.destroy()


if __name__ == "__main__":
    main()
