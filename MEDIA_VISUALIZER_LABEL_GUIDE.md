# Media Visualizer Label

`MediaVisualizerWidget` extends YASB's audio visualizer with a media label drawn in front of the visualization. The spectrum still represents the Windows default output device, while the label follows the selected Windows media session.

## Configuration

```yaml
media_visualizer:
  type: "yasb.media_visualizer.MediaVisualizerWidget"
  options:
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
```

All normal audio-visualizer options remain available, including `style`, `height`, `smoothness`, `sensitivity`, `auto_gain`, `framerate`, frequency range, channels, and bar/wave/dot settings.

## Label Options

| Option | Default | Description |
| --- | --- | --- |
| `show_label` | `true` | Show media text over the visualizer. |
| `label` | `"{title}"` | Label format. Supports `{title}`, `{artist}`, and `{s}`. |
| `separator` | `" - "` | Text inserted by `{s}` when both surrounding values exist. |
| `max_label_length` | `30` | Static truncation limit or scrolling-label width in approximate characters. `0` removes the limit. |
| `visualizer_opacity` | `1.0` | Canvas opacity from `0.0` to `1.0`; the label remains fully opaque. |
| `scrolling_label.enabled` | `false` | Scroll text that exceeds the label width. |
| `scrolling_label.speed` | `30` | Scroll speed in pixels per second, from `1` to `250`. |
| `scrolling_label.delay` | `1500` | Pause before each pass, from `0` to `60000` milliseconds. |
| `scrolling_label.style` | `left` | `left`, `right`, `bounce`, or `bounce-ease`. |
| `scrolling_label.separator` | three spaces | Gap between repeated text for left/right scrolling. |
| `scrolling_label.edge_fade` | `true` | Fade the label edges while scrolling. |
| `scrolling_label.fade_width` | `12` | Edge-fade width from `1` to `200` pixels. |

Missing title or artist values are removed cleanly, including the unused `{s}` separator. With no usable metadata, the label is hidden.

## Styling

```css
.media-visualizer-widget .media-label {
    color: #cdd6f4;
    background: transparent;
    font-size: 12px;
    font-weight: 600;
}
```

The label is mouse-transparent, so the original visualizer callbacks continue to work.

## Related Guide

For the full media player and popup, see [Media V2](MEDIA_V2_GUIDE.md).
