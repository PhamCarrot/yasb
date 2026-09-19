# Audio Visualizer with Media Label

The media label is built into YASB's original `AudioVisualizerWidget`. The spectrum continues to represent the Windows default output device, while the optional label follows the selected Windows media session. No separate media-visualizer widget is required.

## Configuration options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `class_name` | string | `""` | Extra QSS class on the widget. |
| `style` | `bars`, `waves`, `dots` | `bars` | Visualization style. |
| `height` | integer `4..64` | `14` | Maximum painted visualization height, not the outer widget height. |
| `smoothness` | integer `0..100` | `55` | Smoothing applied to level changes. |
| `sensitivity` | integer `0..100` | `50` | Input sensitivity. |
| `auto_gain` | boolean | `true` | Normalize capture levels automatically. |
| `framerate` | integer `1..120` | `60` | Canvas refresh rate. |
| `freq_min` | integer `20..24000` | `50` | Lowest analyzed frequency in hertz. Must be lower than `freq_max`. |
| `freq_max` | integer `20..24000` | `12000` | Highest analyzed frequency in hertz. |
| `hide_idle` | boolean | `false` | Hide the visualizer after sustained silence. |
| `hide_idle_after` | integer `100..60000` | `2000` | Idle duration before hiding, in milliseconds. |
| `channels` | `stereo`, `mono` | `mono` | Channel layout. |
| `mono_option` | `average`, `left`, `right` | `average` | Source used when channels is mono. |
| `reverse` | boolean | `false` | Reverse sample order. |
| `mirror` | boolean | `false` | Mirror samples around the center. |
| `edge_fade` | integer or `[left, right]` | `0` | Fade this many samples at one or both edges. |
| `bars` | object | see below | Bar-style geometry. |
| `waves` | object | see below | Wave-style geometry. |
| `dots` | object | see below | Dot-style geometry. |
| `show_label` | boolean | `false` | Show selected media text over the canvas. |
| `label` | string | `"{title}"` | Format using `{title}`, `{artist}`, and conditional `{s}`. |
| `separator` | string | `" - "` | Text inserted by `{s}` when both neighboring fields exist. |
| `max_label_length` | integer `0..200` | `30` | Static truncation limit or approximate scrolling viewport width. `0` removes this limit. |
| `scrolling_label` | object | see below | Media-label scrolling behavior. |
| `visualizer_opacity` | float `0..1` | `1.0` | Canvas opacity. The media label remains fully opaque. |
| `callbacks` | object | empty | Standard YASB mouse callbacks. |
| `keybindings` | list | `[]` | Standard YASB keybinding entries. |

### Style geometry

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `bars.count` | integer `4..128` | `24` | Number of bars. |
| `bars.width` | integer `1..32` | `2` | Bar width. |
| `bars.gap` | integer `0..32` | `4` | Gap between bars. |
| `waves.width` | integer `16..512` | `80` | Wave canvas width. |
| `dots.count` | integer `4..128` | `24` | Number of dots. |
| `dots.size` | integer `1..32` | `2` | Dot diameter. |
| `dots.gap` | integer `0..32` | `4` | Gap between dots. |

### Media label scrolling

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `scrolling_label.enabled` | boolean | `false` | Scroll text that exceeds the label viewport. |
| `scrolling_label.speed` | integer `1..250` | `30` | Scroll speed in pixels per second. |
| `scrolling_label.delay` | integer `0..60000` | `1500` | Pause before each pass, in milliseconds. |
| `scrolling_label.style` | `left`, `right`, `bounce`, `bounce-ease` | `left` | Movement style. |
| `scrolling_label.separator` | string | three spaces | Gap between repeated text in left/right modes. |
| `scrolling_label.edge_fade` | boolean | `true` | Fade label edges while scrolling. |
| `scrolling_label.fade_width` | integer `1..200` | `12` | Edge-fade width in logical pixels. |

Missing title or artist fields are removed cleanly, including an unused `{s}` separator. The label is hidden when no usable metadata exists.

## Example configuration

```yaml
audio_visualizer:
  type: "yasb.audio_visualizer.AudioVisualizerWidget"
  options:
    class_name: "audio-visualizer-widget"
    style: bars
    height: 18
    smoothness: 70
    sensitivity: 55
    auto_gain: true
    framerate: 30
    freq_min: 50
    freq_max: 12000
    hide_idle: false
    hide_idle_after: 2000
    channels: stereo
    mono_option: average
    reverse: false
    mirror: true
    edge_fade: [4, 4]
    bars:
      count: 28
      width: 2
      gap: 3
    waves:
      width: 80
    dots:
      count: 24
      size: 2
      gap: 4
    show_label: true
    label: "{artist}{s}{title}"
    separator: " - "
    max_label_length: 36
    visualizer_opacity: 0.35
    scrolling_label:
      enabled: true
      speed: 30
      delay: 1500
      style: left
      separator: "   "
      edge_fade: true
      fade_width: 12
    callbacks:
      on_left: do_nothing
      on_middle: do_nothing
      on_right: do_nothing
    keybindings: []
```

## Available styles

```css
.audio-visualizer-widget {}
.audio-visualizer-widget .widget-container {}
.audio-visualizer-widget .audio-visualizer-canvas {}
.audio-visualizer-widget .media-label {}
```

### Gradient visualizer and label example

```css
.audio-visualizer-widget .widget-container {
    background: #1e1e2e;
    border-radius: 8px;
    padding: 0 8px;
}

.audio-visualizer-widget .audio-visualizer-canvas {
    qproperty-fillbrush: qlineargradient(
        x1: 0, y1: 1, x2: 0, y2: 0,
        stop: 0 #74c7ec,
        stop: 0.5 #89b4fa,
        stop: 1 #cba6f7
    );
}

.audio-visualizer-widget .media-label {
    color: #cdd6f4;
    background: transparent;
    font-size: 12px;
    font-weight: 600;
}
```

The exact property is `qproperty-fillbrush` without a leading hyphen. Qt stylesheets use `qlineargradient(...)`, not the browser-CSS `linear-gradient(...)` function. The canvas class remains `.audio-visualizer-canvas` because the label was integrated into the original widget.

The label is mouse-transparent, so the original audio-visualizer callbacks continue to work.

## Related guide

For the full media player and popup, see [Media V2](MEDIA_V2_GUIDE.md).
