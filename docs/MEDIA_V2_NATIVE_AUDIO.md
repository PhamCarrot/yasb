# Media V2 native audio processor

The optional native processor adds adaptive EQ, stereo balance, channel mixing
and dynamics to Media V2. It uses Equalizer APO on the Windows default playback
device. Use a YASB build from this fork with a Media V2 widget already configured.
The processor supports x64 Windows and shared-mode stereo playback at 44.1, 48,
88.2, 96, 176.4 or 192 kHz.

## Build and place the DLL

Use x64 Python 3.14 or later and Visual Studio or Visual Studio Build Tools
with **Desktop development with C++**, MSVC x64/x86 tools and a Windows SDK.
From the root of your checkout of this fork, run in PowerShell:

```powershell
python -m src.build_media_dsp
```

The build writes `YASBMediaProcessor.dll`, `build.json` and third-party notices
under `build/media-dsp/`. Copy the DLL, receipt and notices into a permanent,
versioned local folder. Both your YASB account and the Windows audio host need
read and execute access to the DLL. For example, use a folder under the
Equalizer APO installation, with administrator permission for the copy if
required. Replace the example path below with the actual deployed path. Run
the hash command on **your own deployed DLL** and use the 64 lowercase hexadecimal
characters it prints for `native_sha256`.

```powershell
$dll = 'C:\Program Files\EqualizerAPO\VSTPlugins\YASBMediaDSP-v1\YASBMediaProcessor.dll'
(Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant()
```

If this YASB profile already uses the native processor, keep the old DLL and
back up the profile, its `media-dsp` records and the managed APO configuration
before upgrading. YASB checks the saved DLL path, hash and build and blocks an
unreviewed change. Keep using the existing binding until you have a migration
that preserves the saved EQ and Audio settings.

## Attach Equalizer APO and configure Media V2

1. Install x64 Equalizer APO. Open **Equalizer APO Device Selector** (called
   **Configurator** in older versions), select the Windows default multimedia
   output under playback devices and follow its restart prompt. If you switch
   to another output, check that device's attachment too.
   [Equalizer APO installation and troubleshooting](https://sourceforge.net/p/equalizerapo/wiki/Documentation/)
2. In the active YASB profile's `config.yaml`, merge these keys into
   `widgets.<your Media V2 widget ID>.options.popup.equalizer`. Use your
   existing widget ID in place of `media_v2` and preserve its other options.
   Substitute the actual absolute DLL path and the hash from PowerShell.

   ```yaml
   widgets:
     media_v2:
       type: "yasb.media_v2.MediaV2Widget"
       options:
         popup:
           equalizer:
             backend: equalizer_apo
             apo:
               enabled: true
               target_device: default
               processor: native
               native_library: 'C:\Program Files\EqualizerAPO\VSTPlugins\YASBMediaDSP-v1\YASBMediaProcessor.dll'
               native_sha256: '<your lowercase SHA-256>'
               manage_include: true
   ```

3. `manage_include: true` lets YASB maintain its Include block in
   `config/config.txt` under the Equalizer APO installation. If you manage that
   file, set `manage_include: false` and ensure it contains one copy of this
   block. YASB needs write access to the managed configuration directory. It
   generates `yasb-media-v2-eq.txt` for the endpoint selected in Windows.

   ```text
   # BEGIN YASB MEDIA V2 EQ
   Include: yasb-media-v2-eq.txt
   # END YASB MEDIA V2 EQ
   ```

4. From the YASB tray menu, select **Reload YASB**, then open the Media V2
   popup. YASB sets up the native route or restores the saved settings on load.

## Use the controls and check playback

- **Equalizer → Dynamic** replaces the manual EQ with an adaptive correction
  learned from playback. Turn Dynamic off to return to the saved manual curve.
  Click **Apply** on any pending manual changes before enabling Dynamic if you
  want to keep those edits.
- **Audio** has stereo balance, **Mono audio**, **Swap L/R**, and **Dynamic
  range** with **Off**, **Balanced** and **Night**. These controls save
  automatically. Mono averages left and right into both channels and disables
  balance and Swap. The saved stereo settings resume when Mono is turned off.
  With Mono off, use a known left/right recording to check that Swap exchanges
  the channels.
- Play audio through the attached output and watch the status under **Audio**.
  **Processing frames confirmed** means recent frames advanced with the saved
  settings acknowledged and host latency settled. **Saved; audio host has not
  connected** means YASB has saved the settings and is waiting for the host.
  **Waiting for playback frames** means a host is connected with no recent
  frame progress, which can occur when playback is idle. During latency or
  settings confirmation, give the playing stream time to settle. Silent
  buffers can also advance frame counters. Use a known audible signal to
  verify sound and channel orientation.

[Media V2 widget options and Equalizer APO troubleshooting](../MEDIA_V2_GUIDE.md)
