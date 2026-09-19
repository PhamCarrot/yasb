import logging
from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter, ValidationError, model_validator
from PyQt6.QtGui import QColor

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel, KeybindingConfig

logger = logging.getLogger("MediaV2")

Shape = Literal["square", "rounded", "circle"]
Preset = Literal["Flat", "Bass", "Treble", "Vocal", "Pop", "Rock", "Jazz", "Classic", "Custom"]
Gain = Annotated[int, Field(ge=-12, le=12)]
LEGACY_BOOLEAN = TypeAdapter(bool)


class MediaBackgroundConfig(CustomBaseModel):
    # Window/DWM blur is a popup-shell concern and lives on MediaV2PopupConfig.
    mode: Literal["color", "album_art", "image"] = "album_art"
    color: str | None = None
    image: str = ""
    blur_radius: int = Field(default=18, ge=0, le=64)
    ambient_motion: bool = True
    ambient_paused_opacity: float = Field(default=0.01, ge=0.0, le=0.08, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def migrate_qss_mode(cls, data: Any):
        if isinstance(data, dict) and data.get("mode") == "qss":
            values = dict(data)
            values["mode"] = "color"
            logger.warning("[DEPRECATED] MediaBackgroundConfig: mode 'qss' renamed to 'color'.")
            return values
        return data

    @model_validator(mode="after")
    def require_image(self):
        if self.mode == "image" and not self.image.strip():
            raise ValueError("popup.background.image is required in image mode")
        if self.color is not None and not QColor(self.color).isValid():
            raise ValueError("popup.background.color must be a valid Qt color, including an alpha-capable hex color")
        return self


class MediaDiscConfig(CustomBaseModel):
    spin: bool = True
    visualizer: bool = True
    rhythm: bool = True
    glow: bool = True
    rhythm_strength: float = Field(default=1.0, ge=0.0, le=3.0, allow_inf_nan=False)
    glow_strength: float = Field(default=1.0, ge=0.0, le=3.0, allow_inf_nan=False)
    framerate: int = Field(default=30, ge=15, le=60)


class MediaEqualizerApoConfig(CustomBaseModel):
    enabled: bool = False
    target_device: Literal["default"] = "default"
    auto_preamp: bool = True
    preamp_db: float = Field(default=0.0, ge=-24.0, le=12.0, allow_inf_nan=False)
    write_debounce_ms: int = Field(default=100, ge=50, le=500)
    manage_include: bool = False


class MediaEqualizerConfig(CustomBaseModel):
    preset: Preset = "Flat"
    custom_bands: list[Gain] = Field(default_factory=lambda: [0] * 10, min_length=10, max_length=10)
    preset_effect: Literal["lightning", "ripple", "center_pulse", "none"] = "lightning"
    effect_speed: float = Field(default=1.0, ge=0.4, le=3.0, allow_inf_nan=False)
    backend: Literal["visual", "equalizer_apo"] = "visual"
    apo: MediaEqualizerApoConfig = Field(default_factory=MediaEqualizerApoConfig)

    @model_validator(mode="before")
    @classmethod
    def migrate_blur_slide(cls, data: Any):
        if isinstance(data, dict) and data.get("preset_effect") == "blur_slide":
            values = dict(data)
            values["preset_effect"] = "none"
            logger.warning("[DEPRECATED] MediaEqualizerConfig: preset_effect 'blur_slide' was removed; using 'none'.")
            return values
        return data


class MediaBorderConfig(CustomBaseModel):
    framerate: int = Field(default=60, ge=15, le=120)
    charge_duration: float = Field(default=1.2, ge=0.2, le=5.0, allow_inf_nan=False)
    rotation_duration: float = Field(default=5.0, ge=1.0, le=30.0, allow_inf_nan=False)


class MediaScrollingConfig(CustomBaseModel):
    speed: float = Field(default=40.0, ge=5.0, le=200.0, allow_inf_nan=False)
    delay: int = Field(default=3000, ge=0, le=10000)


class MediaBarScrollingConfig(MediaScrollingConfig):
    enabled: bool = True


class MediaProgressConfig(CustomBaseModel):
    smoothing_ms: int = Field(default=250, ge=0, le=2000)
    show_handle: bool = True


class MediaControlsConfig(CustomBaseModel):
    size: int = Field(default=30, ge=20, le=96)


class MediaV2PopupConfig(CustomBaseModel):
    # Canonical YASB popup/window vocabulary.
    blur: bool = True
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "System"
    alignment: Literal["left", "right", "center"] = "right"
    direction: Literal["up", "down"] = "down"
    offset_top: int = Field(default=6, ge=-500, le=500)
    offset_left: int = Field(default=0, ge=-500, le=500)

    # Media V2 content options.
    show_equalizer: bool = True
    scroll_title: bool = True
    scroll_artist: bool = False
    scrolling_label: MediaScrollingConfig = Field(default_factory=MediaScrollingConfig)
    progress: MediaProgressConfig = Field(default_factory=MediaProgressConfig)
    controls: MediaControlsConfig = Field(default_factory=lambda: MediaControlsConfig(size=43))
    artwork_position: Literal["left", "right", "top", "hidden"] = "left"
    detail_order: list[Literal["title", "artist", "output", "timeline", "controls"]] = Field(
        default_factory=lambda: ["title", "artist", "output", "timeline", "controls"],
        min_length=1,
        json_schema_extra={"uniqueItems": True},
    )
    timestamps: Literal["above", "below", "inline", "hidden"] = "below"
    time_display: Literal["total", "remaining"] = "total"
    equalizer_position: Literal["top", "bottom"] = "bottom"
    show_separator: bool = True
    disc: MediaDiscConfig = Field(default_factory=MediaDiscConfig)
    equalizer: MediaEqualizerConfig = Field(default_factory=MediaEqualizerConfig)
    background: MediaBackgroundConfig = Field(default_factory=MediaBackgroundConfig)
    border: MediaBorderConfig = Field(default_factory=MediaBorderConfig)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_popup_options(cls, data: Any):
        """Accept the old Media V2 popup vocabulary without keeping two public APIs.

        Canonical configuration uses PopupWidget-style alignment/direction/offsets.
        Legacy screen placement cannot be represented exactly by PopupWidget, so it
        is converted to the nearest widget-relative offsets and logged clearly.
        """
        if not isinstance(data, dict):
            return data
        values = dict(data)

        if "scrolling" in values:
            legacy_scrolling = values.pop("scrolling")
            if "scrolling_label" not in values:
                values["scrolling_label"] = legacy_scrolling
            logger.warning("[DEPRECATED] MediaV2PopupConfig: 'scrolling' renamed to 'scrolling_label'.")

        background = values.get("background")
        if isinstance(background, dict) and "native_blur" in background:
            background = dict(background)
            raw_native_blur = background.pop("native_blur")
            try:
                native_blur = LEGACY_BOOLEAN.validate_python(raw_native_blur)
            except ValidationError:
                raise ValueError("popup.background.native_blur must be a recognized boolean value") from None
            values["background"] = background
            if "blur" not in values:
                values["blur"] = native_blur
            logger.warning("[DEPRECATED] MediaV2PopupConfig: 'background.native_blur' moved to popup.blur.")

        placement = values.pop("placement", None)
        widget_offset = values.pop("widget_offset", None)
        edge_offset = values.pop("edge_offset", None)
        bar_offset = values.pop("bar_offset", None)

        if placement is not None:
            logger.warning(
                "[DEPRECATED] MediaV2PopupConfig: 'placement' was removed; PopupWidget now uses parent-relative positioning."
            )
        if widget_offset is not None:
            logger.warning("[DEPRECATED] MediaV2PopupConfig: 'widget_offset' renamed to 'offset_top'.")
        if edge_offset is not None:
            logger.warning(
                "[DEPRECATED] MediaV2PopupConfig: 'edge_offset' is only approximated for legacy screen placement; use 'offset_left'."
            )
        if bar_offset is not None:
            logger.warning(
                "[DEPRECATED] MediaV2PopupConfig: 'bar_offset' is only approximated for legacy screen placement; use 'offset_top'."
            )

        if values.get("direction") == "auto":
            logger.warning(
                "[DEPRECATED] MediaV2PopupConfig: direction 'auto' is not part of the canonical PopupWidget API; using 'down'."
            )
            values["direction"] = "down"

        if "offset_top" not in values:
            if widget_offset is not None:
                values["offset_top"] = widget_offset
            elif placement == "screen":
                values["offset_top"] = 52 if bar_offset is None else bar_offset
            elif bar_offset is not None:
                values["offset_top"] = bar_offset

        if "offset_left" not in values and placement == "screen":
            values["offset_left"] = 5 if edge_offset is None else edge_offset

        return values

    @model_validator(mode="after")
    def unique_sections(self):
        if len(set(self.detail_order)) != len(self.detail_order):
            raise ValueError("popup.detail_order must not contain duplicate sections")
        return self


class MediaV2Config(CustomBaseModel):
    class_name: str = ""
    hide_empty: bool = False
    compact: bool = False
    layout: Literal["standard", "minimal"] = "standard"
    artwork_shape: Shape = "rounded"
    controls_shape: Shape = "rounded"
    scale: float = Field(default=1.0, ge=0.75, le=2.0, allow_inf_nan=False)
    artwork_size: int = Field(default=28, ge=16, le=64)
    border_radius: int = Field(default=8, ge=0, le=32)
    font_family: str = "Adwaita Mono"
    use_default_styles: bool = True
    scrolling_label: MediaBarScrollingConfig = Field(default_factory=MediaBarScrollingConfig)
    controls: MediaControlsConfig = Field(default_factory=MediaControlsConfig)
    popup: MediaV2PopupConfig = Field(default_factory=MediaV2PopupConfig)
    callbacks: CallbacksConfig = Field(
        default_factory=lambda: CallbacksConfig(
            on_left="toggle_media_menu", on_middle="play_pause", on_right="automatic_selection"
        )
    )
    keybindings: list[KeybindingConfig] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def migrate_bar_scrolling(cls, data: Any):
        if not isinstance(data, dict):
            return data
        values = dict(data)
        if "bar_scrolling" in values:
            legacy_scrolling = values.pop("bar_scrolling")
            if "scrolling_label" not in values:
                values["scrolling_label"] = legacy_scrolling
            logger.warning("[DEPRECATED] MediaV2Config: 'bar_scrolling' renamed to 'scrolling_label'.")
        return values
