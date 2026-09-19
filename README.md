### 1. Overview

This fork adds two related media features:

- **Media V2** — a Windows GSMTC media widget with artwork, playback controls, source selection, a detailed popup, visual effects, and an optional equalizer.
- **Media Visualizer Label** — new configuration for displaying the selected media title and artist in front of the existing audio visualizer.

Media V2's popup design and motion are inspired by the media widget in [Serpantinum Shell](https://github.com/ilyamiro/serpantinum).

### 2. Main features

**Media V2**

- Bar artwork, title, timeline, and transport controls.
- One-click `Via ...` player selection with automatic and manual modes.
- Configurable popup layout, artwork position, progress display, background, disc visualizer, and equalizer.
- Independent bar and popup scrolling and control scales.
- YASB-compatible callbacks, keybindings, semantic QSS selectors, and accessibility.

**Media Visualizer Label**

- `{title}`, `{artist}`, and conditional `{s}` separator formatting.
- Static truncation or smooth scrolling.
- Configurable speed, delay, direction or bounce style, repeat gap, and edge fade.
- Independent visualizer opacity so the label remains legible.
- A shared media backend that does not create another Windows session manager.

### 3. Guides

- [Media V2 guide](MEDIA_V2_GUIDE.md)
- [Media Visualizer Label guide](MEDIA_VISUALIZER_LABEL_GUIDE.md)

 
