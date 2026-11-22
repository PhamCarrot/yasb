from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.validation.widgets.yasb.media_v2 import MediaLyricsConfig, MediaV2Config
from settings import SCRIPT_PATH

"""Built-in Media V2 QSS using normal YASB class hierarchy and Qt states."""

_CHEVRON = (Path(SCRIPT_PATH) / "assets/images/media-player-chevron.svg").as_posix()
_PLAYER_STYLES = f"""
.media-v2-popup .media-source {{ text-align: center; }}
.media-v2-popup .media-player-selector::down-arrow {{
    image: url("{_CHEVRON}"); width: 1em; height: 1em;
}}
"""


def media_section_key(scale: float, radius: int) -> str:
    return f"{scale:g}-{radius}"


def media_section_fallbacks(widgets: Mapping[str, str | dict[str, Any]]) -> str:
    metrics: dict[tuple[float, int], MediaLyricsConfig] = {}
    player_styles = ""
    for widget in widgets.values():
        if not isinstance(widget, dict) or widget.get("type") != "yasb.media_v2.MediaWidgetV2":
            continue
        try:
            config = MediaV2Config.model_validate(widget.get("options", {}))
        except ValidationError:
            continue  # WidgetBuilder owns reporting invalid widgets.
        if not config.use_default_styles:
            player_styles = _PLAYER_STYLES
            if config.popup.show_equalizer:
                metrics.setdefault((config.scale, round(config.border_radius * config.scale)), config.popup.lyrics)
    return player_styles + "".join(
        media_section_styles(
            scale,
            radius,
            scoped=True,
            lyrics=lyrics,
        )
        for (scale, radius), lyrics in sorted(metrics.items())
    )


def media_section_styles(
    scale: float, radius: int, *, scoped: bool = False, lyrics: MediaLyricsConfig | None = None
) -> str:
    """Defaults for the lower popup controls at the application stylesheet level."""
    s: Callable[[float], int] = lambda value: round(value * scale)
    lyrics = lyrics or MediaLyricsConfig()
    inactive = lyrics.inactive_color or "#cdd6f4"
    active = lyrics.active_color or "#cba6f7"
    lyric_font = lyrics.font_family.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    lyric_font_rule = f'font-family: "{lyric_font}";' if lyric_font else ""
    rules = f"""
.media-v2-popup .media-section-page, .media-v2-popup .media-section-viewport,
.media-v2-popup .media-audio, .media-v2-popup .equalizer-body {{ background: transparent; border: none; }}
.media-v2-popup .media-section-tabs {{ background: #313244; border-radius: {radius}px; padding: {s(1)}px; }}
.media-v2-popup .media-section-tabs::tab {{
    color: #a6adc8; background: transparent; border: none; border-radius: 0;
    padding: 0 {s(5)}px; margin: {s(1)}px 0; min-height: {s(24)}px; font-size: {s(11.5)}px;
}}
.media-v2-popup .media-section-tabs::tab:selected {{ background: #cba6f7; color: #1e1e2e; }}
.media-v2-popup .media-section-tabs::tab:first {{ margin-left: {s(1)}px; border-top-left-radius: {radius}px; border-bottom-left-radius: {radius}px; }}
.media-v2-popup .media-section-tabs::tab:last {{ margin-right: {s(1)}px; border-top-right-radius: {radius}px; border-bottom-right-radius: {radius}px; }}
.media-v2-popup .media-section-tabs::tab:focus {{ border: {s(1)}px solid #cdd6f4; }}
.media-v2-popup .media-audio QLabel, .media-v2-popup .media-audio QCheckBox {{ color: #cdd6f4; font-size: {s(12)}px; }}
.media-v2-popup .media-audio .audio-status {{ color: #a6adc8; font-size: {s(11)}px; }}
.media-v2-popup .media-audio .audio-card {{ background: rgba(49,50,68,180); border-radius: {radius}px; }}
.media-v2-popup .media-audio[audioMotion="enhanced"] .audio-card:hover {{ background: rgba(69,71,90,190); }}
.media-v2-popup .media-audio[audioMotion="enhanced"] .audio-card[pressed="true"] {{ background: rgba(88,91,112,200); }}
.media-v2-popup .media-audio .audio-percentage {{ color: #a6adc8; font-size: {s(11.5)}px; font-weight: bold; }}
.media-v2-popup .media-audio .audio-value {{ color: #cba6f7; font-size: {s(11.5)}px; font-weight: bold; }}
.media-v2-popup #media-audio-adaptive {{ color: #cdd6f4; font-size: {s(11.5)}px; selection-background-color: #cba6f7; }}
.media-v2-popup .media-audio QCheckBox {{ selection-background-color: #cba6f7; }}
.media-v2-popup .media-audio .audio-dynamics {{ background: #313244; border: none; border-radius: {radius}px; padding: {s(1)}px; }}
.media-v2-popup .media-audio .audio-dynamics::tab {{ color: #a6adc8; background: transparent; border: none; min-height: {s(26)}px; border-radius: 0; padding: 0 {s(6)}px; font-size: {s(11.5)}px; }}
.media-v2-popup .media-audio .audio-dynamics::tab:first {{ margin-left: {s(1)}px; border-top-left-radius: {radius}px; border-bottom-left-radius: {radius}px; }}
.media-v2-popup .media-audio .audio-dynamics::tab:last {{ margin-right: {s(1)}px; border-top-right-radius: {radius}px; border-bottom-right-radius: {radius}px; }}
.media-v2-popup .media-audio .audio-dynamics::tab:selected {{ color: #1e1e2e; background: #cba6f7; }}
.media-v2-popup .media-audio .audio-dynamics::tab:disabled {{ color: #7f849c; }}
.media-v2-popup .media-audio .audio-dynamics::tab:selected:disabled {{ background: #45475a; color: #a6adc8; }}
.media-v2-popup .media-audio .audio-dynamics::tab:focus {{ border: {s(1)}px solid #cdd6f4; }}
.media-v2-popup .audio-reset {{ color: #cdd6f4; background: #313244; border: none; border-radius: {radius}px; font-size: {s(11.5)}px; }}
.media-v2-popup .audio-reset:hover {{ background: #45475a; }}
.media-v2-popup .audio-reset:disabled {{ color: #7f849c; }}
.media-v2-popup .media-lyrics, .media-v2-popup .media-lyrics-view {{
    background: transparent; color: {inactive}; border: none; selection-background-color: {active};
}}
.media-v2-popup .media-lyrics-view {{ {lyric_font_rule} font-size: {s(lyrics.font_size)}px; font-weight: {lyrics.font_weight}; }}
.media-v2-popup .media-lyrics-view .media-lyrics-scrollbar:vertical {{
    background: transparent; width: {s(6)}px; margin: 0 {s(1)}px 0 0;
    border: none;
}}
.media-v2-popup .media-lyrics-view .media-lyrics-scrollbar::handle:vertical {{
    background: rgba(166,173,200,120); min-height: {s(18)}px; border-radius: {s(3)}px;
}}
.media-v2-popup .media-lyrics-view .media-lyrics-scrollbar::handle:vertical:hover {{ background: #cba6f7; }}
.media-v2-popup .media-lyrics-view .media-lyrics-scrollbar::handle:vertical:pressed {{ background: #b4befe; }}
.media-v2-popup .media-lyrics-view .media-lyrics-scrollbar::add-page:vertical,
.media-v2-popup .media-lyrics-view .media-lyrics-scrollbar::sub-page:vertical {{ background: transparent; }}
.media-v2-popup .media-lyrics-view QScrollBar::add-line:vertical,
.media-v2-popup .media-lyrics-view QScrollBar::sub-line:vertical {{ height: 0; }}
.media-v2-popup .media-lyrics-status {{ color: {inactive}; font-size: {s(12)}px; }}
.media-v2-popup .lyrics-action {{
    color: #cdd6f4; background: #313244; border: none; border-radius: {radius}px; font-size: {s(11.5)}px;
}}
.media-v2-popup .lyrics-action:hover {{ background: #45475a; }}
.media-v2-popup .lyrics-action:disabled {{ color: #7f849c; }}
.media-v2-popup .media-audio QSlider {{ background: transparent; selection-background-color: #cba6f7; }}
.media-v2-popup .media-audio QSlider::groove:horizontal {{ height: {s(14)}px; background: #313244; border-radius: {s(7)}px; }}
.media-v2-popup .media-audio QSlider::handle:horizontal {{ width: {s(22)}px; margin: -{s(4)}px 0; background: #cba6f7; border-radius: {s(11)}px; }}
.media-v2-popup .media-audio QSlider::handle:horizontal:disabled {{ background: #585b70; }}

.media-v2-popup .equalizer-apply {{
    color: #1e1e2e; background: #cba6f7; border: none;
    border-radius: {radius}px; font-size: {s(11.5)}px;
}}
.media-v2-popup .equalizer-apply:hover {{ background: #e9bfff; }}
.media-v2-popup .equalizer-apply:pressed {{ background: #b4befe; }}
.media-v2-popup .equalizer-apply:disabled {{ color: #a6adc8; background: transparent; }}
"""
    if scoped:
        rules = rules.replace(
            ".media-v2-popup ", f'.media-v2-popup[mediaSectionMetrics="{media_section_key(scale, radius)}"] '
        )
    return rules


def media_styles(config: MediaV2Config):
    s: Callable[[float], int] = lambda value: round(value * config.scale)
    radius = s(config.border_radius)
    font = config.font_family.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f"""
{_PLAYER_STYLES}
.media-v2-widget, .media-v2-popup, #media-v2, #media-v2-popup {{
    color: #cdd6f4; background: transparent;
    font-family: "{font}", "Cascadia Mono", "Consolas";
}}
.media-v2-widget .widget-container {{
    background: #1e1e2e; border-radius: {radius}px; margin: 0; padding: 0;
}}
.media-v2-widget #media-v2-bar {{ background: transparent; border: none; }}
.media-v2-widget .media-title, .media-v2-popup .media-title,
#media-v2-title {{ color: #cdd6f4; font-weight: 900; }}
.media-v2-widget .media-time, .media-v2-popup .media-artist,
.media-v2-popup .media-output-label, .media-v2-popup .equalizer-status {{ color: #a6adc8; }}
.media-v2-widget .media-art {{ background: #45475a; color: #cba6f7; }}
.media-v2-popup .media-art {{ background: transparent; color: #cba6f7; }}
.media-v2-popup .media-title {{ font-size: {s(19)}px; font-weight: bold; }}
.media-v2-popup .media-artist {{ font-size: {s(13.5)}px; }}
.media-v2-popup .playback-time {{ font-size: {s(12)}px; }}

.media-v2-widget .btn.media-info {{ background: transparent; border: none; padding: 0; }}
.media-v2-widget .btn.media-info:hover {{ background: rgba(205,214,244,0.12); border-radius: {radius}px; }}
.media-v2-widget .media-controls .btn.transport,
.media-v2-popup .media-controls .btn.transport {{
    background: #313244; color: #9399b2; border: none; padding: 0;
}}
.media-v2-widget .media-controls .btn.transport.square,
.media-v2-popup .media-controls .btn.transport.square {{ border-radius: 0; }}
.media-v2-widget .media-controls .btn.transport.rounded,
.media-v2-popup .media-controls .btn.transport.rounded {{ border-radius: {radius}px; }}
.media-v2-widget .media-controls .btn.transport.circle,
.media-v2-popup .media-controls .btn.transport.circle {{ border-radius: 999px; }}
.media-v2-widget .media-controls .btn.transport:hover,
.media-v2-popup .media-controls .btn.transport:hover {{ background: #45475a; color: #cdd6f4; }}
.media-v2-widget .media-controls .btn.transport:pressed,
.media-v2-popup .media-controls .btn.transport:pressed {{ background: #282939; }}
.media-v2-widget .media-controls .btn.transport:disabled,
.media-v2-popup .media-controls .btn.transport:disabled {{ color: #585b70; background: #262637; }}
.media-v2-widget .media-controls .btn.play {{ color: #cdd6f4; }}
.media-v2-widget .media-controls .btn.play:hover {{ color: #a6e3a1; }}
.media-v2-popup .media-controls .btn.play:hover {{ color: #cba6f7; }}

.media-v2-popup .media-surface, #media-v2-popup #media-surface {{
    background: #1e1e2e; border: none; border-radius: {max(0, radius - s(2))}px;
}}
.media-v2-popup .media-source,
.media-v2-popup .media-player-selector,
.media-v2-popup .media-output-label {{
    background: #313244; color: #a6adc8; border: none; border-radius: {radius}px;
    padding: 0 {s(10)}px; font-size: {s(11.5)}px;
}}
.media-v2-popup .media-source:hover,
.media-v2-popup .media-player-selector:hover {{ background: #45475a; color: #cdd6f4; }}
.media-v2-popup .media-source:pressed {{ background: #585b70; color: #cdd6f4; }}
.media-v2-popup .media-source:disabled,
.media-v2-popup .media-output-label:disabled {{ color: #7f849c; }}
.media-v2-popup .media-source:disabled {{ color: #a6adc8; }}
.media-v2-popup .media-player-selector::drop-down {{
    background: transparent; border: none; width: {s(18)}px;
    border-top-right-radius: {radius}px; border-bottom-right-radius: {radius}px;
}}
.media-player-menu {{
    background: #181825; color: #cdd6f4; border: 1px solid #585b70;
    border-radius: {radius}px; outline: none; padding: {s(4)}px;
}}
.media-player-menu::item {{ min-height: {s(26)}px; padding: 0 {s(8)}px; border-radius: {max(2, radius - s(2))}px; }}
.media-player-menu::item:selected {{ background: #cba6f7; color: #11111b; }}

.media-v2-popup .media-progress {{ background: transparent; border: none; outline: none; padding: 0; }}
.media-v2-popup .media-progress-track {{ background: #313244; border: none; border-radius: {s(3)}px; }}
.media-v2-popup .media-progress-fill {{ background: #89b4fa; border: none; border-radius: {s(3)}px; }}
.media-v2-popup .media-progress-handle {{ background: #cdd6f4; border: none; border-radius: {max(1, s(8))}px; }}
.media-v2-popup .media-progress-fill:disabled,
.media-v2-popup .media-progress-handle:disabled {{ background: #585b70; }}
.media-v2-popup .media-separator {{
    background: rgba(255,255,255,26); min-height: {s(2)}px; max-height: {s(2)}px;
    margin: {s(16)}px 0; border-radius: {s(1)}px;
}}

{media_section_styles(config.scale, radius, lyrics=config.popup.lyrics)}
.media-v2-popup .equalizer-section {{ background: transparent; }}
.media-v2-popup .equalizer-adaptive-overlay {{ color: #cdd6f4; background: transparent; font-size: {s(18)}px; font-weight: bold; }}
.media-v2-popup .equalizer {{ color: #cba6f7; }}
.media-v2-popup .equalizer-title {{ color: #cba6f7; font-size: {s(15)}px; font-weight: bold; }}
.media-v2-popup .equalizer-current {{ color: #cdd6f4; font-size: {s(13)}px; font-weight: bold; padding-left: {s(12)}px; }}
.media-v2-popup .equalizer-status {{ color: #7f849c; font-size: {s(11)}px; }}
.media-v2-popup .presets .btn.preset {{
    color: #7f849c; background: #313244; font-size: {s(11.5)}px;
    border: none; border-radius: {radius}px;
}}
.media-v2-popup .presets .btn.preset:hover {{ background: #45475a; color: #cdd6f4; }}
.media-v2-popup .presets .btn.preset:pressed {{ background: #585b70; color: #cdd6f4; }}
.media-v2-popup .presets .btn.preset:checked {{ background: #cba6f7; color: #1e1e2e; }}
.media-v2-popup .equalizer QLabel {{ color: #7f849c; font-size: {s(9.5)}px; }}
.media-v2-popup .eq-band::groove:vertical {{ width: {s(12)}px; background: #313244; border-radius: {s(6)}px; }}
.media-v2-popup .eq-band::handle:vertical {{
    height: {s(16)}px; margin: 0 -{s(2)}px; background: #cdd6f4; border-radius: {s(8)}px;
}}
.media-v2-popup .eq-band::handle:vertical:hover {{ background: #e9bfff; }}
.media-v2-popup .eq-band::handle:vertical:pressed {{ background: #f5c2e7; }}
.media-v2-popup .eq-band::add-page:vertical {{ background: #cba6f7; border-radius: {s(6)}px; }}

.tooltip, .tooltip.dark {{
    background: #181825; color: #cdd6f4; border: 1px solid #585b70;
    border-radius: {radius}px; padding: {s(5)}px {s(8)}px;
}}
"""
