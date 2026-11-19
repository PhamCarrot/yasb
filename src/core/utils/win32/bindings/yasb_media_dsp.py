"""Bindings for the optional x64 Media V2 DSP library."""

from ctypes import CDLL, c_int32, c_uint32, c_uint64, c_void_p


class MediaDspLibrary:
    def __init__(self, path: str) -> None:
        self._dll = CDLL(path, use_last_error=True)
        self.info = self._dll.YasbMediaProtocolInfo
        self.info.argtypes = [c_void_p, c_uint32]
        self.info.restype = c_int32
        self.bootstrap = self._dll.YasbMediaBootstrapInit
        self.bootstrap.argtypes = [c_void_p, c_uint32]
        self.bootstrap.restype = c_int32
        self.create = self._dll.YasbMediaBrokerCreate
        self.create.argtypes = [c_void_p, c_uint32]
        self.create.restype = c_void_p
        self.publish = self._dll.YasbMediaBrokerPublish
        self.publish.argtypes = [c_void_p, c_void_p, c_uint32, c_void_p, c_uint64]
        self.publish.restype = c_int32
        self.reports = self._dll.YasbMediaBrokerReports
        self.reports.argtypes = [c_void_p, c_void_p, c_uint32]
        self.reports.restype = c_uint32
        self.destroy = self._dll.YasbMediaBrokerDestroy
        self.destroy.argtypes = [c_void_p]
        self.destroy.restype = None
