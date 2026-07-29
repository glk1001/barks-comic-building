# Choosing cutoffs for the restored-vs-original compares

Both `just check-for-upscayl-errors` and `just compare-restored-orig` run
`scripts/compare_fanta_image_dirs.py` over the restored pages and their
originals. The cutoffs below were measured rather than guessed; this note
records how, so they can be re-derived when the restore pipeline changes.

Re-measure with `--calibrate`, which reports the per-page figure at a given
`--fuzz` without applying any cutoff:

```sh
uv run scripts/compare_fanta_image_dirs.py --volume 1 --calibrate --fuzz 50%
uv run scripts/compare_fanta_image_dirs.py --volume 1 --calibrate --fuzz 50% \
    --tile-size 256 --diff-dir /tmp/tilecalib
```

## What the comparison is actually measuring

Restoring a page is *meant* to change it: the halftone screen is removed, the
palette is snapped, edges are smoothed. So the difference between a restored
page and its original is mostly legitimate, and the cutoff has to separate an
upscayl error from a restoration that worked. That turns out to be the hard
part, and it is what decides which metric is usable.

## Measurements (volume 1, 254 pages, fuzz 50%, July 2026)

| metric | median | p90 | p99 | max |
| --- | --- | --- | --- | --- |
| whole-page AE | 157 px | 303 px | 461 px | 3896 px |
| worst tile, 256 px tiles | 0.026% | 0.053% | 0.131% | 1.715% |

Both metrics put the same page top: `557.png`. Inspecting it shows the
difference is entirely legitimate - the halftone has been descreened and the
panel edges redrawn. It is the *best* case for the restore, not a defect.

Against that, localised artefacts injected into a known-clean page (`110.png`)
to stand in for upscayl damage:

| injected defect | whole-page AE | worst tile |
| --- | --- | --- |
| none | 219 px | 0.04% |
| 150x150 garbled | 974 px | 0.77% |
| 300x300 garbled | 2116 px | 2.27% |
| 450x450 garbled | 2425 px | 2.35% |
| 300x300 noise | 38729 px | 24.08% |
| 300x300 solid | 19819 px | 19.99% |

## Why the upscayl check is regional and not whole-page

Compare the legitimate outlier against a real defect:

- Whole-page AE ranks them **inverted**: the correctly restored page scores
  3896 while a page with a 450x450 garbled blob scores 2425. No cutoff can
  separate them, because the defect sits *below* the legitimate change. This
  is not a matter of picking a better number - the metric averages a local
  fault away over 6.5 million pixels, and cannot do this job at all.
- Worst-tile ranks them correctly: 1.715% legitimate against 2.27-2.35% for
  the defects.

So `check-for-upscayl-errors` uses `--tile-size 256 --tile-cutoff-pct 0.5`.

The margin between legitimate and defective is only about 1.3x, so treat the
result as a shortlist to look at rather than a pass/fail gate. At 0.5% that is
roughly one page per volume; 0.2% gives about three.

## Why the old cutoffs flagged nothing

`check-for-upscayl-errors` used `--ae_cutoff 10000` and `compare-restored-orig`
used `5000`. Against the distribution above, both are far beyond anything a
page actually produces: **0 of 254 pages** exceed either. `compare-restored-orig`
is now `--ae_cutoff 1000`, which keeps 2.2x headroom over the p99 of 461 and
flags one page per volume.

## Caveats

Measured on volume 1 only, whose scans are Salem-Empire. Other volumes are
different sources and may sit elsewhere; re-run `--calibrate` before trusting
these numbers on a volume that behaves oddly.

The injected defects are a stand-in for upscayl damage, not samples of it. If a
genuine upscayl error turns up, measure it and record it here - one real
example is worth more than the synthetic ones.
