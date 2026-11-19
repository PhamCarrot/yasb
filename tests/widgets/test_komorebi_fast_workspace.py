from __future__ import annotations

# pyright: reportPrivateUsage=false
from typing import Any

from core.widgets.komorebi.workspaces import WorkspaceButton, WorkspaceWidget


class FakeButton:
    def __init__(self, classes: str) -> None:
        self.classes = classes
        self.writes = 0

    def isHidden(self) -> bool:
        return False

    def property(self, name: str) -> str:
        assert name == "class"
        return self.classes

    def setProperty(self, name: str, value: str) -> None:
        assert name == "class"
        self.classes = value
        self.writes += 1


class FakeParent:
    def __init__(self, buttons: list[FakeButton]) -> None:
        self.workspace_buttons = buttons


class FakeClient:
    def __init__(self, workspace: dict[str, Any]) -> None:
        self.workspace = workspace

    def get_focused_workspace(self, screen: object) -> dict[str, Any]:
        return self.workspace

    def get_monocle_container(self, current: dict[str, Any]) -> None:
        return None

    def get_focused_window(self, container: dict[str, Any]) -> dict[str, int]:
        return {"hwnd": 1234 if container["id"] == "second" else 0}


def test_workspace_button_class_refresh_skips_unchanged_button_classes(monkeypatch: Any) -> None:
    button = FakeButton("ws-btn active button-1")
    owner: Any = WorkspaceButton.__new__(WorkspaceButton)
    owner.parent_widget = FakeParent([button])
    refreshes: list[FakeButton] = []
    monkeypatch.setattr("core.widgets.komorebi.workspaces.refresh_widget_style", refreshes.append)

    WorkspaceButton.update_visible_buttons(owner)
    WorkspaceButton.update_visible_buttons(owner)

    assert button.classes == "ws-btn active button-1"
    assert button.writes == 0
    assert refreshes == []


def test_workspace_prediction_uses_focused_container(monkeypatch: Any) -> None:
    owner: Any = WorkspaceWidget.__new__(WorkspaceWidget)
    owner.komorebi_screen = {"index": 2}
    workspace = {
        "index": 4,
        "containers": {"focused": 1, "elements": [{"id": "first"}, {"id": "second"}]},
    }
    owner._komorebic = FakeClient(workspace)

    assert owner._predicted_focused_hwnd({"monitors": {"focused": 2}}) == 1234
    assert owner._predicted_focused_hwnd({"monitors": {"focused": 1}}) is None
