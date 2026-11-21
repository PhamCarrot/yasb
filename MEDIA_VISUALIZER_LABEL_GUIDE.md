# Audio Visualizer Media Label Options

The Audio Visualizer widget can show the title and artist of the current media on top of the visualizer. The label is off by default.

Only the label options are listed here. For every other option see [Audio Visualizer](docs/widgets/%28Widget%29-Audio-Visualizer.md).

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `show_label` | boolean | `false` | Show the media label on top of the visualizer. |
| `label` | string | `"{title}"` | The label format. Supports `{title}`, `{artist}` and the separator `{s}`. |
| `separator` | string | `" - "` | The dynamic separator `{s}`. It is removed when the title or the artist is missing. |
| `max_label_length` | integer | `30` | Maximum label length in characters (0–200). Longer text is truncated, or scrolled when `scrolling_label` is enabled. `0` removes the limit. |
| `visualizer_opacity` | float | `1.0` | Opacity of the visualizer (0.0–1.0). The label is not affected. |
| `scrolling_label` | dict | [See below](#scrolling-label-options) | Label scrolling options. |

## Example Configuration

```yaml
audio_visualizer:
  type: "yasb.audio_visualizer.AudioVisualizerWidget"
  options:
    style: bars
    height: 18
    show_label: true
    label: "{artist}{s}{title}"
    separator: " - "
    max_label_length: 36
    visualizer_opacity: 0.35
    scrolling_label:
      enabled: true
      speed: 30
      delay: 1500
      style: "left"
      separator: "   "
      edge_fade: true
      fade_width: 12
```

## Scrolling Label Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | `false` | Scroll the label when the text is longer than `max_label_length`. |
| `speed` | integer | `30` | Scrolling speed in pixels per second (1–250). |
| `delay` | integer | `1500` | Pause before each pass, in ms (0–60000). |
| `style` | string | `"left"` | Scrolling style: `"left"`, `"right"`, `"bounce"` or `"bounce-ease"`. |
| `separator` | string | `"   "` | The separator between repeating text in `left` or `right` style. |
| `edge_fade` | boolean | `true` | Fade the label edges while scrolling. |
| `fade_width` | integer | `12` | Width of the edge fade in pixels (1–200). |

## Notes

- The label shows the same player as the media widgets. The visualizer itself still follows the output device.
- The label is hidden when the player reports no title and no artist.
- Clicks pass through the label, so the widget callbacks keep working.

## Available Styles

```css
.audio-visualizer-widget {}
.audio-visualizer-widget .widget-container {}
.audio-visualizer-widget .audio-visualizer-canvas {}
.audio-visualizer-widget .media-label {}
```

## Example Style

```css
.audio-visualizer-widget .widget-container {
    background: #1e1e2e;
    border-radius: 8px;
    padding: 0 8px;
}
.audio-visualizer-widget .audio-visualizer-canvas {
    -qproperty-fillbrush: qlineargradient(
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

> [!NOTE]
> Gradients for `-qproperty-fillbrush` use the Qt `qlineargradient(...)` syntax.
