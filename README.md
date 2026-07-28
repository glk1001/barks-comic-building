# barks-comic-building

Build pipeline for a digital library of Carl Barks' comics from Fantagraphics' *The Complete
Carl Barks Disney Library*. It upscales, restores and assembles the scanned volumes into clean
`.cbz` archives, and produces the image files consumed by
[`barks-compleat-reader`](../barks-compleat-reader).

Everything runs from a comics database that knows the volumes, the stories in them, and which
pages belong to each story. Per-comic `.ini` files define page order and page types (cover,
splash, body, and so on).

---

## Requirements

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** for dependency management
- **[just](https://github.com/casey/just)** for the shortcut recipes (optional)
- **[gmic](https://gmic.eu/)** on `PATH` — used by the restore pipeline for smoothing,
  inpainting and compositing
- An upscaler:
  - **waifu2x-ncnn-vulkan** in `~/.local/share/waifu2x-ncnn-vulkan/` (the default), or
  - **Upscayl** in `~/.local/share/upscayl/`
- A **Vulkan-capable GPU**. Both upscalers are ncnn/Vulkan based; without one they fall back to
  software rendering and run roughly five times slower.
- The Fantagraphics source scans, laid out as described under
  [Directory layout](#directory-layout).

## Installation

```bash
uv sync
```

Three packages come from `barks-compleat-reader` as editable path dependencies, declared under
`[tool.uv.sources]`, so no `PYTHONPATH` is needed:

| package | role |
|---|---|
| `barks_fantagraphics` | comics database, titles, pages, metadata |
| `barks_build_comic_images` | image building utilities |
| `comic_utils` | shared low-level utilities (image I/O, CLI options) |

Re-run `uv sync` after any change to `pyproject.toml`.

---

## The pipeline

Three stages, run in order. Each reads one directory under the library root and writes another.

```
Fantagraphics-original/          scanned pages (jpg)
        |
        |  1. upscale            barks-batch-upscayl
        v
Fantagraphics-upscayled/         4x pages (png)
        |
        |  2. restore            barks-batch-restore
        v
Fantagraphics-restored/          restored pages, back at source size
Fantagraphics-restored-upscayled/  restored pages at 4x
Fantagraphics-restored-svg/      vectorised line art
        |
        |  3. build              barks-build
        v
The Comics/                      .cbz archives
```

---

## 1. Upscale

```bash
uv run barks-batch-upscayl --volume 9
uv run barks-batch-upscayl --title "The Pixilated Parrot"
just upscayl 9
```

Enlarges every restorable page 4x into `Fantagraphics-upscayled/`. Pages whose destination
already exists are skipped, so an interrupted run resumes cheaply.

### Backends

Choose with `--upscaler`:

| backend | notes |
|---|---|
| **`waifu2x`** (default) | cunet model, denoise level 1. Roughly 90s per page. Leaves flat colour fills alone, which matters because Fantagraphics pages are flat colour under line art. |
| `upscayl` | `ultramix_balanced` model. Roughly 10 minutes per page, and it injects texture into flat fills. Kept for odd scales — waifu2x only handles 1, 2, 4, 8, 16 and 32. |

The backend that ran is recorded in each output page's PNG metadata.

### Gotchas

- **Upscayl's auto tile size is broken on Ubuntu 26.04.** The Vulkan submit fails with
  `VK_ERROR_DEVICE_LOST`, after which Upscayl writes an all-black image, prints
  "Upscayled Successfully!" and exits 0. `UPSCAYL_TILE_SIZE` in `restore/upscale_image.py`
  works around it. Tile sizes 32 to 144 are safe; 160 and above fail like auto does.
- **Keep upscaling runs sequential.** Two jobs sharing one GPU trigger the same failure at any
  tile size.
- Because a broken run still exits 0, every result is checked against its source — the output
  must be source size x scale, and coarse thumbnails of the two must stay within a mean
  deviation of 25. A rejected file is deleted so a re-run retries it rather than skipping.

---

## 2. Restore

```bash
uv run barks-batch-restore --work-dir /path/to/workdir --volume 9
just restore 9          # uses the work dir configured in the justfile
```

The restore exists to deal with the line art. The Fantagraphics scans are ~300 DPI, where Barks'
finer pen lines land on one or two pixels, so they arrive jagged, and JPEG ringing leaves a dirty
halo along every stroke. Filtering cannot recover geometry that has been quantised to a pixel
grid, so instead the line art is **separated, vectorised and re-composited**, which lets it be
redrawn at any resolution.

### What it does to a page

1. **Remove JPEG artifacts** — masked median filter over the upscaled page.
2. **Remove colours** — posterise and isolate the black ink, giving an ink mask.
3. **Smooth** — gmic anisotropic smoothing of that mask, then a soft threshold back to binary.
4. **Vectorise** — vtracer traces the smoothed mask to SVG, and it is rasterised back at 4x.
5. **Inpaint** — the ink is lifted out of the colour layer and the gap filled, leaving flat
   colour only.
6. **Palette snap** — the flat areas are snapped back to the exact colours the source page was
   drawn with (see below).
7. **Overlay** — the vector ink is composited back over the colour layer.
8. **Resize** — the result is reduced from 4x back to source size.

Outputs land in `Fantagraphics-restored/` (source size), `Fantagraphics-restored-upscayled/`
(4x) and `Fantagraphics-restored-svg/` (the traced line art).

### Palette snapping

The source jpgs hold their flat colours almost exactly — around 90% of flat pixels sit on a
palette of about ten colours, with the JPEG noise crowded into a halo along the ink. Upscaling
loses that (down to 24% for waifu2x, 5% for upscayl) because the models put texture into fills
that had none.

Those colours are recoverable, so rather than filtering the drift away it is replaced with what
the page started with. Only pixels both in a flat region and already close to a palette colour
are touched, leaving anti-aliased edges alone. On volume 9 page 110 this took the inpainted
layer from 27% of its flat pixels exactly on palette to 97%, and shrank the file from 39MB to
17MB.

It runs after inpainting, where the ink has been lifted out and no line edges need protecting.
Disable it with `RestorePipeline(..., do_palette_snap=False)` — there is no CLI flag.

Note the ink colour is **not** the same across the library: volumes 5 to 20 have it as a dark
grey around `(35, 29, 29)`, the rest as pure black, and some volumes hold pages of both. Anything
keying off it must work it out per page. `barks-ink-survey` reports what is actually there.

### Tuning

| knob | where | effect |
|---|---|---|
| `SMOOTH_THRESHOLD` | `restore/smooth_image.py` | Weight of the line art. Smoothing puts weight on; lowering this takes it off. 100 came out 1.3% heavier than the source page, 60 lands within 0.2%, 30 sits a little under and keeps the most separation between fine hatching strokes. |
| `do_palette_snap` | `RestorePipeline` | Whether flat colours are snapped back to the source palette. |
| `UPSCAYL_TILE_SIZE` | `restore/upscale_image.py` | Works around the black-image failure described above. |

### Running and resuming

Work runs in four phases across all pages, each phase finishing before the next starts. The
memory-hungry phases are throttled — smoothing to 6 workers, inpaint/snap/overlay/resize to 5,
and both to 1 on machines with under 16GB.

`--use-existing-work-files` resumes from whatever intermediates survive in the work dir. One
trap: the resize step regenerates the SVG raster at source size as its last act, so **re-running
only the final phase against a completed run overlays a 1x ink layer onto a 4x colour layer** and
silently produces a page with almost no ink. Run the SVG phase first when resuming mid-pipeline.

### Related commands

```bash
uv run barks-single-restore SRCE UPSCALED DEST DEST_4X DEST_SVG   # one page
uv run barks-batch-panel-bounds --work-dir DIR --volume 9         # panel geometry
uv run barks-ink-survey --volume 9-11                             # ink/paper colours
```

---

## 3. Build

```bash
uv run barks-build --volume 9
uv run barks-build --title "The Pixilated Parrot"
just build-volume 9
just build-title "the pixilated parrot"
```

Assembles finished comics into `.cbz` archives under `The Comics/`. For each story it picks the
best available version of every page — the restored page where one exists, otherwise a manually
fixed or added page, otherwise the original scan — applies the page order and types from the
comic's `.ini`, adds metadata, and zips the result.

Alongside the chronological archives it generates symlinked views by series and by year, so the
library can be browsed either way.

### Checking a build

```bash
uv run barks-check-build --volume 9
uv run barks-check-build --title "The Pixilated Parrot"
uv run barks-check-build --fix-names
just check-volume 9
```

Verifies previously built comics and can repair artifact names, which follow the pattern
`NNN <title> [<ISSUE>].cbz`.

---

## Directory layout

Everything lives under the Barks library root (`$HOME/Books/Carl Barks` in the justfile). Each
directory holds one folder per volume, named for the volume and its source release, with an
`images/` subfolder inside.

```
Carl Barks/
├── Fantagraphics-original/                      scanned pages (jpg)
│   └── Carl Barks Vol. 9 - Donald Duck - The Pixilated Parrot (Digital-Empire)/
│       └── images/
│           ├── 001.jpg
│           └── 002.jpg
├── Fantagraphics-upscayled/                     4x pages (png)
├── Fantagraphics-restored/                      restored, at source size
├── Fantagraphics-restored-upscayled/            restored, at 4x
├── Fantagraphics-restored-svg/                  vectorised line art
├── Fantagraphics-restored-ocr/                  OCR text
├── Fantagraphics-restored-panel-segments/       panel geometry
├── Fantagraphics-fixes-and-additions/           manually corrected or added pages
└── Fantagraphics-upscayled-fixes-and-additions/ upscaled versions of those fixes
```

The volume folder names carry the source release group — `(Salem-Empire)`, `(Digital-Empire)`
or `(Bean-Empire)` — which is worth knowing, as it correlates with the ink colour difference
noted above.

---

## Package layout

All live code is in `src/barks_comic_building/`, an installable hatchling package. Entry points
are registered under `[project.scripts]` in `pyproject.toml`.

| subpackage | entry points | role |
|---|---|---|
| `query/` | 20 | querying and browsing comic metadata |
| `build/` | 4 | comic assembly into `.cbz` |
| `restore/` | 8 | restoration and upscaling |

Shared bits:

- `log_setup.py` — loguru globals used by every CLI script
- `resources/log-config.yaml` — central log config

The old flat directories (`barks-cmds/`, `build-comics/`, `barks-restore/`) are dead code, and
are excluded from linting and type checking.

---

## Development

```bash
uv run ruff check .        # lint
uv run ruff format .       # format
uv run ty check            # type check
```

Python 3.13+ syntax, type hints on all function signatures (`str | None`, not `Optional[str]`),
Google-style docstrings on public functions. Line length 100, configured in `.ruff.toml`; type
checker config in `ty.toml`. A pre-commit hook runs ruff, ty and cspell over changed files and
over the commit message — new project words go in `cspell-words.txt`.

Run `just` on its own to list every recipe.

---

## License

GPL. Intended for personal, non-commercial use in managing a legally owned collection. Please
respect all copyright laws.
