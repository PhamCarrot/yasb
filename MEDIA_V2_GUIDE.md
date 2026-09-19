# Media V2

Media V2 is a custom YASB media widget for Windows. Its popup design and motion were inspired by the media widget in [Serpantinum Shell](https://github.com/ilyamiro/serpantinum). The YASB implementation is adapted for PyQt, Windows GSMTC sessions, and YASB configuration and styling conventions.

## Configuration

```yaml
media_v2:
  type: "yasb.media_v2.MediaWidgetV2"
  options:
    layout: standard
    artwork_shape: rounded
    controls_shape: rounded
    hide_empty: false
    compact: false
    scale: 1.0
    bar_height: 30
    border_radius: 8
    use_default_styles: false
    scrolling_label:
      enabled: true
      speed: 20
      delay: 3000
    controls:
      scale: 1.0
    popup:
      blur: true
      alignment: right
      direction: down
      offset_top: 6
      offset_left: 0
      artwork_position: left
      detail_order: [title, artist, output, timeline, controls]
      timestamps: below
      time_display: total
      scroll_title: true
      scroll_artist: true
      scrolling_label:
        speed: 16
        delay: 3000
      progress:
        smoothing_ms: 300
        show_handle: true
      controls:
        scale: 1.0
      disc:
        spin: true
        visualizer: true
        rhythm: true
        glow: true
        rhythm_strength: 1.0
        glow_strength: 1.0
        framerate: 30
      background:
        mode: album_art
        blur_radius: 18
        ambient_motion: true
        ambient_paused_opacity: 0.01
      equalizer:
        preset: Flat
        backend: visual
    callbacks:
      on_left: toggle_media_menu
      on_middle: play_pause
      on_right: automatic_selection
```

The complete validated configuration is in [config-media-v2-test.yaml](config-media-v2-test.yaml). Important choices include:

- `layout`: `standard` or `minimal`.
- `artwork_shape` and `controls_shape`: `square`, `rounded`, or `circle`.
- `scale`: `0.75..2.0`.
- `controls.scale` and `popup.controls.scale`: `0.75..1.5`.
- `offset_top` and `offset_left`: signed popup offsets from `-500..500`.
- `artwork_position`: `left`, `right`, `top`, or `hidden`.
- `detail_order`: any unique ordering of `title`, `artist`, `output`, `timeline`, and `controls`.
- `background.mode`: `color`, `album_art`, or `image`.
- `equalizer.backend`: `visual` or `equalizer_apo`.

The `Via ...` button opens a player menu containing `Automatic` and every available media session. Player selection is independent from the Windows output-device label.

## Callbacks

| Callback | Action |
| --- | --- |
| `toggle_media_menu` | Open or close the popup. |
| `play_pause` | Toggle playback. |
| `previous` | Request the previous track. |
| `next` | Request the next track. |
| `automatic_selection` | Clear a manually selected player. |
| `toggle_compact` | Toggle compact bar geometry. |

## Styling

Common selectors:

```css
.media-v2-widget {}
.media-v2-widget .widget-container {}
.media-v2-widget .media-info {}
.media-v2-widget .media-art {}
.media-v2-widget .media-title {}
.media-v2-widget .media-time {}
.media-v2-widget .media-controls .btn {}

.media-v2-popup {}
.media-v2-popup .media-surface {}
.media-v2-popup .media-title {}
.media-v2-popup .media-artist {}
.media-v2-popup .media-output-label {}
.media-v2-popup .media-source {}
.media-v2-popup .media-progress-track {}
.media-v2-popup .media-progress-fill {}
.media-v2-popup .media-progress-handle {}
.media-v2-popup .media-progress-fill:disabled {}
.media-v2-popup .equalizer-section {}
.media-v2-popup .eq-band {}
.media-player-menu {}
.media-player-menu::item:selected {}
```

Disable the bar information hover without disabling interaction:

```css
.media-v2-widget .btn.media-info:hover {
    background: transparent;
}
```

The progress control uses child frames, not native slider sub-controls. Style `.media-progress-track`, `.media-progress-fill`, and `.media-progress-handle` instead of `::add-page`, `::sub-page`, or `::handle`.

See [styles-media-v2-test.css](styles-media-v2-test.css) for a complete stylesheet.

## Equalizer APO

Real audio equalization is optional. Use `backend: equalizer_apo` with `apo.enabled: true` only after installing and configuring Equalizer APO for the Windows output endpoint. The default `visual` backend changes only the displayed curve.

## Notes

- Media metadata and artwork come from Windows GSMTC. Applications may omit or publish incorrect values.
- The disc visualizer represents shared system-output audio, not only the selected player.
- Native popup blur, mixed-DPI placement, player behavior, and Equalizer APO output require interactive Windows verification.
