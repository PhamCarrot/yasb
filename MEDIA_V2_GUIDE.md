# Media V2 Widget Options

A media player widget with a detailed popup. The bar shows the artwork, a scrolling title, the playback time and transport buttons. The popup adds seeking, player selection, an animated disc with an audio visualizer, lyrics and an optional 10-band equalizer.

The popup design and motion are inspired by the media widget in [Serpantinum Shell](https://github.com/ilyamiro/serpantinum).

> [!NOTE]
> Media V2 shows what the player reports through the Windows media API (GSMTC). Apps that do not create a media session do not appear, and the title, artist, artwork, duration and position can each be missing. Buttons and seeking are disabled when the player does not report support for them, and unknown times are shown as `--:--`. If the source app doesn't expose a usable timeline, there isn't much YASB can do about it.

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `class_name` | string | `""` | Additional CSS class names for the widget. |
| `hide_empty` | boolean | `false` | Hide the widget when there is no media session. |
| `compact` | boolean | `false` | Start in compact mode, with tighter spacing and slightly smaller artwork. Adds the `compact` class to the widget. |
| `layout` | string | `"standard"` | Bar layout: `"standard"` or `"minimal"`. `minimal` removes the title and time. |
| `artwork_shape` | string | `"rounded"` | Bar artwork shape: `"square"`, `"rounded"` or `"circle"`. |
| `controls_shape` | string | `"rounded"` | Transport button shape in the bar and the popup: `"square"`, `"rounded"` or `"circle"`. |
| `scale` | float | `1.0` | Size multiplier for the widget and the popup (0.75–2.0). |
| `artwork_size` | integer | `28` | Bar artwork size in pixels, before `scale` (16–64). |
| `border_radius` | integer | `8` | Base corner radius used by the default styles (0–32). |
| `font_family` | string | `"Adwaita Mono"` | Font used by the default styles. |
| `use_default_styles` | boolean | `true` | Apply the built-in styles. Set to `false` to style the widget entirely from `styles.css`. |
| `scrolling_label` | dict | [See below](#scrolling-label-options) | Bar title scrolling options. |
| `controls` | dict | [See below](#controls-options) | Bar transport button options. |
| `popup` | dict | [See below](#popup-options) | Popup options. |
| `callbacks` | dict | [See below](#available-callbacks) | Mouse callbacks: `on_left`, `on_middle`, `on_right`. |
| `keybindings` | list | `[]` | Optional hotkeys. See [Keybindings](docs/Keybindings.md). |

## Example Configuration

Every option is optional. The example below sets the options that are changed most often.

```yaml
media_v2:
  type: "yasb.media_v2.MediaWidgetV2"
  options:
    hide_empty: false
    layout: "standard"
    artwork_shape: "rounded"
    controls_shape: "rounded"
    scale: 1.0
    artwork_size: 28
    scrolling_label:
      enabled: true
      speed: 40.0
      delay: 3000
    controls:
      size: 30
    popup:
      blur: true
      round_corners: true
      round_corners_type: "normal"
      border_color: "System"
      alignment: "right"
      direction: "down"
      offset_top: 6
      offset_left: 0
      artwork_position: "left"
      detail_order: ["title", "artist", "output", "timeline", "controls"]
      timestamps: "below"
      time_display: "total"
      show_equalizer: true
      equalizer_position: "bottom"
      disc:
        spin: true
        visualizer: true
      equalizer:
        preset: "Flat"
        preset_effect: "lightning"
        backend: "visual"
      background:
        mode: "album_art"
        blur_radius: 18
    callbacks:
      on_left: "toggle_media_menu"
      on_middle: "play_pause"
      on_right: "automatic_selection"
    keybindings:
      - keys: "win+shift+m"
        action: "toggle_media_menu"
```

## Scrolling Label Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | `true` | Scroll long titles in the bar. When disabled the title is truncated. |
| `speed` | float | `40.0` | Scrolling speed (5–200). |
| `delay` | integer | `3000` | Delay before scrolling starts, in ms (0–10000). |

## Controls Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `size` | integer | `30` | Transport button size in pixels (20–96). The icon scales with the button. |

## Popup Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `blur` | boolean | `true` | Apply a blur effect to the popup window. |
| `round_corners` | boolean | `true` | Round the corners of the popup window. |
| `round_corners_type` | string | `"normal"` | Corner style: `"normal"` or `"small"`. |
| `border_color` | string | `"System"` | Border color of the popup window. |
| `alignment` | string | `"right"` | Popup alignment relative to the widget: `"left"`, `"center"` or `"right"`. |
| `direction` | string | `"down"` | Direction the popup opens: `"up"` or `"down"`. |
| `offset_top` | integer | `6` | Vertical offset of the popup (-500–500). |
| `offset_left` | integer | `0` | Horizontal offset of the popup (-500–500). |
| `artwork_position` | string | `"left"` | Position of the artwork disc: `"left"`, `"right"`, `"top"` or `"hidden"`. |
| `detail_order` | list | `["title", "artist", "output", "timeline", "controls"]` | Rows shown next to the artwork, in order. Leave a row out to hide it. No duplicates. |
| `scroll_title` | boolean | `true` | Scroll long titles. |
| `scroll_artist` | boolean | `false` | Scroll long artist names. |
| `scrolling_label` | dict | `{speed: 40.0, delay: 3000}` | Scrolling speed (5–200) and delay in ms (0–10000) for the popup title and artist. |
| `timestamps` | string | `"below"` | Position of the time labels: `"above"`, `"below"`, `"inline"` or `"hidden"`. |
| `time_display` | string | `"total"` | Right-hand time label: `"total"` or `"remaining"`. |
| `progress` | dict | `{smoothing_ms: 250, show_handle: true}` | Seek bar options. `smoothing_ms` smooths progress movement (0–2000), `show_handle` shows the seek handle. |
| `controls` | dict | `{size: 43}` | Play button size in pixels (20–96). Previous and next scale with it. |
| `show_equalizer` | boolean | `true` | Show the lower section with the Equalizer, Audio and Lyrics tabs. |
| `equalizer_position` | string | `"bottom"` | Position of the lower section: `"top"` or `"bottom"`. |
| `show_separator` | boolean | `true` | Show a separator between the media details and the lower section. |
| `lyrics` | dict | [See below](#lyrics-options) | Lyrics tab options. |
| `disc` | dict | [See below](#disc-options) | Artwork disc options. |
| `equalizer` | dict | [See below](#equalizer-options) | Equalizer options. |
| `audio` | dict | [See below](#audio-options) | Audio tab options. |
| `background` | dict | [See below](#background-options) | Popup background options. |
| `border` | dict | [See below](#border-options) | Animated border options. |

## Lyrics Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `alignment` | string | `"left"` | Line alignment: `"left"`, `"center"` or `"right"`. |
| `center_position` | float | `0.44` | Vertical position of the active line while following playback (0.0–1.0). |
| `lines_before` | integer | `-1` | Lines shown before the active line (-1–100). `-1` shows all. |
| `lines_after` | integer | `-1` | Lines shown after the active line (-1–100). `-1` shows all. |
| `inactive_opacity` | float | `-1.0` | Opacity of inactive lines (0.0–1.0). `-1` fades lines by distance from the active line. |
| `font_family` | string | `""` | Lyrics font. Empty uses the popup font. |
| `font_size` | integer | `18` | Font size in pixels (8–72). |
| `font_weight` | integer | `700` | Font weight, 100 to 900 in steps of 100. |
| `margins` | dict | `{horizontal: 4, vertical: 0, placeholder: 8}` | Margins in pixels (0–64) for lyric lines and for the empty or status message. |
| `line_height` | integer | `30` | Minimum line height in pixels (0–200). |
| `line_spacing` | integer | `6` | Spacing between lines in pixels (0–100). |
| `animation_duration_ms` | integer | `320` | Line and scroll animation duration in ms (0–5000). |
| `browse_return_ms` | integer | `4000` | Time before a browsed list returns to the playing line, in ms (0–60000). |
| `drag_threshold` | integer | `4` | Pointer movement in pixels that starts a drag (1–64). |
| `style` | dict | [See below](#lyrics-style-options) | Separate styles for the lines before the current line, the current line and the lines after it. Colors are set in `styles.css`, see [Lyrics Colors](#lyrics-colors). |
| `glow` | dict | [See below](#lyrics-glow-options) | A soft halo behind the current line. |
| `word_highlight` | string | `"step"` | `"step"` colors whole words as they are sung. `"sweep"` fills each word smoothly from left to right. |
| `sweep_softness` | float | `0.5` | Width of the soft edge of the sweep, in em (0–3). `0` is a hard edge. |
| `sweep_fps` | integer | `30` | Frame rate of the sweep (10–60). Lower values use less CPU. |
| `unsung_opacity` | float | `0.4` | Opacity of the words of the current line that are not sung yet (0.0–1.0). |
| `line_sweep` | boolean | `false` | Also sweep lines that have no word timing, from the start of the line to its end. |
| `line_sweep_max_ms` | integer | `6000` | Longest duration of a line sweep in ms (500–30000), so long instrumental gaps do not crawl. |
| `auto_lookup` | boolean | `true` | Look up lyrics when the Lyrics tab is opened. |
| `provider_order` | list | `["lrclib", "netease", "better_lyrics"]` | Providers to try, in order: `"lrclib"`, `"netease"`, `"better_lyrics"`, `"musixmatch"`. No duplicates. |
| `better_lyrics_enabled` | boolean | `true` | Allow lookups through Better Lyrics. |
| `musixmatch_enabled` | boolean | `false` | Allow lookups through Musixmatch. Requires `musixmatch_api_key`. |
| `musixmatch_api_key` | string | `""` | API key for the Musixmatch API. |
| `request_spacing_ms` | integer | `250` | Minimum time between provider requests in ms (200–5000). |
| `request_timeout_ms` | integer | `10000` | Timeout for a provider request in ms (1000–60000). |
| `prefer_word_timed` | boolean | `true` | When a provider returns lyrics without word timing, show them and keep asking the remaining providers for word-timed lyrics. |

Lyrics are only looked up while the popup is open on the Lyrics tab, and only when the track has an artist. A disabled provider, or Musixmatch without a key, is skipped.

With `prefer_word_timed: true`, line-timed or plain lyrics appear as soon as they are found. Media V2 then continues down `provider_order`, one request at a time, and replaces them in place only with word-timed lyrics. This can add one request per remaining provider for a track (two for NetEase, which uses an undocumented interface). Set it to `false` to stop at the first provider that has lyrics.

Timed lyrics follow playback and highlight the current line. Scrolling, dragging or using the arrow keys pauses following for `browse_return_ms`, and a right click resumes it. Clicking a timed line, or selecting it and pressing Enter, seeks to it when the player allows seeking.

### Lyrics Style Options

`before`, `current` and `after` take the same options. Every option left at its default keeps the built-in look.

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `bold` | boolean | `null` | `true` draws at least weight 700, `false` at most 400. `null` uses `font_weight`. |
| `italic` | boolean | `false` | Italic text. |
| `underline` | boolean | `false` | Underlined text. |
| `strikethrough` | boolean | `false` | Struck-through text. |
| `opacity` | float | `null` | Opacity for this whole side (0.0–1.0). `null` fades lines by distance from the current line. |
| `scale` | float | `null` | Size for this whole side (0.5–1.5). `null` uses the built-in sizes. |

`style` also has `background_radius` (`6`, 0–32) and `background_padding` (`4`, 0–16), in pixels. They shape the fill set with `-qproperty-beforeBackground`, `-qproperty-currentBackground` or `-qproperty-afterBackground`. Rows keep the same height when a line becomes current, so a bold or larger current line never moves the list.

### Lyrics Glow Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | `false` | Show the glow. |
| `radius` | integer | `8` | Blur radius in pixels (0–32). |
| `strength` | float | `0.6` | Opacity multiplier (0–2). |
| `target` | string | `"line"` | `"line"` lights the whole current line. `"sung"` lights only the part already sung, and needs a sweep. |

The glow uses the color of the current line, or `-qproperty-glowColor` when it is set.

Styles and the glow are computed once per line and add no work per frame. Only the sweep repaints every frame, and only the current line, while the Lyrics tab is open and media is playing. `sweep_fps` limits that cost.

### Lyrics Colors

Like the rest of the widget, lyric colors are set in `styles.css`, on `.media-v2-popup .media-lyrics-view`. The lyrics are painted by the widget, so the per-side colors use `-qproperty-` values, the same convention as the [adaptive bar style](docs/Styling.md#adaptive-bar-style).

| Property | Default | Description |
| --- | --- | --- |
| `color` | `#cdd6f4` | Color of lines that are not current. |
| `selection-background-color` | `#cba6f7` | Color of the current line and of sung words. |
| `-qproperty-beforeColor` | `color` | Lines before the current line. |
| `-qproperty-currentColor` | `selection-background-color` | The current line. |
| `-qproperty-afterColor` | `color` | Lines after the current line. |
| `-qproperty-beforeBackground` | none | A rounded fill behind lines before the current line. |
| `-qproperty-currentBackground` | none | A rounded fill behind the current line. |
| `-qproperty-afterBackground` | none | A rounded fill behind lines after the current line. |
| `-qproperty-glowColor` | current line color | Color of the [glow](#lyrics-glow-options). |

Colors with alpha use the CSS `#RRGGBBAA` order in `styles.css`, for example `#cba6f733`, or `rgba()`. Qt reads a `qproperty` once, when the widget is polished. Changing a value works on save, but deleting a line keeps the old value until YASB restarts.

Example of a styled Lyrics tab:

```yaml
lyrics:
  alignment: center
  font_weight: 600
  style:
    before:  { italic: true, bold: false, opacity: 0.55 }
    current: { bold: true }
    after:   { bold: false, opacity: 0.4 }
    background_radius: 8
  glow: { enabled: true, radius: 10, strength: 0.7, target: sung }
  word_highlight: sweep
  line_sweep: true
```

```css
.media-v2-popup .media-lyrics-view {
    color: #a6adc8;
    selection-background-color: #cba6f7;
    -qproperty-beforeColor: #6c7086;
    -qproperty-currentBackground: #cba6f733;
}
```

## Disc Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `spin` | boolean | `true` | Rotate the artwork while playing. |
| `visualizer` | boolean | `true` | Show the radial audio spectrum around the disc. |
| `rhythm` | boolean | `true` | Move the disc with the bass. |
| `glow` | boolean | `true` | Show a glow that reacts to the audio. |
| `rhythm_strength` | float | `1.0` | Strength of the rhythm movement (0–3). |
| `glow_strength` | float | `1.0` | Strength of the glow (0–3). |
| `framerate` | integer | `60` | Disc update rate in frames per second (15–60). |

The visualizer, rhythm and glow use the same audio capture as the [Audio Visualizer](docs/widgets/%28Widget%29-Audio-Visualizer.md) widget, and only run while the popup is open and media is playing.

## Equalizer Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `preset` | string | `"Flat"` | Initial preset: `"Flat"`, `"Bass"`, `"Treble"`, `"Vocal"`, `"Pop"`, `"Rock"`, `"Jazz"`, `"Classic"` or `"Custom"`. |
| `custom_bands` | list | `[0, 0, 0, 0, 0, 0, 0, 0, 0, 0]` | Gain in dB (-12–12) for the `Custom` preset. Exactly 10 values, for 31 Hz, 63 Hz, 125 Hz, 250 Hz, 500 Hz, 1 kHz, 2 kHz, 4 kHz, 8 kHz and 16 kHz. |
| `preset_effect` | string | `"lightning"` | Animation played when a preset is selected: `"lightning"`, `"ripple"`, `"center_pulse"`, `"curve"`, `"glow"`, `"scan"`, `"random"` or `"none"`. `"random"` picks one of the others for each switch. |
| `effect_speed` | float | `1.0` | Duration multiplier for the preset animation and the handle movement (0.4–3.0). Lower is faster. |
| `preset_motion` | dict | [See below](#preset-motion-options) | How the band handles move to a new preset. |
| `backend` | string | `"visual"` | `"visual"` only moves the sliders. `"equalizer_apo"` changes the sound through Equalizer APO. |
| `apo` | dict | [See below](#equalizer-apo-options) | Equalizer APO options. |

Preset buttons apply immediately. Dragging a band switches to `Custom` and shows an **Apply** button. The change is saved when you click it, and discarded if you close the popup or leave the Equalizer tab.

### Preset Motion Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `style` | string | `"together"` | `"together"`, `"cascade"` (left to right), `"center_out"`, `"edges_in"`, `"wave"` (cascade with a small overshoot) or `"spring"` (together with an overshoot). |
| `duration_ms` | integer | `350` | Travel time of each band in ms (80–2000). |
| `stagger_ms` | integer | `0` | Delay between neighbouring bands in ms (0–200). `duration_ms` plus nine times `stagger_ms` must not exceed 3000. |
| `easing` | string | `"out_quart"` | Travel curve: `"out_quart"`, `"out_cubic"`, `"out_back"` or `"in_out_sine"`. `wave` and `spring` use their own curve. |

The motion is only presentation. The selected curve is applied immediately, and selecting another preset during the movement continues from where the handles are.

## Equalizer APO Options

Changing the sound requires [Equalizer APO](https://sourceforge.net/projects/equalizerapo/) installed for your playback device, `backend: "equalizer_apo"` and `apo.enabled: true`.

```yaml
equalizer:
  backend: "equalizer_apo"
  apo:
    enabled: true
    manage_include: true
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | `false` | Allow Media V2 to write its Equalizer APO configuration. |
| `target_device` | string | `"default"` | Device to equalize. Only `"default"`, the Windows default playback device, is supported. |
| `processor` | string | `"graphic_eq"` | `"graphic_eq"` writes a 10-band GraphicEQ. `"native"` uses the optional [native audio processor](https://github.com/PhamCarrot/yasb/blob/main/docs/MEDIA_V2_NATIVE_AUDIO.md). |
| `native_library` | string | `""` | Absolute path to the native processor DLL. Used when `processor` is `"native"`. |
| `native_sha256` | string | `""` | SHA-256 of the DLL, as 64 lowercase hex characters. The DLL is rejected if the hash does not match. |
| `auto_preamp` | boolean | `true` | Lower the preamp by the largest positive band gain to avoid clipping. |
| `preamp_db` | float | `0.0` | Preamp in dB when `auto_preamp` is off (-24–12). |
| `manage_include` | boolean | `false` | Let Media V2 add its `Include` line to Equalizer APO's `config.txt`. |

Media V2 writes its curve to `yasb-media-v2-eq.txt` in the Equalizer APO config folder. With `manage_include: true` it adds the block below to `config.txt`. With `manage_include: false` you have to add the block yourself.

```text
# BEGIN YASB MEDIA V2 EQ
Include: yasb-media-v2-eq.txt
# END YASB MEDIA V2 EQ
```

> [!NOTE]
> **Saved** means the file was written, not that Equalizer APO is active on the device. If a preset sounds unchanged, open the Equalizer APO Device Selector, select the playback device shown in the popup and restart when asked. Other Equalizer APO filters, including Peace, stay active and stack with the Media V2 curve.

The Audio tab (balance, mono, channel swap and dynamic range) and the **Dynamic** equalizer only work with `processor: "native"`. See [Media V2 Native Audio Processor](https://github.com/PhamCarrot/yasb/blob/main/docs/MEDIA_V2_NATIVE_AUDIO.md).

## Audio Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `motion` | string | `"reference"` | `"enhanced"` animates balance changes from Reset or another popup, fades changed texts, stretches the switch knob while it moves and adds hover and press feedback to the cards. |
| `meters` | boolean | `false` | Show live left and right levels on the balance scale while the Audio tab is open and media is playing. |

The meters use the same audio capture as the disc and show the playing audio with balance, mono and swap applied by the popup.

## Background Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `mode` | string | `"album_art"` | Background source: `"album_art"`, `"image"` or `"color"`. |
| `color` | string | `null` | Fill color for `color` mode, for example `"#181825ee"`. |
| `image` | string | `""` | Image path for `image` mode. Required in that mode. `~` and environment variables are expanded. |
| `blur_radius` | integer | `18` | Blur applied to the artwork or image (0–64). Not the same as `popup.blur`, which blurs what is behind the window. |
| `ambient_motion` | boolean | `true` | Slowly move the background. |
| `ambient_paused_opacity` | float | `0.01` | Opacity of the ambient effect while paused (0–0.08). |

## Border Options

The popup has an animated border that takes its colors from the artwork. It is separate from `popup.border_color`, which is the window border.

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `framerate` | integer | `60` | Border update rate in frames per second (15–120). |
| `charge_duration` | float | `1.2` | Duration of the reveal animation in seconds (0.2–5.0). |
| `rotation_duration` | float | `5.0` | Duration of one rotation of the gradient in seconds (1–30). |

## Available Callbacks

```yaml
callbacks:
  on_left: "toggle_media_menu"
  on_middle: "play_pause"
  on_right: "automatic_selection"
```

Available actions:

- `toggle_media_menu`: Opens or closes the popup.
- `play_pause`: Toggles between play and pause.
- `previous`: Skips to the previous track.
- `next`: Skips to the next track.
- `automatic_selection`: Removes a pinned player and returns to automatic player selection.
- `toggle_compact`: Toggles compact mode.
- `do_nothing`: A placeholder callback that does nothing when triggered.
- `exec <command>`: Runs a command.

The same actions can be used in `keybindings`.

## Player Selection

With one player, the popup shows its name as `Via <app>`. With two or more it becomes a menu where you can pin a player. Without a pin, Media V2 picks the player that is playing, then the one it used last, then any player that can be controlled.

## Labels

Media V2 has no `label` or `label_alt` option, and placeholders such as `{title}` and `{artist}` are not supported. The text is built by the widget: the title and `current / duration` in the bar, and the title, `By <artist>`, the output device and `Via <app>` in the popup.

## Available Styles

```css
.media-v2-widget {}
.media-v2-widget.compact {}
.media-v2-widget .widget-container {}
.media-v2-widget .media-v2-bar {}
.media-v2-widget .btn.media-info {}
.media-v2-widget .media-art {}
.media-v2-widget .media-title {}
.media-v2-widget .media-time {}
.media-v2-widget .media-controls {}
.media-v2-widget .btn.transport {}
.media-v2-widget .btn.transport.previous {}
.media-v2-widget .btn.transport.play {}
.media-v2-widget .btn.transport.pause {}
.media-v2-widget .btn.transport.next {}
.media-v2-widget .btn.transport:disabled {}

.media-v2-popup {}
.media-v2-popup .media-surface {}
.media-v2-popup .media-art {}
.media-v2-popup .media-title {}
.media-v2-popup .media-artist {}
.media-v2-popup .media-output {}
.media-v2-popup .media-output-label {}
.media-v2-popup .media-source {}
.media-v2-popup .media-player-selector {}
.media-v2-popup .media-timeline {}
.media-v2-popup .media-progress {}
.media-v2-popup .media-progress-track {}
.media-v2-popup .media-progress-fill {}
.media-v2-popup .media-progress-handle {}
.media-v2-popup .playback-time {}
.media-v2-popup .playback-time.elapsed {}
.media-v2-popup .playback-time.duration {}
.media-v2-popup .media-controls {}
.media-v2-popup .btn.transport {}
.media-v2-popup .media-separator {}
.media-v2-popup .media-section-tabs {}
.media-v2-popup .media-section-viewport {}

.media-v2-popup .equalizer-section {}
.media-v2-popup .equalizer {}
.media-v2-popup .equalizer-title {}
.media-v2-popup .equalizer-current {}
.media-v2-popup .equalizer-status {}
.media-v2-popup .presets {}
.media-v2-popup .btn.preset {}
.media-v2-popup .btn.preset:checked {}
.media-v2-popup .eq-band {}
.media-v2-popup .eq-band::groove:vertical {}
.media-v2-popup .eq-band::handle:vertical {}
.media-v2-popup .eq-band::add-page:vertical {}

.media-v2-popup .media-audio {}
.media-v2-popup .media-audio .audio-card {}
.media-v2-popup .audio-balance {}
.media-v2-popup .audio-dynamics {}
.media-v2-popup .audio-status {}
.media-v2-popup .audio-reset {}

.media-v2-popup .media-lyrics {}
.media-v2-popup .media-lyrics-view {}
.media-v2-popup .media-lyrics-scrollbar {}
.media-v2-popup .media-lyrics-status {}
.media-v2-popup .lyrics-action {}

.media-player-menu {}
.media-player-menu::item {}
.media-player-menu::item:selected {}
.media-player-menu::item:checked {}
```

- The popup gets its playback state as a class: `.media-v2-popup.playing`, `.paused`, `.stopped`, `.changing`, `.opened`, `.closed`, `.unknown` or `.empty`.
- `.media-source` and `.media-player-selector` get `.automatic` or `.pinned`.
- Transport buttons get their shape as a class: `.square`, `.rounded` or `.circle`.
- A single preset or band can be styled with `.preset.flat`, `.preset.bass` and so on, and `.eq-band.band-31` to `.eq-band.band-16k`.
- `:hover`, `:pressed` and `:disabled` work on buttons and other controls.
- The off color of the Audio switches can be set with `qproperty-offColor`, for example `.media-v2-popup .media-audio QCheckBox { qproperty-offColor: #313244; }`. The Dynamic switch in the header is `#media-audio-adaptive`.
- With `audio.motion: "enhanced"`, the cards can be styled with `.media-v2-popup .media-audio[audioMotion="enhanced"] .audio-card:hover` and `.audio-card[pressed="true"]`.

> [!NOTE]
> The disc, the animated border, the artwork background and the preset effects are painted by the widget. They are controlled by the `disc`, `border`, `background` and `equalizer` options, not by CSS. The bar has no height option, use vertical padding on `.media-v2-bar` instead.

## Example Style

The examples below are written for `use_default_styles: false`. Sizes in `styles.css` are not multiplied by `scale`.

```css
.media-v2-widget .widget-container {
    background: #17191f;
    border: 1px solid #2b303b;
    border-radius: 8px;
}
.media-v2-widget .media-v2-bar {
    padding: 4px 0;
}
.media-v2-widget .media-title {
    color: #f3f4f6;
    font-weight: 700;
}
.media-v2-widget .media-time {
    color: #9299a8;
    font-size: 10px;
}
.media-v2-widget .btn.media-info {
    background: transparent;
    border: none;
}
.media-v2-widget .btn.transport {
    background: #242832;
    color: #aeb6c7;
    border: none;
    border-radius: 8px;
}
.media-v2-widget .btn.transport:hover {
    background: #313744;
    color: #ffffff;
}
.media-v2-widget .btn.transport:disabled {
    background: #20232b;
    color: #555d6d;
}
```

## Example Popup Style

```css
.media-v2-popup {
    color: #e5e7eb;
    font-family: "Adwaita Mono", "Cascadia Mono", "Consolas";
}
.media-v2-popup .media-surface {
    background: #17191f;
    border-radius: 6px;
}
.media-v2-popup .media-title {
    color: #f8fafc;
    font-weight: 700;
}
.media-v2-popup .media-artist {
    color: #9ca3af;
}
.media-v2-popup .media-output-label,
.media-v2-popup .media-source,
.media-v2-popup .media-player-selector {
    color: #aeb6c7;
    background: #242832;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0 10px;
}
.media-v2-popup .media-player-selector.pinned {
    border-color: #9aa9ff;
}
.media-player-menu {
    color: #e5e7eb;
    background: #111318;
    border: 1px solid #343a47;
    border-radius: 8px;
    padding: 4px;
}
.media-player-menu::item:selected {
    background: #343b4a;
}
.media-v2-popup .btn.transport {
    color: #aeb6c7;
    background: #242832;
    border: none;
    border-radius: 8px;
}
.media-v2-popup .btn.transport:hover {
    color: #ffffff;
    background: #313744;
}
.media-v2-popup .btn.transport:disabled {
    color: #555d6d;
    background: #20232b;
}
.media-v2-popup .media-progress-track {
    background: #303541;
    border-radius: 3px;
}
.media-v2-popup .media-progress-fill {
    background: #8cabff;
    border-radius: 3px;
}
.media-v2-popup .media-progress-handle {
    background: #f1f5f9;
    border-radius: 999px;
}
.media-v2-popup .playback-time {
    color: #87909f;
    font-size: 10px;
}
.media-v2-popup .media-separator {
    background: rgba(255, 255, 255, 0.09);
    min-height: 2px;
    max-height: 2px;
    margin: 16px 0;
}
.media-v2-popup .equalizer-title {
    color: #c5b7ff;
    font-size: 15px;
    font-weight: 700;
}
.media-v2-popup .btn.preset {
    color: #9ca3af;
    background: #242832;
    border: 1px solid transparent;
    border-radius: 8px;
}
.media-v2-popup .btn.preset:hover {
    color: #ffffff;
    background: #313744;
}
.media-v2-popup .btn.preset:checked {
    color: #12141a;
    background: #ad9cff;
}
.media-v2-popup .eq-band::groove:vertical {
    width: 12px;
    background: #303541;
    border-radius: 6px;
}
.media-v2-popup .eq-band::handle:vertical {
    height: 16px;
    margin: 0 -2px;
    background: #e7eaf0;
    border-radius: 8px;
}
.media-v2-popup .eq-band::add-page:vertical {
    background: #9f8cff;
    border-radius: 6px;
}
```

## Deprecated Options

Older option names are still accepted and converted when the config is loaded. New configurations should use the current names. The lyric color options are not converted: they are ignored with a warning, and `yasbc migrate-config` removes them. Set the colors in `styles.css` instead.

| Old option | Current option |
| --- | --- |
| `bar_scrolling` | `scrolling_label` |
| `popup.scrolling` | `popup.scrolling_label` |
| `popup.widget_offset` | `popup.offset_top` |
| `popup.bar_offset` | `popup.offset_top` |
| `popup.edge_offset` | `popup.offset_left` |
| `popup.placement` | Removed. The popup is always placed relative to the widget. |
| `popup.direction: "auto"` | `popup.direction: "down"` |
| `popup.background.native_blur` | `popup.blur` |
| `popup.background.mode: "qss"` | `popup.background.mode: "color"` |
| `popup.equalizer.preset_effect: "blur_slide"` | `"none"` |
| `popup.equalizer.apo.write_debounce_ms` | Ignored. Manual band changes are saved with Apply. |
| `popup.lyrics.active_color` | `selection-background-color` on `.media-lyrics-view` in `styles.css` |
| `popup.lyrics.inactive_color` | `color` on `.media-lyrics-view` in `styles.css` |
| `popup.lyrics.style.<side>.color` | `-qproperty-beforeColor`, `-qproperty-currentColor` or `-qproperty-afterColor` in `styles.css` |
| `popup.lyrics.style.<side>.background` | `-qproperty-beforeBackground`, `-qproperty-currentBackground` or `-qproperty-afterBackground` in `styles.css` |
| `popup.lyrics.glow.color` | `-qproperty-glowColor` in `styles.css` |
