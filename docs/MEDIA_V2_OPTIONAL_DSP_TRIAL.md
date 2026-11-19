# Optional Media V2 native DSP trial

Prepared 18 November 2026. This is a proposal for a future, separately authorized
trial. The current run used a synthetic host and read-only deployment discovery.
Live endpoint association, host permissions, latency negotiation and audible
processing still need evidence.

## Candidate and local evidence

- Processor build `386112c60e9c4364`, Windows x64, MSVC 14.44.35207 / Windows SDK
  10.0.26100.0. Protocol 3. The nine build inputs match the current checkout.
- Use `.git/final-001/dsp-candidate-verified/YASBMediaProcessor.dll`, SHA-256
  `f77afffdaa75194e47069889ab789a8e697656eafc6abffcc05b8b685b75e636`.
  The ordinary build has test hooks disabled. The copy includes the project MIT
  license and the unchanged DPF/Xaymar VST2 header, license and README.
- `.git/final-001/dsp-candidate.json` records the candidate files, original
  compiler command and four new synthetic host exits (all 0). The host binary
  is bound to the archived DSP-003 harness source. The integrated suite builds
  the current harness separately. Revalidate the exact DLL digest before any
  trial. A different build needs a reviewed binding and migration.
- Scope is x64 stereo float32 shared-mode output at 44.1, 48, 88.2, 96, 176.4
  or 192 kHz. Exclusive and RAW routes, other channel layouts and restricted
  real host behavior need separate evidence.
  [Processor contracts and provenance](../src/core/widgets/services/media/native/README.md)

## Read-only baseline and backup

The 64-bit Equalizer APO registry key resolves to `C:\Program Files\EqualizerAPO`
with config under `C:\Program Files\EqualizerAPO\config`. Installed Equalizer APO
is 1.4.2.0. The parent already has the valid managed Include. The candidate
profile is `C:\Users\PhamCarrot\.config\yasb\config.yaml`. Confirm the selected
profile and running YASB binary before using it.

The preflight in
`.git/final-001/deployment-backup/preflight-20261118-024136Z/manifest.json`
records original paths, existence, file lengths, hashes, timestamps and ACLs.
The three existing files were copied into that directory with CurrentUser
DPAPI encryption, then decrypted in memory and compared byte-for-byte by hash.
Only the same Windows user can decrypt those copies. The current bytes and
directory ownership must be checked again immediately before authorization
is used. Take a fresh snapshot if any baseline or selected profile differs.

| Existing file | SHA-256 |
| --- | --- |
| Candidate profile `config.yaml` | `964400873d4a0cf3d88e0335d59c07f8a09e7dc890cf8982140deecfab32be12` |
| APO `config.txt` | `7f50a8f7767d7a8a12b62be5fbd121650c291d7b2f8617146b3a03dd97f4bf14` |
| APO `yasb-media-v2-eq.txt` | `e0b31e2755a6e77b0b708aee4d5601df2ba02e670eb1ebc774a1934aac464b24` |

The trial DLL directory, `config.txt.yasb-backup`, managed leaf
`.yasb-native-backup`, and the profile's native record and its `.backup` were
absent. The record path is
`media-dsp/67dff64e428a1a755266b069de19cd2bb1f0afd79242a25f8935e6258e18b0ec.json`
relative to the candidate profile. Capture and verify both the originals and
this absence state again before activation.

## Proposed authorized actions

1. Confirm one named default render endpoint, its GUID, existing Equalizer APO
   attachment, x64 host, stereo float32 shared mode and supported sample rate.
   Compare the reported endpoint to the existing leaf's Device GUID. Confirm
   the actual selected YASB config and build and pause its writer before
   taking the final exact backup. Stop if the attachment or profile differs
   from the approved trial. Adding an attachment would require its own scope.
2. Place the exact DLL and notices in
   `C:\Program Files\EqualizerAPO\VSTPlugins\YASBMediaDSP-386112c60e9c4364`.
   Use the existing ACL inheritance and verify the copied digest. Keep the
   build receipt with the candidate. Check actual host read/execute and broker
   access during the trial.
3. Edit only `widgets.media_v2.options.popup.equalizer` in the confirmed
   profile. Keep `backend: equalizer_apo`, `apo.enabled: true`,
   `apo.manage_include: false` and current preamp settings. Set
   `apo.processor: native`, `apo.native_library` to the versioned DLL path,
   and `apo.native_sha256` to the digest above. Leave `config.txt` in place.
   The saved preset is Flat but the current static leaf contains the band
   values `[2, 4, 2, 0, 1, 2, 4, 2, 1, 2]` and −4 dB preamp. If approved
   as the initial state, seed `preset: Custom` and those `custom_bands`
   after reconfirming the leaf. Native Q=1 and GraphicEQ have different
   frequency responses even with the same band values. Start at a
   user-controlled safe level for the audition.
4. Start only the approved YASB build/profile. Its normal setup writes the
   native managed leaf and profile record at launch. Expect one endpoint-bound
   VST plugin chain with the matching bootstrap and an automatic static leaf
   backup. Verify the parent hash, endpoint, host identity, permissions and
   accepted/applied/settled revisions. An ordinary manual band edit remains
   a draft until Apply.
5. With explicit permission to play and capture a short controlled signal on
   that endpoint, verify left/right orientation, mono, swap, balance, manual
   Apply, bypass, compressor and adaptive processing by comparing baseline/on
   recordings and listening at a safe level. Check latency changes, negotiated
   sample rate, signal integrity and quiet recovery. Advancing callback
   counters are supporting control evidence. Roll back on unexpected routing,
   denied access, stuck latency, dropouts or failed signal checks.

## Rollback

Stop the trial writer first. Verify that the selected profile, file identities
and deployment directory still match the trial receipt. As the original
Windows user, verify each protected blob's digest, use
`ProtectedData.Unprotect(blob, null, CurrentUser)` and compare the resulting
bytes to the original SHA-256 before placing them. Restore the original profile
and static managed leaf from exact bytes via same-directory atomic replacement
with the recorded ACL and timestamp. The parent already includes the same
leaf. Restore the parent only if the trial changed it, leaving subsequent
unrelated edits for explicit reconciliation. Verify all original hashes with
YASB stopped. Restore original record/backup bytes when present. For paths
recorded as absent, remove only files created by this trial, after checking
their ownership and receipt.

The normal profile's initial preset may rewrite the restored leaf on restart.
Treat restart as a separate authorized action and compare the new leaf to the
baseline. If its initial Flat curve replaced the recovered bands, restoring the
previous effective curve requires an explicit Apply of the captured bands and
preamp, followed by another byte check. Rollback is recoverable with the static
leaf active even if Windows still holds the DLL open. Retire the versioned
folder only once the DLL is no longer in use and nothing references it.

While YASB is absent, a host reload can start with the bootstrap's initial
settings. The latest committed record is reconciled on YASB reconnect.
Endpoint attachment or service changes are outside this proposed trial.
