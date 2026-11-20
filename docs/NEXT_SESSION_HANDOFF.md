# Media V2 release handoff

## Current scope

The output-device name and the single-player Via badge center in their own fields. When several players are available, the selected player's caption aligns to the right before the arrow. Long captions shorten in place. The selector preserves literal ampersands and gives duplicate sessions distinct names. The title tooltip follows the active track, including the loading and empty states.

The popup keeps its staged entrance, tab transitions and animated preset changes. Dragging a band creates a draft until Apply. See the [user guide](../MEDIA_V2_GUIDE.md) for configuration and the [regression list](MEDIA_V2_UI_REGRESSIONS.md) for the interactions to repeat. The Windows release uses the normal YASB source, assets and tests layout.

## Release verification

Checked 20 November 2026 against base `0d01fb26`. The full x64 suite passed 2,796 cases and skipped one hardware check because `atiadlxx.dll` was unavailable. Ruff, compilation and strict Pyright passed. Freshly exporting all 60 widget definitions reproduced the release schema byte for byte. The standalone ZIP contained 252 verified files, including the project license. All 31 checked frozen modules matched source. Only the standalone build command ran.

| Synthetic popup benchmark | Title paint start, p95 | Event-loop delay after repeated opening, p95 | Two closed views, CPU (% of one core) | Checks passed |
| --- | ---: | ---: | ---: | ---: |
| Previous build | 15.20 ms | 1.25 ms | 8.39% | 45/45 |
| Candidate, first run | 14.95 ms | 163.42 ms | 9.69% | 44/45 |
| Candidate, repeat | 19.06 ms | 6.33 ms | 9.85% | 45/45 |
| Candidate, confirmation | 16.15 ms | 6.23 ms | 9.12% | 45/45 |

Each run covered 48 reopen cycles and ended with zero capture readers. The event-loop limit was 50 ms. The initial spike did not recur on either repeat and its cause remains open. In the separate Windows fixture the first popup surface paint started at 95.87 ms for the candidate and 99.83 ms for the preceding build. The two warm openings took 13.06 and 11.97 ms on the candidate, versus 11.69 and 10.51 ms previously. These are paint-start observations with synthetic media.

The packaged DAC caption centered at x=83 in a 167 px field in the default and custom themes, and x=104 in a 209 px field at 125% scale. The Windows fixture exercised the entrance, preset travel, selector, Audio and Lyrics transitions, and interrupted reopening. Teardown released all capture readers and lyric subscriptions. Windows showed a responsive bar from the final x64 executable with the existing user profile.

The scoped source is ready for commit. The first-run timing spike and the previously recorded Windows COM diagnostic `0x8001010d` remain observations to track. The live bar stayed responsive after that diagnostic. The build also repeated an existing cx_Freeze warning about a duplicated Quick Launch resource entry. Both entries had identical contents in the previous and current builds. Physical listening and compositor frame timing remain unmeasured. [Earlier Windows comparison](history/MEDIA_V2_REAL_USE_2026-11-19.md)
