from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import CustomBaseModel
from core.validation.widgets.yasb.audio_visualizer import AudioVisualizerConfig


class MediaVisualizerScrollingLabelConfig(CustomBaseModel):
    """Marquee behaviour for titles wider than the label area."""

    enabled: bool = False
    # Pixels per second, converted to the ScrollingLabel timer interval.
    speed: int = Field(default=30, ge=1, le=250)
    # Pause in ms before scrolling starts and each time the text wraps back
    # to its start. 0 scrolls continuously.
    delay: int = Field(default=1500, ge=0, le=60000)
    style: Literal["left", "right", "bounce", "bounce-ease"] = "left"
    # Gap inserted between repeats while scrolling (left/right styles only).
    separator: str = "   "
    # Fade the label's own left/right edges while it scrolls.
    edge_fade: bool = True
    fade_width: int = Field(default=12, ge=1, le=200)


class MediaVisualizerConfig(AudioVisualizerConfig):
    """Audio Visualizer options plus a foreground media label.

    Every visualizer option (style, height, smoothness, sensitivity,
    auto_gain, framerate, bars/waves/dots, ...) is inherited unchanged, so an
    existing ``audio_visualizer`` block can be reused unchanged.
    """

    # Foreground media label
    show_label: bool = True
    label: str = "{title}"
    separator: str = " - "
    # Static label: truncate to this many characters (0 = no limit).
    # Scrolling label: maximum label width in characters (0 = no limit, so
    # nothing ever scrolls).
    max_label_length: int = Field(default=30, ge=0, le=200)
    scrolling_label: MediaVisualizerScrollingLabelConfig = MediaVisualizerScrollingLabelConfig()

    # Applies to the visualizer canvas only; the label keeps full opacity.
    visualizer_opacity: float = Field(default=1.0, ge=0.0, le=1.0)
