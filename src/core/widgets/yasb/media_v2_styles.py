"""Built-in Media V2 QSS using normal YASB class hierarchy and Qt states."""


def media_styles(config):
    s = lambda value: round(value * config.scale)
    radius = s(config.border_radius)
    font = config.font_family.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f"""
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
.media-v2-popup .media-progress-handle {{ background: #cdd6f4; border: none; border-radius: 999px; }}
.media-v2-popup .media-progress-fill:disabled,
.media-v2-popup .media-progress-handle:disabled {{ background: #585b70; }}
.media-v2-popup .media-separator {{
    background: rgba(255,255,255,26); min-height: {s(2)}px; max-height: {s(2)}px;
    margin: {s(16)}px 0; border-radius: {s(1)}px;
}}

.media-v2-popup .equalizer-section {{ background: transparent; }}
.media-v2-popup .equalizer {{ color: #cba6f7; }}
.media-v2-popup .equalizer-title {{ color: #cba6f7; font-size: {s(15)}px; font-weight: bold; }}
.media-v2-popup .equalizer-current {{ color: #cdd6f4; font-weight: bold; }}
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
