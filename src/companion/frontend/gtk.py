import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from companion.events import ApplicationError, ApplicationEvent, CharacterLoaded
from companion.frontend.animation import AnimationScheduler
from companion.frontend.model import FrontendError, PetPresentationModel, PetVisualState
from companion.frontend.observer import ScheduledEventObserver
from companion.frontend.runtime_thread import RuntimeApplication, RuntimeWorker


class PetWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application) -> None:
        super().__init__(application=application)
        self.set_title("Companion")
        self.set_decorated(False)
        self.set_default_size(320, 320)
        self.set_resizable(True)
        self.add_css_class("companion-pet-window")

        self._picture = Gtk.Picture()
        self._picture.set_can_shrink(True)
        self._picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.set_child(self._picture)
        self._textures: dict[Path, Gdk.Texture] = {}

        drag = Gtk.GestureClick(button=1)
        drag.connect("pressed", self._begin_move)
        self.add_controller(drag)

    def show_visual(self, path: Path) -> None:
        texture = self._textures.get(path)
        if texture is None:
            try:
                texture = Gdk.Texture.new_from_filename(str(path))
            except GLib.Error as exc:
                raise FrontendError(f"could not load character PNG: {path}") from exc
            self._textures[path] = texture
        self._picture.set_paintable(texture)

    def clear_texture_cache(self) -> None:
        self._textures.clear()

    def _begin_move(
        self, gesture: Gtk.GestureClick, presses: int, x: float, y: float
    ) -> None:
        del presses
        surface = self.get_surface()
        device = gesture.get_current_event_device()
        if isinstance(surface, Gdk.Toplevel) and device is not None:
            surface.begin_move(
                device,
                gesture.get_current_button(),
                x,
                y,
                gesture.get_current_event_time(),
            )


class GtkPetApplication(Gtk.Application):
    """GTK lifecycle owner; all widget access occurs on the GTK main thread."""

    def __init__(self, model: PetPresentationModel | None = None) -> None:
        super().__init__(
            application_id="org.companion.DesktopPet",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._model = model or PetPresentationModel()
        self._window: PetWindow | None = None
        self._worker: RuntimeWorker | None = None
        self._animation: AnimationScheduler | None = None
        self.observer = ScheduledEventObserver(self._schedule, self._consume_event)

    def attach_runtime(self, application: RuntimeApplication) -> None:
        if self._worker is not None:
            raise RuntimeError("GTK frontend runtime is already attached")
        self._worker = RuntimeWorker(application, on_finished=self._runtime_finished)

    def do_activate(self) -> None:
        if self._worker is None:
            raise RuntimeError("GTK frontend requires an attached runtime")
        if self._window is None:
            self._install_css()
            self._window = PetWindow(self)
            self._window.connect("close-request", self._window_closing)
            self._animation = AnimationScheduler(
                GLib.timeout_add,
                GLib.source_remove,
                self._window.show_visual,
            )
        self._window.present()
        if not self._worker.started:
            self._worker.start()

    def do_shutdown(self) -> None:
        if self._animation is not None:
            self._animation.stop()
        if self._worker is not None:
            self._worker.cancel()
            self._worker.join()
        Gtk.Application.do_shutdown(self)

    def request_shutdown(self) -> None:
        """Request cancellation and let Gtk.Application own final cleanup."""
        if self._animation is not None:
            self._animation.stop()
        if self._worker is not None:
            self._worker.cancel()
        self.quit()

    def _schedule(self, callback) -> int:
        return GLib.idle_add(callback)

    def _consume_event(self, event: ApplicationEvent) -> None:
        try:
            self._model.apply(event)
            if isinstance(event, ApplicationError):
                print(f"Companion error: {event.message}", file=sys.stderr)
            if self._window is None or self._animation is None:
                raise FrontendError("character window is not ready")
            if isinstance(event, CharacterLoaded):
                self._window.clear_texture_cache()
            self._animation.activate(
                self._model.visual_asset,
                animate=self._model.state is not PetVisualState.STOPPED,
            )
        except FrontendError as exc:
            print(f"Companion frontend error: {exc}", file=sys.stderr)
            if self._worker is not None:
                self._worker.cancel()
            self.quit()

    def _window_closing(self, window: PetWindow) -> bool:
        del window
        if self._animation is not None:
            self._animation.stop()
        if self._worker is not None:
            self._worker.cancel()
        return False

    def _runtime_finished(self, failure: BaseException | None) -> None:
        def finish() -> bool:
            if failure is not None:
                print("Companion runtime failed.", file=sys.stderr)
            self.quit()
            return False

        GLib.idle_add(finish)

    @staticmethod
    def _install_css() -> None:
        display = Gdk.Display.get_default()
        if display is None:
            raise FrontendError("no graphical display is available")
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b"window.companion-pet-window { background-color: transparent; }"
        )
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
