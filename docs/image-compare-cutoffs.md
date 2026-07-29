# Choosing cutoffs for the restored-vs-original compares

Both `just check-for-upscayl-errors` and `just compare-restored-orig` run
`scripts/compare_fanta_image_dirs.py` over the restored pages and their
originals. The cutoffs below were measured rather than guessed; this note
records how, so they can be re-derived when the restore pipeline changes.

Re-measure with `--calibrate`, which reports the per-page figure at a given
`--fuzz` without applying any cutoff:

```sh
uv run scripts/compare_fanta_image_dirs.py --volume 2,12,29 --calibrate \
    --fuzz 20% --tile-size 512 --diff-dir /tmp/tilecalib
```

## What the comparison is actually measuring

Restoring a page is *meant* to change it: the halftone screen is removed, the
palette is snapped, edges are smoothed and thinned. So the difference between a
restored page and its original is mostly legitimate, and the cutoff has to
separate an upscale fault from a restoration that worked. That is the hard part,
and it is what decides both the metric and its parameters.

## The fuzz and tile size came from a sweep

`--fuzz` was swept over 5%, 10%, 15% and 20% across volumes 2, 12 and 29 in
June 2026, and 20% chosen. Regional comparison was then added and `--tile-size
512` settled on over the same volumes plus per-title spot checks. Those two
parameters are the result of that sweep - do not change one without re-running
it, because every figure below is quoted at fuzz 20% and 512 px tiles.

## Measurements (volumes 2, 12 and 29; 607 pages; fuzz 20%, tile 512)

| | median | p90 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- |
| worst tile | 0.767% | 1.135% | 1.336% | 1.803% | 3.539% |

What each cutoff would flag:

| `--tile-cutoff-pct` | pages flagged of 607 |
| --- | --- |
| 0.5 | 532 |
| 1 | 110 |
| **2** | **4** |
| 3 | 1 |
| 5 | 0 |

2% sits just above the p99 and yields a four-page shortlist, so that is what
`check-for-upscayl-errors` uses.

The scan source matters, and one cutoff across the library is a compromise:

| volume | source | n | median | max | over 2% |
| --- | --- | --- | --- | --- | --- |
| 2 | Salem-Empire | 212 | 0.538% | 1.201% | 0 |
| 12 | Digital-Empire | 215 | 0.929% | 3.539% | 3 |
| 29 | Salem-Empire | 180 | 0.813% | 2.147% | 1 |

Digital-Empire volumes run consistently hotter. Only one is in this sample; if
the shortlist gets long on a Digital-Empire volume, re-calibrate before assuming
the pages are bad.

## Why the check is regional and not whole-page

Localised artefacts injected into a known-clean page, to stand in for upscale
damage, measured at the same parameters:

| injected defect | worst tile | vs the 2% cutoff |
| --- | --- | --- |
| none | 0.656% | passes |
| 150x150 garbled | 1.472% | passes |
| 300x300 garbled | 5.621% | flagged |
| 450x450 garbled | 11.260% | flagged |
| 300x300 noise | 13.208% | flagged |

Against the p99 of 1.803% that is about 3.1x separation for a 300x300 fault. A
whole-page AE cutoff cannot do this at all: measured on volume 1, a correctly
restored page scored 3896 while a page carrying a 450x450 garbled blob scored
2425. The defect ranks *below* the legitimate change, because a local fault
averages away over 6.5 million pixels. No threshold fixes that.

Note the 150x150 fault escapes even the regional check. That is the floor.

`compare-restored-orig` keeps the whole-page metric, for gross change only, at
`--ae_cutoff 1000` - 2.2x above the volume-1 p99 of 461. It is not an
upscale-fault detector and should not be treated as one.

## Caveats

Calibrated 2026-07-29, after waifu2x became the default upscaler, after the
palette snap and after the line-art thinning. Any change to those steps moves
these numbers - re-run `--calibrate` rather than trusting the table.

An earlier calibration of the same parameters was made in June 2026 against the
pre-waifu2x pipeline and also arrived at 2%, so the figure has now survived one
pipeline change. That is reassuring, not a guarantee.

The injected defects are a stand-in for upscale damage, not samples of it. If a
genuine one turns up, measure it and record it here - one real example is worth
more than all the synthetic ones.
