# Media V2 Widget Options

Media V2 is an independent Windows media widget for YASB using:

```yaml
type: "yasb.media_v2.MediaWidgetV2"
```

It provides a compact bar player and a larger media popup with album artwork, playback controls, seeking, player/session selection, an animated disc/visualizer, configurable background effects, an animated artwork-colored border, and an optional 10-band equalizer.

The popup design and motion were inspired by the media widget in [Serpantinum Shell](https://github.com/ilyamiro/serpantinum), then adapted for PyQt, Windows media sessions, and YASB's configuration and styling conventions.

## Windows GSMTC limitations

Media V2 gets media sessions, metadata, playback state, timeline information, and playback capabilities from Windows Global System Media Transport Controls (GSMTC).

This means Media V2 can only display or control information that the application exposes to Windows.

Important limitations:

- Applications that do not create a GSMTC media session will not appear.
- Title, artist, album, artwork, duration, playback position, and control capabilities can be missing independently.
- Previous, play/pause, and next are automatically disabled when the active player does not advertise the corresponding GSMTC capability.
- Seeking requires both:
  - a valid timeline/duration; and
  - the player's `can_seek` capability.
- Some browsers, web players, games, and older desktop applications expose incomplete or inaccurate timeline information.
- A player can accept a Windows media command without immediately changing playback state.
- Multiple simultaneous sessions from the same application are treated as separate sessions.
- Automatic player selection prefers:
  1. a manually pinned session;
  2. a currently playing session;
  3. the previous automatic session;
  4. a controllable session;
  5. the first available session.
- Media artwork supplied by Windows is limited to 16 MiB by the backend.
- Unknown or invalid time values are displayed as `--:--`.

The popup receives additional audio-output information from Windows separately from GSMTC. The active audio output therefore does not necessarily correspond to a particular media application's own routing.

---

# Complete configuration

The following configuration includes every current Media V2 option.

```yaml
media_v2:
  type: "yasb.media_v2.MediaWidgetV2"
  options:
    class_name: ""
    hide_empty: false
    compact: false
    layout: "standard"

    artwork_shape: "rounded"
    controls_shape: "rounded"

    scale: 1.0
    artwork_size: 28
    border_radius: 8

    font_family: "Adwaita Mono"
    use_default_styles: true

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

      show_equalizer: true

      scroll_title: true
      scroll_artist: false

      scrolling_label:
        speed: 40.0
        delay: 3000

      progress:
        smoothing_ms: 250
        show_handle: true

      controls:
        size: 43

      artwork_position: "left"

      detail_order:
        - "title"
        - "artist"
        - "output"
        - "timeline"
        - "controls"

      timestamps: "below"
      time_display: "total"

      equalizer_position: "bottom"
      show_separator: true

      lyrics:
        alignment: "left"
        center_position: 0.44
        lines_before: -1
        lines_after: -1
        inactive_opacity: -1.0
        active_color: null
        inactive_color: null
        font_family: ""
        font_size: 18
        font_weight: 700
        margins:
          horizontal: 4
          vertical: 0
          placeholder: 8
        line_height: 30
        line_spacing: 6
        animation_duration_ms: 320
        browse_return_ms: 4000
        drag_threshold: 4
        auto_lookup: true
        provider_order: ["lrclib", "netease", "better_lyrics"]
        better_lyrics_enabled: true
        musixmatch_enabled: false
        musixmatch_api_key: ""
        request_spacing_ms: 250
        request_timeout_ms: 10000

      disc:
        spin: true
        visualizer: true
        rhythm: true
        glow: true
        rhythm_strength: 1.0
        glow_strength: 1.0
        framerate: 60

      equalizer:
        preset: "Flat"

        custom_bands:
          - 0
          - 0
          - 0
          - 0
          - 0
          - 0
          - 0
          - 0
          - 0
          - 0

        preset_effect: "lightning"
        effect_speed: 1.0

        backend: "visual"

        apo:
          enabled: false
          target_device: "default"
          processor: "graphic_eq"
          native_library: ""
          native_sha256: ""
          auto_preamp: true
          preamp_db: 0.0
          write_debounce_ms: 100
          manage_include: false

      background:
        mode: "album_art"
        color: null
        image: ""
        blur_radius: 18
        ambient_motion: true
        ambient_paused_opacity: 0.01

      border:
        framerate: 60
        charge_duration: 1.2
        rotation_duration: 5.0

    callbacks:
      on_left: "toggle_media_menu"
      on_middle: "play_pause"
      on_right: "automatic_selection"

    keybindings: []
```

If you want your external `styles.css` to completely control the appearance, set:

```yaml
use_default_styles: false
```

---

# Top-level options

| Option | Type | Default | Values / Range | Description |
|---|---|---:|---|---|
| `class_name` | string | `""` | Any CSS class name(s) | Adds custom class tokens to the widget frame. |
| `hide_empty` | boolean | `false` | `true`, `false` | Hides the widget when there is no active media session. |
| `compact` | boolean | `false` | `true`, `false` | Starts the widget in compact mode. Adds the `.compact` class while compact. |
| `layout` | string | `"standard"` | `standard`, `minimal` | `minimal` removes the bar title/time column. |
| `artwork_shape` | string | `"rounded"` | `square`, `rounded`, `circle` | Shape of bar artwork. |
| `controls_shape` | string | `"rounded"` | `square`, `rounded`, `circle` | Shape used by transport buttons in both the bar and popup. |
| `scale` | float | `1.0` | `0.75–2.0` | Global Media V2 geometry scale. |
| `artwork_size` | integer | `28` | `16–64` | Bar artwork size in logical pixels before global scaling. |
| `border_radius` | integer | `8` | `0–32` | Base corner radius used by Media V2 geometry/default styling. |
| `font_family` | string | `"Adwaita Mono"` | Font family | Font used by generated default Media V2 styles. |
| `use_default_styles` | boolean | `true` | `true`, `false` | Enables Media V2's internally generated QSS. |
| `scrolling_label` | object | See below | — | Bar-title scrolling configuration. |
| `controls` | object | See below | — | Bar transport control configuration. |
| `popup` | object | See below | — | Popup configuration. |
| `callbacks` | object | See below | — | Mouse callbacks for the widget. |
| `keybindings` | list | `[]` | Keybinding objects | Global keyboard shortcuts targeting this widget. |

Media V2 does not expose a separate bar-height option. The content uses its natural height; control the outer height with vertical QSS padding on `#media-v2-bar` or `.widget-container`.

---

# `scrolling_label`

Controls the title displayed directly in the bar.

| Option | Type | Default | Range | Description |
|---|---|---:|---|---|
| `enabled` | boolean | `true` | — | Scroll long bar titles. When disabled, the title is elided instead. |
| `speed` | float | `40.0` | `5–200` | Scrolling speed. |
| `delay` | integer | `3000` | `0–10000` ms | Delay before scrolling begins. |

---

# `controls`

Controls the size of the bar transport buttons.

| Option | Type | Default | Range | Description |
|---|---|---:|---|---|
| `size` | integer | `30` | `20–96` | Bar control size in logical pixels. The button container and its icon scale together. |

The full option path is `controls.size`. This intentionally keeps the icon proportional to its container instead of exposing a separate icon-size setting.

---

# `popup`

| Option | Type | Default | Values / Range | Description |
|---|---|---:|---|---|
| `blur` | boolean | `true` | — | Enables the native popup blur effect. |
| `round_corners` | boolean | `true` | — | Requests native rounded popup corners. |
| `round_corners_type` | string | `"normal"` | PopupWidget-supported value | Native corner style, normally `normal` or `small`. |
| `border_color` | string | `"System"` | System/color value | Native popup-window border color. This is separate from `popup.border`. |
| `alignment` | string | `"right"` | `left`, `right`, `center` | Popup alignment relative to the Media V2 widget. |
| `direction` | string | `"down"` | `up`, `down` | Direction in which the popup opens. |
| `offset_top` | integer | `6` | `-500–500` | Vertical popup offset. |
| `offset_left` | integer | `0` | `-500–500` | Horizontal popup offset. |
| `show_equalizer` | boolean | `true` | — | Show the equalizer section. |
| `scroll_title` | boolean | `true` | — | Scroll long popup titles. |
| `scroll_artist` | boolean | `false` | — | Scroll long artist labels. |
| `scrolling_label` | object | See below | — | Shared popup title/artist scrolling speed and delay. |
| `progress` | object | See below | — | Timeline/progress configuration. |
| `controls` | object | See below | — | Popup control icon sizing. |
| `artwork_position` | string | `"left"` | `left`, `right`, `top`, `hidden` | Position of the large popup artwork/disc. |
| `detail_order` | list | Default list | See below | Visible detail sections and their order. Duplicates are not allowed. |
| `timestamps` | string | `"below"` | `above`, `below`, `inline`, `hidden` | Position of elapsed/duration labels. |
| `time_display` | string | `"total"` | `total`, `remaining` | Show total duration or remaining time at the right side. |
| `equalizer_position` | string | `"bottom"` | `top`, `bottom` | Position of equalizer relative to main media details. |
| `show_separator` | boolean | `true` | — | Show separator between media details and equalizer. |
| `lyrics` | object | See below | — | Lyrics rendering and bounded online provider lookup. |
| `disc` | object | See below | — | Animated popup artwork/disc options. |
| `equalizer` | object | See below | — | Equalizer UI/audio backend. |
| `background` | object | See below | — | Popup content background. |
| `border` | object | See below | — | Animated Media V2 content border. |

## `detail_order`

The full option path is `popup.detail_order`.

Any unique, non-empty combination of:

```yaml
- "title"
- "artist"
- "output"
- "timeline"
- "controls"
```

For example:

```yaml
detail_order:
  - "title"
  - "artist"
  - "timeline"
  - "controls"
```

removes the output-device row.

---

# `popup.scrolling_label`

| Option | Type | Default | Range | Description |
|---|---|---:|---|---|
| `speed` | float | `40.0` | `5–200` | Popup title/artist scrolling speed. |
| `delay` | integer | `3000` | `0–10000` ms | Delay before scrolling begins. |

Whether the labels scroll is controlled separately by `scroll_title` and `scroll_artist`.

---

# `popup.progress`

| Option | Type | Default | Range | Description |
|---|---|---:|---|---|
| `smoothing_ms` | integer | `250` | `0–2000` | Duration used to smooth progress movement. Set `0` for effectively immediate updates. |
| `show_handle` | boolean | `true` | — | Show the seek handle. |

The entire progress control is disabled when the active GSMTC session is not seekable.

The seekbar host is 50 logical pixels high and includes a moving played-wave
layer. The wave remains clipped to the authoritative progress fill, keeps a
visible crest for short fills, fades while paused and stops when hidden. Seek
commands still use the captured media session and seek revision.

---

# `popup.lyrics`

| Option | Type | Default | Values / Range | Description |
|---|---|---:|---|---|
| `alignment` | string | `"left"` | `left`, `center`, `right` | Horizontal alignment for lyric rows. |
| `center_position` | float | `0.44` | `0.0–1.0` | Vertical position of the active line while following playback. |
| `lines_before` | integer | `-1` | `-1–100` | Visible rows before the active line. `-1` keeps all rows visible. |
| `lines_after` | integer | `-1` | `-1–100` | Visible rows after the active line. `-1` keeps all rows visible. |
| `inactive_opacity` | float | `-1.0` | `-1.0–1.0` | Opacity for inactive rows. `-1` keeps distance-based opacity. |
| `active_color` | string or null | `null` | Qt color | Active line and word color. `null` follows the current palette. |
| `inactive_color` | string or null | `null` | Qt color | Inactive lyric color. `null` follows the current palette. |
| `font_family` | string | `""` | Installed font or empty | Uses the popup font when empty. |
| `font_size` | integer | `18` | `8–72` | Lyric font size in logical pixels. |
| `font_weight` | integer | `700` | Qt weight values | Qt font weight. |
| `margins` | object | See below | — | Lyric row and placeholder margins. |
| `line_height` | integer | `30` | `0–200` | Minimum lyric row height in logical pixels. |
| `line_spacing` | integer | `6` | `0–100` | Spacing between lyric rows and placeholder controls. |
| `animation_duration_ms` | integer | `320` | `0–5000` ms | Line and scroll animation duration. |
| `browse_return_ms` | integer | `4000` | `0–60000` ms | Delay before browsing returns to the playing line. |
| `drag_threshold` | integer | `4` | `1–64` px | Pointer movement needed to start lyric browsing. |
| `auto_lookup` | boolean | `true` | — | Start provider lookup when Lyrics is selected. |
| `provider_order` | list | `["lrclib", "netease", "better_lyrics"]` | Unique provider names | Lookup tries enabled routes in the configured order. If every configured route is disabled, it uses the default active chain. |
| `better_lyrics_enabled` | boolean | `true` | — | Allow the documented Better Lyrics API route. |
| `musixmatch_enabled` | boolean | `false` | — | Opt in to Musixmatch requests. |
| `musixmatch_api_key` | string | `""` | — | API key for the official Musixmatch API. |
| `request_spacing_ms` | integer | `250` | `200–5000` ms | Minimum spacing between provider requests. |
| `request_timeout_ms` | integer | `10000` | `1000–60000` ms | Transfer timeout for a provider request. |

## `popup.lyrics.margins`

| Option | Type | Default | Range | Description |
|---|---|---:|---|---|
| `horizontal` | integer | `4` | `0–64` px | Horizontal lyric row margin. |
| `vertical` | integer | `0` | `0–64` px | Reserved vertical panel margin. |
| `placeholder` | integer | `8` | `0–64` px | Horizontal margin for empty and status content. |

The legacy aliases `center_ratio`, `visible_lines_before`, `visible_lines_after`,
`activeLineColor`, `inactiveLineColor`, `fontFamily`, `fontWeight`, `lineHeight`,
`lineSpacing`, `animation_ms`, `return_delay_ms`, and `providers` remain accepted
and are normalized to the names above.

Provider adapters share the request bounds, spacing and cancellation rules.
Better Lyrics can return TTML with word timing. Musixmatch requires an
explicit API key.

## Lyrics behavior

Lyrics lookup starts only while the popup is visible and the Lyrics tab is
selected. The default order is LRCLIB, NetEase and Better Lyrics. Musixmatch
can be placed anywhere in `provider_order` when its opt-in key is complete. The
effective sequence skips Better Lyrics when disabled and Musixmatch when disabled
or missing its key. If filtering removes every configured route, the default active chain
is used. Missing artist metadata prevents automatic lookup.

Responses are limited to 1 MiB, 5000 rows, 16384 characters per row and 30000
words. Invalid or unsupported data produces an error state. Instrumental and
unsynchronized plain lyrics have distinct presentations, and missing timing is
not invented. The lyric view exposes source and format warnings through its
tooltip and accessible description.

Timed lyrics highlight the active line as follow-scroll begins. The separate
highlight animation runs when the list is stationary. Wheel, drag or keyboard browsing pauses
follow for `browse_return_ms`; right-click resumes it immediately. Clicking a
timed line, or selecting it with the arrow keys and pressing Enter, requests a
seek when the player allows it. Track or source changes, metadata refresh,
dragging, tab changes, focus loss and close cancel a captured seek.

When `show_equalizer: true`, the lower section contains Equalizer, Audio and
Lyrics tabs. Ctrl+Tab and Ctrl+Shift+Tab switch sections, while Tab moves
through the controls. The option still controls the entire lower section.

---

# `popup.controls`

| Option | Type | Default | Range | Description |
|---|---|---:|---|---|
| `size` | integer | `43` | `20–96` | Popup control reference size in logical pixels. Play/pause uses this size; previous/next and all icons retain their existing proportions. |

The full option path is `popup.controls.size`. The container and icon always scale together.

---

# `popup.disc`

The popup artwork is rendered as a vinyl-style animated disc.

| Option | Type | Default | Range | Description |
|---|---|---:|---|---|
| `spin` | boolean | `true` | — | Rotate artwork while playing. |
| `visualizer` | boolean | `true` | — | Show the radial audio spectrum. |
| `rhythm` | boolean | `true` | — | Allow bass/kick energy to affect disc motion. |
| `glow` | boolean | `true` | — | Enable reactive glow. |
| `rhythm_strength` | float | `1.0` | `0–3` | Multiplier for reactive disc motion. |
| `glow_strength` | float | `1.0` | `0–3` | Multiplier for reactive glow. |
| `framerate` | integer | `60` | `15–60` FPS | Target update rate for disc/reactive effects. An explicit value overrides the default. |

The visualizer/rhythm/glow effects use YASB's Windows loopback audio capture and shared FFT service. Capture is attached while the popup disc is visible and active playback is occurring.

---

# `popup.equalizer`

The backend selector's full option path is `popup.equalizer.backend`.

| Option | Type | Default | Values / Range | Description |
|---|---|---:|---|---|
| `preset` | string | `"Flat"` | See presets below | Initial equalizer curve. |
| `custom_bands` | list[int] | Ten `0`s | Exactly 10 values, each `-12–12` dB | Curve used by the `Custom` preset. |
| `preset_effect` | string | `"lightning"` | `lightning`, `ripple`, `center_pulse`, `none` | Animation played when selecting presets. |
| `effect_speed` | float | `1.0` | `0.4–3.0` | Effect-duration multiplier. `<1` is faster; `>1` is slower. |
| `backend` | string | `"visual"` | `visual`, `equalizer_apo` | Select UI-only mode or Equalizer APO integration. |
| `apo` | object | See below | — | Equalizer APO configuration. |

## Presets

Supported configuration values:

```text
Flat
Bass
Treble
Vocal
Pop
Rock
Jazz
Classic
Custom
```

The popup has buttons for the eight built-in curves:

```text
Flat
Bass
Treble
Vocal
Pop
Rock
Jazz
Classic
```

`Custom` is selected automatically when a band is manually changed, or it can be selected through configuration using `custom_bands`.

## Preset effects

| Value | Behavior |
|---|---|
| `lightning` | Existing full-section lightning sweep and ring effect. |
| `ripple` | A low-to-high band sweep with roughly 25 ms between bands, short ease-out overshoot, and a highlight clipped inside each rounded fill. |
| `center_pulse` | Starts at the two middle bands and propagates outward symmetrically with the same clipped internal highlight. |
| `none` | Changes the band values without a special preset effect. |

`effect_speed` multiplies the animation duration. Values below `1.0` are faster; values above `1.0` are slower.

## Band order

`custom_bands` always uses this order:

```text
31 Hz
63 Hz
125 Hz
250 Hz
500 Hz
1 kHz
2 kHz
4 kHz
8 kHz
16 kHz
```

Example:

```yaml
custom_bands: [4, 3, 2, 0, -1, 0, 1, 2, 3, 4]
```

---

# `popup.equalizer.apo`

Equalizer APO support is optional.

| Option | Type | Default | Values / Range | Description |
|---|---|---:|---|---|
| `enabled` | boolean | `false` | — | Enables APO writes. `backend` must also be `equalizer_apo`. |
| `target_device` | string | `"default"` | `default` only | Target the current Windows default multimedia render device. |
| `processor` | string | `"graphic_eq"` | `graphic_eq`, `native` | Select the managed GraphicEQ file or the optional native DSP route. |
| `native_library` | string | `""` | Absolute DLL path | Native processor DLL to validate and load when `processor: native`. |
| `native_sha256` | string | `""` | 64 lowercase hex characters | Prepared SHA-256 for `native_library`. The DLL is rejected if its hash does not match. |
| `auto_preamp` | boolean | `true` | — | Automatically reduce preamp by the largest positive EQ gain. |
| `preamp_db` | float | `0.0` | `-24–12` dB | Manual preamp when `auto_preamp` is disabled. |
| `write_debounce_ms` | integer | `100` | `50–500` ms | Deprecated and ignored. Manual band changes are written only by Apply. |
| `manage_include` | boolean | `false` | — | Allow Media V2 to install/manage its Include block in Equalizer APO `config.txt`. |

For actual audio processing both must be enabled:

```yaml
equalizer:
  backend: "equalizer_apo"
  apo:
    enabled: true
```

With:

```yaml
backend: "visual"
```

the controls intentionally affect only the Media V2 display.

## Manual changes and Apply

Moving a band or releasing its slider changes a draft only. **Apply** commits the complete curve. Returning to the preset values while dragging holds the header steady until release. Closing the popup or leaving the Equalizer section discards unsubmitted edits. There is no legacy autosave mode; `write_debounce_ms` remains readable for configuration compatibility and has no effect.

Preset buttons remain immediate actions. Popups using the same managed file share committed/applied state; a second popup cannot overwrite or cancel another popup's active draft. Closing the editing popup releases its draft lease. Output-device changes retarget the shared committed curve, not an unsubmitted draft.

**Saved** means the managed configuration was persisted successfully; it does not prove that Equalizer APO is active on the endpoint. Failed writes retain the requested curve and show **Retry**. A clean header hides the Apply action. The visual backend stores the curve for display only.

## Native processor

The optional `native` processor uses an absolute DLL path and its prepared
SHA-256. The default `graphic_eq` processor keeps the ordinary Equalizer APO
file behavior. Build the optional x64 DLL from the repository root with:

```powershell
python -m src.build_media_dsp
```

This writes `YASBMediaProcessor.dll`, its build receipt and vendor notices to
`build/media-dsp/`. The command does not install or activate the DLL in
Equalizer APO. Native processing is reported separately from persistence, so a
successful save does not confirm endpoint processing. A missing processor or a
disconnected host remains unavailable and does not silently select another
processor.

Native state is profile- and endpoint-bound. The previous managed GraphicEQ
leaf is retained as `yasb-media-v2-eq.txt.yasb-native-backup`, and the native
state record keeps its own first `.json.backup`. Native settings use the same
Apply flow as the manual curve. Audio actions use the committed curve and keep
an unsubmitted EQ draft intact.

## Equalizer APO files

Media V2 uses:

```text
yasb-media-v2-eq.txt
```

for its generated 10-band configuration.

When Media V2 manages `config.txt`, it uses:

```text
# BEGIN YASB MEDIA V2 EQ
Include: yasb-media-v2-eq.txt
# END YASB MEDIA V2 EQ
```

A backup may be created as:

```text
config.txt.yasb-backup
```

## Equalizer APO limitations

- Equalizer APO must already be installed and configured for the Windows output device.
- Media V2 currently supports only `target_device: "default"`.
- Changing the Windows default output retargets the committed EQ curve. Manual edits take effect after Apply.
- The `graphic_eq` processor writes a device-specific 10-band `GraphicEQ`. The `native` processor writes its validated native route payload instead.
- Existing custom Equalizer APO filters remain active and can stack with the Media V2 EQ.
- Peace is deliberately not rewritten. If Peace is detected, the two processing chains can stack.
- `manage_include: false` requires the YASB Include block to already exist in `config.txt`.
- `manage_include: true` can install the Include automatically.
- Automatic neutralization is deliberately conservative and only applies to a recognized stock/sample Equalizer APO configuration.
- Arbitrary/custom configurations are not automatically removed.
- Write permissions can prevent configuration changes.
- If Windows does not provide a default multimedia render endpoint, APO processing cannot be targeted.
- The visual sliders keep their intended position even if an APO write fails; status text reports the backend problem.

## Popup layout and packaging

The standard popup targets 625x569 logical pixels at `scale: 1`. The lower
section has a 235-pixel preferred viewport and negotiates down within that
shell. The canonical layout keeps the 155-pixel EQ band row, the two-row preset
box and the tab strip reachable. Larger custom styles can use the section's
inner scroll area.

The Audio tab provides balance, mono, channel swap, Dynamic range and Reset.
Reset keeps Dynamic EQ and bypass state while resetting balance, mono, channel
swap and dynamics. The Dynamic control lives in the lower-section header. When
it is active, the manual EQ page is dimmed and a page-scoped overlay blocks
manual edits until the mode changes.

The popup moves and fades in over 760 ms. Artwork, metadata, transport controls,
divider, header, individual bands and presets enter in sequence. Closing takes
500 ms. Reopening during an exit continues from the current position and opacity.
Lower-section pages slide for 400 ms and crossfade for 250 ms. Audio reveals
its balance, channel and dynamics cards in order. Leaving a page cancels active
gestures and releases lyric demand. Lower controls expose status through accessible
descriptions.

The output device and the single-player “Via …” caption are centered in their
badges. With multiple players, the selector aligns its caption to the right and
reserves room for its arrow. All three shorten long names. A preset moves the visible EQ handles over
350 ms at the default effect speed. A second selection continues from the
displayed positions. Manual drags still edit a draft until Apply.

The optional native DSP build is x64-only and is separate from the ordinary
YASB executable and MSI. To build and run the application from `src`:

```powershell
python build.py build
.\dist\yasb.exe
```

`build.py` detects x64 or ARM64 and selects the matching tray-hook and Everything
DLL. To create an installer separately, run `python build.py bdist_msi` from
`src`. The MSI appears in `src/dist/out/` with an `x64` or `aarch64` suffix.
The frozen package includes this guide, the visualizer-label guide and the
root `schema.json`.

---

# `popup.background`

The background source's full option path is `popup.background.mode`.

| Option | Type | Default | Values / Range | Description |
|---|---|---:|---|---|
| `mode` | string | `"album_art"` | `color`, `album_art`, `image` | Popup surface background source. |
| `color` | string/null | `null` | Valid Qt color | Explicit fill for `color` mode. Alpha-capable colors are accepted. |
| `image` | string | `""` | Path | Image used by `image` mode. Required when `mode: image`. |
| `blur_radius` | integer | `18` | `0–64` | Gaussian blur radius applied to artwork/image backgrounds. |
| `ambient_motion` | boolean | `true` | — | Enables very slow ambient background motion. |
| `ambient_paused_opacity` | float | `0.01` | `0–0.08` | Ambient effect opacity while media exists but is paused. |

Example solid background:

```yaml
background:
  mode: "color"
  color: "#181825ee"
  image: ""
  blur_radius: 0
  ambient_motion: false
  ambient_paused_opacity: 0.0
```

Example custom image:

```yaml
background:
  mode: "image"
  image: "~/Pictures/media-background.jpg"
  blur_radius: 24
  ambient_motion: true
  ambient_paused_opacity: 0.01
```

User-home and environment-variable expansion are supported for image paths.

`blur_radius` here is image processing blur. It is not the same thing as `popup.blur`, which controls the native popup-window effect.

---

# `popup.border`

This configures the animated artwork-derived border drawn around the popup content.

| Option | Type | Default | Range | Description |
|---|---|---:|---|---|
| `framerate` | integer | `60` | `15–120` FPS | Border animation update rate. |
| `charge_duration` | float | `1.2` | `0.2–5.0` s | Initial border charge/reveal duration. |
| `rotation_duration` | float | `5.0` | `1–30` s | Duration of one full rotating-gradient cycle. |

The border palette follows colors extracted from the current artwork/background where available.

This animated content border is separate from:

```yaml
popup:
  border_color: "System"
```

which controls the native popup window border.

---

# Callbacks

## Mouse callback configuration

```yaml
callbacks:
  on_left: "toggle_media_menu"
  on_middle: "play_pause"
  on_right: "automatic_selection"
```

| Option | Default | Description |
|---|---|---|
| `on_left` | `toggle_media_menu` | Action for left click. |
| `on_middle` | `play_pause` | Action for middle click. |
| `on_right` | `automatic_selection` | Action for right click. |

## Media V2 callback actions

| Callback | Description |
|---|---|
| `toggle_media_menu` | Open or close the Media V2 popup. |
| `play_pause` | Request play/pause from the active GSMTC session. |
| `previous` | Request previous track. |
| `next` | Request next track. |
| `automatic_selection` | Remove a manual player pin and return to automatic session selection. |
| `toggle_compact` | Toggle bar compact mode. |
| `do_nothing` | Inherited YASB no-op callback. |
| `default` | Inherited default/no-op callback. |
| `exec ...` | Inherited YASB callback for executing a command. |

---

# Keybindings

Each keybinding uses:

| Option | Type | Required | Default | Description |
|---|---|---|---|---|
| `keys` | string | Yes | — | Global key combination. |
| `action` | string | Yes | — | Media V2 callback to execute. |
| `screen` | string | No | `"active"` | `active`, `cursor`, or `primary`. |

Example:

```yaml
keybindings:
  - keys: "win+shift+m"
    action: "toggle_media_menu"
    screen: "active"

  - keys: "win+shift+space"
    action: "play_pause"
    screen: "active"

  - keys: "win+shift+c"
    action: "toggle_compact"
    screen: "cursor"
```

Screen modes:

| Value | Behavior |
|---|---|
| `active` | Target the widget on the screen containing the focused window; normally falls back to the primary display when required. |
| `cursor` | Target the screen containing the mouse cursor. |
| `primary` | Always target the primary display. |

The `action` should normally be one of the Media V2 callback names listed above.

---

# Available placeholders

Media V2 currently has **no configurable text-format placeholders**.

There is no Media V2 equivalent of:

```text
{title}
{artist}
{album}
{position}
```

because Media V2 does not expose a `label`, `label_alt`, or format-string option.

Instead, its text fields are built directly by the widget:

- bar title → media title/fallback status;
- bar time → `current / duration`;
- popup title → media title;
- popup artist → `By <artist>`;
- popup output → current Windows default output;
- popup source → `Via <application>`;
- popup timeline → elapsed and total/remaining time;
- tooltip → available title, artist, album, application and backend error information.

Do not copy placeholder syntax from the legacy Media widget and expect it to work in Media V2.

---

# Available Styles

Media V2 exposes stable IDs, semantic classes, dynamic classes, and normal Qt pseudo-states.

Using semantic classes is recommended for general themes. IDs are useful when targeting one exact component.

## Widget selectors

| Element | Selectors |
|---|---|
| Media V2 root | `#media-v2`, `.media-v2-widget` |
| Custom class | `.<class_name>` |
| Compact state | `.media-v2-widget.compact` |
| Standard YASB container | `.media-v2-widget .widget-container` |
| Bar surface | `#media-v2-bar`, `.media-v2-bar` |
| Info/click area | `#media-info`, `.btn.media-info` |
| Artwork | `#media-art`, `.media-art`, `.artwork` |
| Text column | `#media-v2-text` |
| Title | `#media-v2-title`, `.media-title`, `.title` |
| Time | `#media-v2-time`, `.media-time` |
| Controls | `#media-controls`, `.media-controls` |
| Previous | `#media-previous`, `.btn.transport.previous` |
| Play | `#media-play`, `.btn.transport.play` |
| Pause state | `#media-play`, `.btn.transport.pause` |
| Next | `#media-next`, `.btn.transport.next` |
| Square control | `.btn.transport.square` |
| Rounded control | `.btn.transport.rounded` |
| Circle control | `.btn.transport.circle` |

`#media-play` remains the stable object ID when the button changes into pause mode. Use `.play` and `.pause` when you need different styling for the two states.

## Popup selectors

| Element | Selectors |
|---|---|
| Popup root | `#media-v2-popup`, `.media-v2-popup` |
| Scroll viewport | `#media-viewport` |
| Animated border container | `#media-border` |
| Main surface | `#media-surface`, `.media-surface` |
| Main media section | `#media-main` |
| Details column | `#media-details` |
| Artwork/disc | `#media-art`, `.media-art`, `.artwork` |
| Title | `#media-v2-title`, `.media-title`, `.title` |
| Artist | `#media-v2-artist`, `.media-artist`, `.artist` |
| Output row | `#media-v2-output`, `.media-output` |
| Output label | `#media-v2-output-label`, `.media-output-label`, `.label` |
| Informational source pill | `#media-source`, `.media-source` |
| Player selector | `#media-player-selector`, `.media-player-selector`, `.combobox` |
| Player menu | `#media-player-menu`, `.media-player-menu`, `.menu` |
| Timeline container | `#media-v2-timeline`, `.media-timeline` |
| Progress control | `#media-progress`, `.media-progress` |
| Progress track | `#media-progress-track`, `.media-progress-track` |
| Progress fill | `#media-progress-fill`, `.media-progress-fill` |
| Progress handle | `#media-progress-handle`, `.media-progress-handle` |
| Elapsed label | `#media-v2-elapsed`, `.playback-time.elapsed` |
| Duration label | `#media-v2-duration`, `.playback-time.duration` |
| Separator | `#media-v2-separator`, `.separator.media-separator` |
| Section tabs | `#media-section-tabs`, `.media-section-tabs` |
| Section viewport | `#media-section-viewport`, `.media-section-viewport` |
| Audio panel | `#media-audio`, `.media-audio` |
| Audio balance | `#media-audio-balance`, `.audio-balance` |
| Audio dynamics | `#media-audio-dynamics`, `.audio-dynamics` |
| Audio status | `#media-audio-status`, `.audio-status` |
| Audio reset | `#media-audio-reset`, `.audio-reset` |
| Lyrics panel | `#media-lyrics`, `.media-lyrics` |
| Lyrics view | `#media-lyrics-view`, `.media-lyrics-view` |
| Lyrics scrollbar | `#media-lyrics-scrollbar`, `.media-lyrics-scrollbar` |
| Lyrics status | `#media-lyrics-status`, `.media-lyrics-status` |
| Lyrics retry | `#lyrics-retry`, `.lyrics-action` |

## Popup playback-state classes

The popup root receives the current playback state as an additional class:

```css
.media-v2-popup.empty
.media-v2-popup.unknown
.media-v2-popup.opened
.media-v2-popup.changing
.media-v2-popup.stopped
.media-v2-popup.playing
.media-v2-popup.paused
.media-v2-popup.closed
```

Examples:

```css
.media-v2-popup.playing .media-title {
    font-weight: 700;
}

.media-v2-popup.paused .media-title {
    opacity: 0.75;
}

.media-v2-popup.empty .media-controls {
    opacity: 0.45;
}
```

## Player-selection classes

Both the player selector and the informational source pill can expose:

```css
.automatic
.pinned
```

For example:

```css
.media-player-selector.automatic {
    border: 1px solid transparent;
}

.media-player-selector.pinned {
    border: 1px solid #a78bfa;
}
```

With two or more sessions, `.media-player-selector` opens the anchored player menu. With fewer sessions, `.media-source` displays the source when available.

---

# Equalizer style selectors

| Element | Selector |
|---|---|
| Equalizer section | `#media-equalizer-section`, `.equalizer-section` |
| Band container | `#media-equalizer`, `.equalizer` |
| Title | `#media-equalizer-title`, `.equalizer-title`, `.title` |
| Current preset | `#media-equalizer-current`, `.equalizer-current`, `.label` |
| APO/status label | `#media-equalizer-status`, `.equalizer-status`, `.label` |
| Preset container | `#media-presets`, `.presets` |
| Any preset button | `.btn.preset` |
| Flat | `#media-preset-flat`, `.preset.flat` |
| Bass | `#media-preset-bass`, `.preset.bass` |
| Treble | `#media-preset-treble`, `.preset.treble` |
| Vocal | `#media-preset-vocal`, `.preset.vocal` |
| Pop | `#media-preset-pop`, `.preset.pop` |
| Rock | `#media-preset-rock`, `.preset.rock` |
| Jazz | `#media-preset-jazz`, `.preset.jazz` |
| Classic | `#media-preset-classic`, `.preset.classic` |
| Any EQ band | `.eq-band` |

There is no `#media-preset-custom` button. Moving an individual band changes the active state to `Custom`.

## Individual equalizer bands

```css
#media-eq-31   /* .band-31   */
#media-eq-63   /* .band-63   */
#media-eq-125  /* .band-125  */
#media-eq-250  /* .band-250  */
#media-eq-500  /* .band-500  */
#media-eq-1k   /* .band-1k   */
#media-eq-2k   /* .band-2k   */
#media-eq-4k   /* .band-4k   */
#media-eq-8k   /* .band-8k   */
#media-eq-16k  /* .band-16k  */
```

Useful slider subcontrols:

```css
.eq-band::groove:vertical
.eq-band::handle:vertical
.eq-band::add-page:vertical
```

These may also use normal interaction pseudo-states such as:

```css
.eq-band::handle:vertical:hover
.eq-band::handle:vertical:pressed
```

---

# Interaction pseudo-states

Normal Qt states are available on relevant controls:

```css
:hover
:pressed
:disabled
:checked
```

Examples:

```css
.media-controls .btn.transport:hover {}
.media-controls .btn.transport:pressed {}
.media-controls .btn.transport:disabled {}

.presets .btn.preset:hover {}
.presets .btn.preset:pressed {}
.presets .btn.preset:checked {}

.media-source:hover {}
.media-source:pressed {}
.media-source:disabled {}

.media-progress-fill:disabled {}
.media-progress-handle:disabled {}
```

The source menu uses QMenu item/subcontrol states:

```css
.media-player-menu::item
.media-player-menu::item:selected
.media-player-menu::item:checked
.media-player-menu::indicator
.media-player-menu::indicator:checked
```

---

# Copyable widget style

This is an external QSS example for the bar portion of Media V2. It is intentionally independent of the built-in theme.

For full control use:

```yaml
use_default_styles: false
```

```css
.media-v2-widget {
    color: #e5e7eb;
    background: transparent;
    font-family: "Adwaita Mono", "Cascadia Mono", "Consolas";
}

.media-v2-widget .widget-container {
    background: #17191f;
    border: 1px solid #2b303b;
    border-radius: 8px;
    padding: 0;
    margin: 0;
}

.media-v2-widget #media-v2-bar {
    background: transparent;
    border: none;
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

.media-v2-widget .media-art {
    color: #8b9cff;
    background: #282c35;
    border: none;
}

.media-v2-widget .btn.media-info {
    background: transparent;
    border: none;
    padding: 0;
}

.media-v2-widget .btn.media-info:hover {
    background: transparent; /* removes the optional bar-info hover fill */
}

.media-v2-widget .media-controls .btn.transport {
    background: #242832;
    color: #aeb6c7;
    border: none;
    padding: 0;
}

.media-v2-widget .media-controls .btn.transport.square {
    border-radius: 0;
}

.media-v2-widget .media-controls .btn.transport.rounded {
    border-radius: 8px;
}

.media-v2-widget .media-controls .btn.transport.circle {
    border-radius: 999px;
}

.media-v2-widget .media-controls .btn.transport:hover {
    background: #313744;
    color: #ffffff;
}

.media-v2-widget .media-controls .btn.transport:pressed {
    background: #1d2028;
}

.media-v2-widget .media-controls .btn.transport:disabled {
    color: #555d6d;
    background: #20232b;
}

.media-v2-widget .media-controls .btn.play,
.media-v2-widget .media-controls .btn.pause {
    color: #dce4ff;
}

.media-v2-widget .media-controls .btn.play:hover,
.media-v2-widget .media-controls .btn.pause:hover {
    color: #9fc2ff;
}

/* Optional compact-state overrides */
.media-v2-widget.compact .widget-container {
    border-radius: 6px;
}
```

---

# Copyable popup style

```css
.media-v2-popup {
    color: #e5e7eb;
    background: transparent;
    font-family: "Adwaita Mono", "Cascadia Mono", "Consolas";
}

.media-v2-popup .media-surface {
    background: #17191f;
    border: none;
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

.media-v2-popup .media-source:hover,
.media-v2-popup .media-player-selector:hover {
    color: #ffffff;
    background: #313744;
}

.media-v2-popup .media-source:pressed {
    background: #3a4150;
}

.media-v2-popup .media-source:disabled,
.media-v2-popup .media-player-selector:disabled,
.media-v2-popup .media-output-label:disabled {
    color: #596273;
}

.media-v2-popup .media-source.pinned {
    border-color: #9aa9ff;
}

.media-v2-popup .media-player-selector::drop-down {
    border: none;
    background: transparent;
    width: 18px;
}

/* Player/source menu */

.media-player-menu {
    color: #e5e7eb;
    background: #111318;
    border: 1px solid #343a47;
    border-radius: 8px;
    padding: 4px;
}

.media-player-menu::item {
    min-height: 26px;
    padding: 0 10px;
    border-radius: 6px;
}

.media-player-menu::item:selected {
    color: #ffffff;
    background: #343b4a;
}

.media-player-menu::item:checked {
    font-weight: 700;
}

.media-player-menu::indicator {
    width: 7px;
    height: 7px;
}

.media-player-menu::indicator:checked {
    background: #9aa9ff;
    border-radius: 3px;
}

/* Transport controls */

.media-v2-popup .media-controls .btn.transport {
    color: #aeb6c7;
    background: #242832;
    border: none;
    padding: 0;
}

.media-v2-popup .media-controls .btn.transport.square {
    border-radius: 0;
}

.media-v2-popup .media-controls .btn.transport.rounded {
    border-radius: 8px;
}

.media-v2-popup .media-controls .btn.transport.circle {
    border-radius: 999px;
}

.media-v2-popup .media-controls .btn.transport:hover {
    color: #ffffff;
    background: #313744;
}

.media-v2-popup .media-controls .btn.transport:pressed {
    background: #1d2028;
}

.media-v2-popup .media-controls .btn.transport:disabled {
    color: #555d6d;
    background: #20232b;
}

.media-v2-popup .media-controls .btn.play,
.media-v2-popup .media-controls .btn.pause {
    color: #d7c4ff;
}

/* Progress */

.media-v2-popup .media-progress {
    background: transparent;
    border: none;
    outline: none;
    padding: 0;
    margin-left: -6px;
    margin-right: 6px;
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

.media-v2-popup .media-progress-fill:disabled {
    background: #4b5260;
}

.media-v2-popup .media-progress-handle:disabled {
    background: #656d7b;
}

.media-v2-popup .playback-time {
    color: #87909f;
    font-size: 10px;
}

/* Separator */

.media-v2-popup .media-separator {
    background: rgba(255, 255, 255, 0.09);
    min-height: 2px;
    max-height: 2px;
    margin: 16px 0;
    border-radius: 1px;
}

/* Equalizer */

.media-v2-popup .equalizer-section {
    background: transparent;
}

.media-v2-popup .equalizer {
    color: #af9cff;
}

.media-v2-popup .equalizer-title {
    color: #c5b7ff;
    font-size: 15px;
    font-weight: 700;
}

.media-v2-popup .equalizer-current {
    color: #f3f4f6;
    font-weight: 700;
}

.media-v2-popup .equalizer-status {
    color: #7d8594;
    font-size: 10px;
}

.media-v2-popup .presets .btn.preset {
    color: #9ca3af;
    background: #242832;
    border: 1px solid transparent;
    border-radius: 8px;
}

.media-v2-popup .presets .btn.preset:hover {
    color: #ffffff;
    background: #313744;
}

.media-v2-popup .presets .btn.preset:pressed {
    background: #414858;
}

.media-v2-popup .presets .btn.preset:checked {
    color: #12141a;
    background: #ad9cff;
}

.media-v2-popup .equalizer QLabel {
    color: #8b93a3;
    font-size: 9px;
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

.media-v2-popup .eq-band::handle:vertical:hover {
    background: #c8bcff;
}

.media-v2-popup .eq-band::handle:vertical:pressed {
    background: #e1c7ff;
}

.media-v2-popup .eq-band::add-page:vertical {
    background: #9f8cff;
    border-radius: 6px;
}

/* Playback-state examples */

.media-v2-popup.playing .media-title {
    color: #ffffff;
}

.media-v2-popup.paused .media-art {
    opacity: 0.85;
}

.media-v2-popup.empty .media-title,
.media-v2-popup.stopped .media-title {
    color: #9299a8;
}
```

The paired progress margins shift the whole control left while preserving its layout allocation. Positive left padding moves its contents right, so use a small negative left margin for this adjustment.

The examples above assume approximately `scale: 1.0` and `border_radius: 8`. Unlike Media V2's generated default QSS, a normal external stylesheet does not automatically multiply pixel sizes by the widget's `scale` setting.

---

# Styling states reference

## Progress states

Normal:

```css
.media-progress-track {}
.media-progress-fill {}
.media-progress-handle {}
```

Unavailable/disabled:

```css
.media-progress-fill:disabled {}
.media-progress-handle:disabled {}
```

The slider becomes disabled automatically when GSMTC does not provide a valid seekable timeline.

## Source-menu states

Player selector and informational source pill:

```css
.media-player-selector:hover {}
.media-player-selector:pressed {}
.media-source:disabled {}

.media-source.automatic {}
.media-source.pinned {}
```

Popup menu:

```css
.media-player-menu::item {}
.media-player-menu::item:selected {}
.media-player-menu::item:checked {}
.media-player-menu::indicator:checked {}
```

## Equalizer states

```css
.presets .btn.preset:hover {}
.presets .btn.preset:pressed {}
.presets .btn.preset:checked {}

.eq-band::handle:vertical:hover {}
.eq-band::handle:vertical:pressed {}
```

## Audio and Lyrics states

```css
.media-audio .audio-card {}
.media-audio .audio-status {}
.media-audio .audio-reset:hover {}
.media-lyrics-view {}
.media-lyrics-scrollbar:vertical {}
.media-lyrics-scrollbar::handle:vertical:hover {}
.media-lyrics-scrollbar::handle:vertical:pressed {}
.media-lyrics-status {}
.lyrics-action:hover {}
```

## Transport states

```css
.btn.transport:hover {}
.btn.transport:pressed {}
.btn.transport:disabled {}

.btn.transport.play {}
.btn.transport.pause {}
.btn.transport.previous {}
.btn.transport.next {}

.btn.transport.square {}
.btn.transport.rounded {}
.btn.transport.circle {}
```

## Popup playback states

```css
.media-v2-popup.empty {}
.media-v2-popup.unknown {}
.media-v2-popup.opened {}
.media-v2-popup.changing {}
.media-v2-popup.stopped {}
.media-v2-popup.playing {}
.media-v2-popup.paused {}
.media-v2-popup.closed {}
```

---

# Custom-painted components and QSS limitations

Some Media V2 elements use custom Qt painting rather than ordinary QSS primitives.

### Album artwork / disc

The album-art component paints its own clipped artwork, fallback note, vinyl details, rotation, reactive movement, and vinyl outline. Normal bar artwork has no playing-state outline.

QSS colors can influence its palette, but QSS cannot directly replace the internal disc animation logic.

### Animated popup border

`#media-border` is custom-painted using an animated conical gradient. Its animation rate and timing come from:

```yaml
popup:
  border:
```

not normal QSS animation properties.

### Album-art/image background

`#media-surface` performs its own background image processing, cross-fade, blur, overlay, palette extraction and ambient rendering.

QSS provides the underlying/fallback surface, but options under:

```yaml
popup:
  background:
```

control the actual media-background rendering.

### Equalizer effects

The lightning, ripple, and center-pulse preset effects are custom-painted. QSS styles the band chrome, handles, labels, and buttons, but does not define these animations.

---

# Deprecated / migrated option names

Media V2 currently accepts several older names for compatibility, but new configurations should use the canonical options documented above.

| Old option | Current option / behavior |
|---|---|
| `bar_scrolling` | `scrolling_label` |
| `popup.scrolling` | `popup.scrolling_label` |
| `popup.background.native_blur` | `popup.blur` |
| `popup.background.mode: "qss"` | `popup.background.mode: "color"` |
| `popup.equalizer.preset_effect: "blur_slide"` | Converted to `"none"` |
| `popup.widget_offset` | `popup.offset_top` |
| `popup.placement` | Removed |
| `popup.edge_offset` | Only approximated through `offset_left` for old screen placement |
| `popup.bar_offset` | Only approximated through `offset_top` |
| `popup.direction: "auto"` | Converted to `"down"` |

Legacy absolute/screen placement cannot be reproduced exactly by the current parent-relative `PopupWidget` placement system.

---

# Quick reference

Minimal Media V2:

```yaml
media_v2:
  type: "yasb.media_v2.MediaWidgetV2"
  options:
    callbacks:
      on_left: "toggle_media_menu"
      on_middle: "play_pause"
      on_right: "automatic_selection"
```

Minimal visual equalizer:

```yaml
popup:
  show_equalizer: true
  equalizer:
    preset: "Flat"
    backend: "visual"
```

Equalizer APO:

```yaml
popup:
  show_equalizer: true
  equalizer:
    preset: "Flat"
    backend: "equalizer_apo"
    apo:
      enabled: true
      target_device: "default"
      auto_preamp: true
      manage_include: false
```

Player pin state:

```css
.media-source.automatic {}
.media-source.pinned {}
```

Playback state:

```css
.media-v2-popup.playing {}
.media-v2-popup.paused {}
.media-v2-popup.stopped {}
.media-v2-popup.empty {}
```

Interactive states:

```css
:hover {}
:pressed {}
:disabled {}
:checked {}
```
