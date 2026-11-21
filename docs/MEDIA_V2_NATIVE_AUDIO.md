# Media V2 Native Audio Processor

The native audio processor is an optional add-on for the [Media V2](../MEDIA_V2_GUIDE.md) widget. It adds a dynamic equalizer, stereo balance, mono, channel swap and dynamic range control to the popup. It runs inside [Equalizer APO](https://sourceforge.net/projects/equalizerapo/) on the Windows default playback device.

> [!NOTE]
> The processor is x64 only and is not included in the YASB installer. It works with shared-mode stereo playback at 44.1, 48, 88.2, 96, 176.4 or 192 kHz.

## Requirements

- A YASB build from this fork with a Media V2 widget in your `config.yaml`.
- x64 Python 3.14 or later.
- Visual Studio or Visual Studio Build Tools with **Desktop development with C++**, the MSVC x64/x86 tools and a Windows SDK.
- Equalizer APO (x64), installed for your default playback device.

## Build the DLL

From the root of the repository, run:

```powershell
python -m src.build_media_dsp
```

The build writes `YASBMediaProcessor.dll`, `build.json` and the third-party licenses to `build/media-dsp/`.

Copy them to a permanent folder that both your user account and the Windows audio service can read and execute, for example a folder under the Equalizer APO installation. Then get the SHA-256 of the copied DLL:

```powershell
$dll = 'C:\Program Files\EqualizerAPO\VSTPlugins\YASBMediaDSP-v1\YASBMediaProcessor.dll'
(Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant()
```

## Configuration

Add the options below to the `popup.equalizer` section of your Media V2 widget, with your own DLL path and hash.

```yaml
media_v2:
  type: "yasb.media_v2.MediaWidgetV2"
  options:
    popup:
      equalizer:
        backend: "equalizer_apo"
        apo:
          enabled: true
          processor: "native"
          native_library: 'C:\Program Files\EqualizerAPO\VSTPlugins\YASBMediaDSP-v1\YASBMediaProcessor.dll'
          native_sha256: "<your lowercase SHA-256>"
          manage_include: true
```

Then:

1. Open the **Equalizer APO Device Selector** (**Configurator** in older versions), select your default playback device and restart when asked. Repeat this if you switch to another output device.
2. Reload YASB and open the Media V2 popup.

With `manage_include: true` YASB adds its `Include` line to Equalizer APO's `config.txt`. If you manage that file yourself, set it to `false` and add the block below once.

```text
# BEGIN YASB MEDIA V2 EQ
Include: yasb-media-v2-eq.txt
# END YASB MEDIA V2 EQ
```

> [!NOTE]
> YASB remembers the DLL path, hash and build, and refuses a DLL that has changed. Before you replace the DLL, keep the old one and back up your YASB config folder and the Equalizer APO config folder.

## Controls

- **Dynamic** (Equalizer tab): Replaces the manual equalizer with a correction that adapts to what is playing. Turn it off to return to your saved curve. Click **Apply** first if you have unsaved band changes, otherwise they are discarded.
- **Balance** (Audio tab): Stereo balance between left and right.
- **Mono audio** (Audio tab): Mixes left and right into both channels. Balance and Swap are disabled while it is on.
- **Swap L/R** (Audio tab): Swaps the left and right channels.
- **Dynamic range** (Audio tab): `Off`, `Balanced` or `Night`.
- **Reset** (Audio tab): Resets balance, mono, swap and dynamic range.

Changes on the Audio tab are saved automatically.

## Status Messages

The Audio tab shows the state of the processor while audio is playing.

| Status | Description |
| --- | --- |
| Processing frames confirmed | The processor is running with your saved settings. |
| Bypass confirmed | The processor is running and bypassed. |
| Saved; audio host has not connected | The settings are saved and YASB is waiting for Equalizer APO to load the processor. |
| Audio host connected; unsupported sample rate | The playback format is not one of the supported sample rates. |
| Audio host connected; waiting for playback frames | The processor is loaded but no audio is passing through it, for example when playback is idle. |
| Audio frames arriving; host latency update pending | The stream is still settling. Wait a moment. |
| Audio frames arriving; waiting for settings confirmation | The stream is still settling. Wait a moment. |

> [!NOTE]
> Silence also counts as playback, so the status alone does not prove that you hear the processed sound. Use a recording you know to check the result and the left and right channels.

For the equalizer options and Equalizer APO troubleshooting see [Media V2](../MEDIA_V2_GUIDE.md).
