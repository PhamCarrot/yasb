"""Shared default multimedia render-endpoint state for Windows widgets."""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

try:
    import comtypes
    from pycaw.callbacks import MMNotificationClient
    from pycaw.constants import DEVICE_STATE
    from pycaw.pycaw import AudioUtilities, EDataFlow, ERole

    _WINDOWS_AUDIO_AVAILABLE = True
except ImportError:
    comtypes = None
    AudioUtilities = EDataFlow = ERole = DEVICE_STATE = None
    _WINDOWS_AUDIO_AVAILABLE = False

    class MMNotificationClient:
        pass


from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger("AudioOutputService")
_ENDPOINT_GUID_RE = re.compile(r"(\{[0-9a-fA-F-]{36}\})$")


@dataclass(frozen=True)
class AudioOutputState:
    endpoint_id: str = ""
    endpoint_guid: str = ""
    friendly_name: str = ""

    @property
    def available(self) -> bool:
        return bool(self.endpoint_id)


def extract_endpoint_guid(endpoint_id: str) -> str:
    """Return the endpoint GUID portion used by Equalizer APO Device matching."""
    match = _ENDPOINT_GUID_RE.search(endpoint_id or "")
    return match.group(1) if match else ""


class _DefaultRenderWatcher(MMNotificationClient):
    def __init__(self, service: DefaultAudioOutputService) -> None:
        super().__init__()
        self._service = service

    def on_default_device_changed(self, flow, flow_id, role, role_id, default_device_id) -> None:
        if flow_id == EDataFlow.eRender.value and role_id == ERole.eMultimedia.value:
            self._service.request_refresh(force=True)

    def on_device_state_changed(self, device_id, new_state, new_state_id) -> None:
        state = self._service.state
        if device_id != state.endpoint_id:
            return
        if new_state_id in (DEVICE_STATE.ACTIVE.value, DEVICE_STATE.DISABLED.value, DEVICE_STATE.UNPLUGGED.value):
            self._service.request_refresh(force=True)


class DefaultAudioOutputService(QObject):
    """Singleton cache for the default eRender/eMultimedia endpoint.

    Native notifications only request a refresh. Endpoint COM queries run on a
    single worker and return plain strings to the Qt thread.
    """

    default_output_changed = pyqtSignal(object)
    default_output_refreshed = pyqtSignal(object)
    _refresh_requested = pyqtSignal(bool)
    _query_finished = pyqtSignal(int, object, bool)

    _instance: DefaultAudioOutputService | None = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        super().__init__()
        self._state = AudioOutputState()
        self._generation = 0
        self._closed = False
        self._query_running = False
        self._pending_force = False
        self._enumerator = None
        self._watcher = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yasb-audio-output")
        self._refresh_requested.connect(self._schedule_refresh)
        self._query_finished.connect(self._accept_query)
        self._register_watcher()
        self.request_refresh()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @classmethod
    def instance(cls) -> DefaultAudioOutputService:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def state(self) -> AudioOutputState:
        return self._state

    def request_refresh(self, force: bool = False) -> None:
        if not self._closed:
            self._refresh_requested.emit(bool(force))

    def _schedule_refresh(self, force: bool = False) -> None:
        if self._closed:
            return
        if self._query_running:
            if force:
                self._pending_force = True
            return
        self._start_query(bool(force))

    def _start_query(self, force: bool) -> None:
        if self._closed:
            return
        self._generation += 1
        generation = self._generation
        self._query_running = True
        future = self._executor.submit(self._query_state)
        future.add_done_callback(lambda result, g=generation, f=force: self._query_done(g, result, f))

    @staticmethod
    def _query_state() -> AudioOutputState:
        if not _WINDOWS_AUDIO_AVAILABLE:
            return AudioOutputState()
        comtypes.CoInitialize()
        try:
            enumerator = AudioUtilities.GetDeviceEnumerator()
            endpoint = enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender.value, ERole.eMultimedia.value)
            endpoint_id = str(endpoint.GetId() or "")
            devices = AudioUtilities.GetAllDevices(
                data_flow=EDataFlow.eRender.value,
                device_state=DEVICE_STATE.ACTIVE.value,
            )
            friendly_name = next(
                (str(device.FriendlyName or "") for device in devices if str(device.id) == endpoint_id), ""
            )
            return AudioOutputState(endpoint_id, extract_endpoint_guid(endpoint_id), friendly_name)
        finally:
            comtypes.CoUninitialize()

    def _query_done(self, generation, future, force: bool) -> None:
        try:
            state = future.result()
        except Exception:
            logger.debug("Default output lookup failed", exc_info=True)
            state = AudioOutputState()
        try:
            self._query_finished.emit(generation, state, force)
        except RuntimeError:
            pass

    def _accept_query(self, generation: int, state: AudioOutputState, force: bool) -> None:
        if self._closed or generation != self._generation:
            return

        changed = state != self._state
        if changed:
            self._state = state
            self.default_output_changed.emit(state)

        pending_force = self._pending_force
        self._query_running = False

        # If a forced native event arrived while this query was running, defer
        # capture reconsideration until one fresh forced query has sampled the
        # endpoint after that event. This also coalesces force/normal/force
        # bursts into a single final reopen notification.
        if not pending_force and (changed or force):
            self.default_output_refreshed.emit(state)

        if pending_force:
            self._pending_force = False
            self._start_query(True)

    def _register_watcher(self) -> None:
        if not _WINDOWS_AUDIO_AVAILABLE:
            return
        try:
            self._enumerator = AudioUtilities.GetDeviceEnumerator()
            self._watcher = _DefaultRenderWatcher(self)
            self._enumerator.RegisterEndpointNotificationCallback(self._watcher)
        except Exception:
            self._enumerator = None
            self._watcher = None
            logger.warning("Default output notifications unavailable", exc_info=True)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pending_force = False
        self._query_running = False
        watcher, self._watcher = self._watcher, None
        enumerator, self._enumerator = self._enumerator, None
        if watcher is not None and enumerator is not None:
            try:
                enumerator.UnregisterEndpointNotificationCallback(watcher)
            except Exception:
                logger.debug("Unable to unregister default output watcher", exc_info=True)
        self._executor.shutdown(wait=False, cancel_futures=True)
