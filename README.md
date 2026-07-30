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

Run in order. Each stage reads one directory under the library root and writes another.

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
        |  +  panel bounds       barks-batch-panel-bounds
        v
Fantagraphics-restored-panel-segments/  panel geometry (json)
        |
        |  3. build              barks-build
        v
The Comics/                      .cbz archives
```

Panel bounds are a separate command rather than a fourth stage — they depend on the restored
pages but nothing depends on them until the build, so they can be run at any point in between.
A page can be fully restored and still not buildable without them.

---

## How one page becomes a comic page

The stages above are how the *library* is processed. This is the trail a **single page** leaves,
which is what the integrity check verifies and what you need in order to work out why a page is
wrong.

Take page 117 of volume 9. Every artifact for it keeps the same stem, `117`, in a different tree:

| Stage | Command | Writes | Note |
|---|---|---|---|
| — | *(the scan)* | `Fantagraphics-original/…/images/117.jpg` | read-only |
| 1 | `barks-batch-upscayl` | `Fantagraphics-upscayled/…/images/117.png` | 4x |
| 2 | `barks-batch-restore` | `Fantagraphics-restored/…/images/117.png` | source size |
| | | `Fantagraphics-restored-upscayled/…/images/117.png` | 4x |
| | | `Fantagraphics-restored-svg/…/images/117.svg` + `117.svg.png` | traced ink |
| + | `barks-batch-panel-bounds` | `Fantagraphics-restored-panel-segments/…/117.json` | panel geometry |
| 3 | `barks-build` | `The Comics/…/<title>/images/<dest page>.jpg` | then zipped to `.cbz` |

Two things about that table are easy to miss. Panel bounds are computed from the **restored** page,
not the scan — so re-restoring a page leaves its panel bounds stale. And unlike every image tree,
the panel-segments volume folder has no `images/` level inside it; the json sits directly in the
volume folder.

At the build the page is not simply the restored file. For each page of the story, in the order the
comic's `.ini` gives, the build resolves *one* source file:

- **`BODY`, `FRONT_MATTER`, `BACK_MATTER`** — the restorable types — must have a restored file.
  If it is missing this is a **hard error**, not a fallback to the original scan. The one
  exception is a synthetic collection (below): a collection page that has not been restored yet
  falls back to its staged scan with a warning, so a half-restored collection still builds.
  `barks-check-build` reports every page that took that fallback, because the page it produces
  is a valid, up-to-date image and nothing else can tell it apart from a restored one.
- **Everything else** — `COVER`, `SPLASH`, paintings, back matter without panels — comes straight
  from the original scan (with the override below applied). These are never restored.
- **`TITLE`** is synthesised by the build itself, from the `.ini` and the title's inset image.
  **`BLANK_PAGE`** is an empty page. Neither has a source scan.
- Two titles, **"Good Deeds"** and **"Silent Night"**, were restored by hand and are exempt from
  the restored-file requirement.

### The override mechanism: fixes and additions

Any page can be replaced by hand. A file placed in the fixes tree under the same stem **takes
precedence over the original**, always:

```
Fantagraphics-original/…/images/117.jpg              the scan
Fantagraphics-fixes-and-additions/…/images/117.jpg   wins if present
```

There is no flag or list to update — presence in the fixes tree *is* the override. Which of two
things it means depends on whether the original exists:

| Original scan | Fixes file | Meaning | Recorded as |
|---|---|---|---|
| exists | — | ordinary page | `ORIGINAL` |
| exists | exists | the scan was **edited** — censorship fix, rescan, cleanup | `MODIFIED` |
| absent | exists | a page was **added** that the Fantagraphics volume never had | `ADDED` |

An **added** page has to be numbered outside the volume's real page range: either in the
extra-pages band (`num_fanta_pages + 1` up to `300`) or in a staged collection's range, and it
must be referenced by one of the volume's `.ini` files. An edited page must be a story page type.
The `bounded/` subdirectory inside the fixes images dir is not a page at all — it holds
hand-drawn panel-bounds overrides that `barks-batch-panel-bounds` reads.

### Upscayled fixes and additions

The same override exists one stage later, for when the *upscale* is what needs replacing rather
than the scan:

```
Fantagraphics-upscayled-fixes-and-additions/…/images/117.png
```

Four rules differ from the plain fixes tree, and all four are enforced rather than documented
only:

- **`.png` only.** A `.jpg` there raises rather than being used — the upscale output is png.
- **An upscayled fix replaces the upscayled output.** Having both a fix and a real upscale for one
  page raises, because which of the two wins would be undefined.
- **A page must not be fixed in both fixes trees.** A page held in the plain *and* the upscayled
  fixes tree is reported by `barks-check-build` for the same reason.
- **No added-pages band.** A page here with no original scan behind it is only allowed where the
  database explicitly records one as added.

### Special cases: one-pagers and covers

"All One-Pagers" and "All Covers" are not scanned books. Each is a synthetic collection assembled
out of pages that live in *other* volumes, by symlinking them into a collection volume before the
normal pipeline runs:

```bash
uv run barks-stage-one-pagers      # then upscayl / restore / panel-bounds / build as usual
uv run barks-stage-covers
uv run barks-stage-covers --remove # clean up
```

Each located member is staged as collection page **`500 + its index`** in table order
(`ONE_PAGER_LOCATIONS`, `COVER_LOCATIONS`), which is the thing to be careful about: **inserting a
member shifts every later member's page**. Skip the restage and the links stay attached to the old
numbers, so the built cbz shows members under each other's pages — with no file missing and no
timestamp out of date. `barks-check-build` checks the staged links against the location tables for
exactly this reason.

The two collections stage different amounts of work, and the reason is the page type:

- **One-pagers are `BODY` pages**, so they are restorable and the whole chain applies. Six
  artifacts are staged per member: the scan, the upscale, the restored page, the `.svg` and
  `.svg.png` pair, and the panel segments.
- **Covers are `COVER` pages**, so they are built full-page — scaled with black bars, never
  cropped to panels and never restored. Only two artifacts are worth staging: the scan and the
  upscale.

Both stage the original scan into the collection volume's **fixes** tree rather than its
read-only original tree, so no permission changes are needed. That also means every collection
page is an *added* page by the rule above, which is why the added-page band accepts a staged
collection's range.

### What the integrity check verifies

`barks-check-build` walks the same trail backwards. Per page it checks each artifact exists and
that timestamps **decrease** along the chain — panel segments, restored, restored-upscayled,
restored-svg, upscayled, original — because each stage is produced *from* the next. A stage newer
than the thing derived from it means that thing needs remaking:

```
ERROR: File "Fantagraphics-restored-upscayled/…/117.png"
       is out of date with
       file "Fantagraphics-restored-svg/…/117.svg":
       '2026-07-29 03:02:31.65' < '2026-07-30 02:59:59.82'
```

read as: the `.svg` was re-traced after the upscayled page was built from it, so re-run the
restore for that page.

"Decrease" is not strict: equal timestamps pass, and there is no tolerance either way.

**How much of the chain applies depends on the page.** The full six-stage walk is for an ordinary
restorable page. For an *added* page — the hard-coded special cases, every synthetic-collection
page, and a censored title's `BODY` pages — there is no upscayl or original scan behind it, so the
chain stops at the restored file and the four earlier stages are not checked. `BLANK_PAGE` has no
chain at all, and `TITLE` is dated by its inset alone, the `.ini` being hash-checked instead. Only
"Good Deeds" and "Silent Night" are exempt from needing a restored file at all; they were restored
by hand.

It also checks the two things a consistent chain cannot show, because in both cases every file is
present and every timestamp along the chain agrees:

- **A restorable page whose source came from outside the restored tree** — the collection fallback
  above. The only trace is which tree the file was in.
- **Panel segments older than the hand-drawn `bounded/` override they were computed from.** The
  segments depend on both the override and the restored page, so this is a fork in the chain
  rather than a link in it, and it is graded separately.

Two things are deliberately **not** timestamp-checked. The `.ini` file is compared by **content
hash** against the hash recorded in the comic's metadata at build time, because the `.ini` files
are git-tracked in another repository and a checkout rewrites every mtime without changing a byte.
And an `.ini` whose metadata records no hash at all is reported, since the hash is that file's
only check.

Beyond the per-page trail it also checks that the original tree is still read-only, that the
directory structure is complete, that no unexpected file has appeared in any namespace it owns,
that every `.ini` title is one `SERIES_INFO` knows, and — for the synthetic collections — that
every staged link points at the source its location table says it should. `--no-check-symlinks`
and `--no-check-for-unexpected-files` switch off the last two groups.

### What it does not cover

Worth knowing, because a clean run does not mean all of these are true:

- **Recipe currency.** The check compares mtimes; it never reads a recipe id. A page restored or
  upscayled under an obsolete recipe, with a consistent chain, passes clean. Staleness against the
  *current* recipe is `barks-restore-status` and `barks-upscale-status`, not this.
- **Image content.** No image is ever opened — no dimensions, no pixels. The all-black Upscayl
  failure is caught by the upscale's own guard and by `just check-for-upscayl-errors`; see
  [docs/image-compare-cutoffs.md](docs/image-compare-cutoffs.md).
- **cbz contents.** The archive is graded on existence and its own mtime. Its member list is
  never compared against the dest images.
- **A page-level error stops that title.** A `.jpg` in a fixes tree, a missing restored file, or a
  fix competing with a real upscale raises, and the run records that one error and abandons the
  rest of the title. Its zip, symlink and info-file verdicts are then *unknown*, not clean — fix
  the file it names and re-run before trusting the title.
- **A `SERIES_INFO` title with no `.ini`** is not reported. The `.ini` files are written per story
  as each is worked on, so the difference is outstanding work, not an inconsistency.

---

## 1. Upscale

```bash
uv run barks-batch-upscayl --volume 9
uv run barks-batch-upscayl --title "The Pixilated Parrot"
just upscayl 9
```

Enlarges every restorable page 4x into `Fantagraphics-upscayled/`.

### Backends

Choose with `--upscaler`:

| backend | notes |
|---|---|
| **`waifu2x`** (default) | cunet model, denoise level 1. Roughly 90s per page. Leaves flat colour fills alone, which matters because Fantagraphics pages are flat colour under line art. |
| `upscayl` | `ultramix_balanced` model. Roughly 10 minutes per page, and it injects texture into flat fills. Kept for odd scales — waifu2x only handles 1, 2, 4, 8, 16 and 32. |

### Knowing what is left to do

The upscale keeps the same provenance the restore does, for the same reason: which backend and
settings made a page is not recoverable from the page.

Each output PNG carries the **upscale recipe** — backend, scale, model, and the denoise level or
tile size — expanded as JSON beside a short `Upscale recipe id`, plus the date. **A page is
skipped only when its recipe id matches the current one**, so changing `WAIFU2X_NOISE_LEVEL`, the
model or the backend schedules the pages made under the old value without anything being deleted
by hand. `--force` redoes pages that are already current. As with the restore, recipe staleness is
`barks-upscale-status`'s answer, not `barks-check-build`'s.

Settings belonging to the backend *not* in use are held at a sentinel, so tuning Upscayl does not
invalidate pages made with waifu2x or the other way round.

```bash
uv run barks-upscale-status --volume 1-29     # per-volume table with an ETA
uv run barks-upscale-status --failed          # pages that failed, and why
uv run barks-upscale-status --json            # for scripting
just upscale-status 9
```

```
Vol  Title                         Pages  Current  Stale  Missing  Linked  No srce  Est. left
  1  Donald Duck - Finds Pirate…     283             146       31     106                  --
  2  Donald Duck - Frozen Gold       210             210                                   --
```

Note the report is **per backend**, because the recipe is: asking about waifu2x while a volume
was made with Upscayl shows it as stale, which is the answer rather than a fault in the question.

`Linked` pages are symlinks to another volume's page — collection titles borrow them, and volume
1 carries over a hundred. They are upscayled as part of the volume they point at, and are never
written here: doing so would follow the link and replace that volume's page from a different
source image.

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
- A failed page is recorded and the run carries on, since one bad page should not cost the rest
  of a run measured in hours. But five failures **in a row** stop it: a GPU that has stopped
  producing usable images fails every page the same way, and grinding through a volume to
  record a thousand identical rejections helps nobody.

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
| `--batch-size` | `barks-batch-restore` | Pages per phase batch. Larger keeps the throttled phases fuller; smaller bounds the work dir and the loss from an interrupted run. |

Everything in that table except `UPSCAYL_TILE_SIZE` and `--batch-size` is part of the
**restore recipe** in `restore/restore_recipe.py`, alongside the gmic smoothing and inpainting
parameters, the vtracer settings and the palette-snap thresholds. Changing any of them changes
the recipe id, which is what marks existing pages as stale and schedules them to be redone —
so tune deliberately, and check `barks-restore-status` before starting a long run.

### Running and resuming

Work runs in four phases over a batch of pages, each phase finishing before the next starts.
The memory-hungry phases are throttled — smoothing to 6 workers, inpaint/snap/overlay/resize
to 4, and both to 1 on machines with under 16GB.

Pages are batched **across** titles, `--batch-size` at a time (default 64), because a title is
only 8–14 pages and a 6-worker phase given 8 pages spends half its time running a half-empty
round. Each batch is a checkpoint: its ledger records are flushed and its work files cleaned
before the next starts, so an interrupted run loses at most one batch of unfinished work.

Work files are deleted once a page succeeds; `--keep-work-files` leaves them. Pages that
**fail** keep theirs, so a retry can resume from them. `--use-existing-work-files` reuses
whatever survives.

### Stopping a run

A run is days long and spread over a pool of worker processes, each driving gmic
subprocesses that take minutes. Interrupting that from the terminal kills the whole
process group at once and leaves half-written intermediates behind, so instead a stop is
**asked for** by writing a file into the work dir. Any terminal can write it, the run does
not have to be in the foreground, and the workers see it directly — a flag set in the
parent would never reach them.

```bash
just restore-stop         # let pages already under way finish, start nothing new
just restore-stop-now     # or: finish the current step only, sooner
just restore-stop-cancel  # changed your mind
```

Two levels, because what a clean stop costs depends on where the run has got to:

| | what finishes | pages left |
|---|---|---|
| `restore-stop` | every remaining step of pages already started | complete and recorded |
| `restore-stop-now` | only the step each worker is in | part-done, resume next run |

**How long `restore-stop` takes depends entirely on when you ask.** Part 1 is quick and
runs sixteen at a time, so within a few minutes of a batch starting, every page in it
counts as started — and a graceful stop then has to see the whole batch through. At the
default batch size of 64 that is up to about five hours. Ask during part 1 and only the
pages that had begun are carried, which is more like an hour.

So `restore-stop` is the one to use when you want the work banked and can leave it
running; `restore-stop-now` is the one to use when you want the machine back, and it
costs about ten minutes whenever you ask. If you expect to interrupt often, a smaller
`--batch-size` shrinks the graceful stop's worst case in proportion.

**Asking twice escalates** from the first to the second, so you can decide to stop, then
decide you meant sooner, without remembering a flag. It never goes the other way — a
gentle ask after an urgent one leaves the urgent one in force.

Nothing is ever cut mid-step, so every intermediate left on disk is a whole file. Pages
that were part way through keep their work files and are picked up by the next run with
`--use-existing-work-files`; pages the stop reached before they had begun were never
touched at all. Re-running the same command carries on — finished pages are skipped by
the recipe check.

For an unattended run that has to be over by morning:

```bash
uv run barks-batch-restore --work-dir DIR --volume 1-29 --stop-after 8h
```

`--stop-after` accepts `8h`, `90m`, `1h30m`. It asks for the same graceful stop rather
than being a second mechanism, and it is checked as pages come back — so with a long
phase in progress it can overshoot by up to the length of one step, around ten minutes.
A leftover stop request is cleared when a run starts, so it can never stop the next one
before it has done anything.

### Tracking a long run

Restoring the library is 5,500 pages and several hundred hours, so the pipeline records what
it did. Two places, for two different failure modes:

- **In each restored PNG** — the settings it was made with, expanded as JSON plus a short
  `Restore recipe id`, and the date. Travels with the file; readable with `exiftool` or
  `restore.image_io.read_png_metadata`.
- **In `restore-ledger.jsonl`** (a sibling of the stage directories, so the integrity
  checks don't walk it) — one line per run carrying the full recipe, then one per page
  carrying its outcome, per-step timings and the step it failed at. Append-only and
  flushed per page, so it survives a hard kill. The upscale keeps its own alongside it, in
  `upscale-ledger.jsonl`.

  A page's outcome is `ok`, `failed`, `copied` (a non-comic page passed through unrestored)
  or `present` (already there, so this run did nothing to it). Only `ok` pages count towards
  the timings — a file copy takes a fraction of a second where a restore takes minutes, and
  letting those in would shorten every estimate built afterwards.

```python
from barks_comic_building.restore.restore_ledger import read_ledger

ledger = read_ledger()  # defaults to the path above
stats = ledger.timing_stats()  # mean/median seconds per page
ledger.recipe_for(ledger.pages[-1].recipe_id)  # the actual settings, not just a digest
```

**A page is skipped only when all three of its outputs exist and its recipe id matches the
current one.** That is what makes a re-run after a tuning change automatic — change
`SMOOTH_THRESHOLD`, and every page made under the old value reports as stale and gets redone,
with nothing deleted by hand. It also catches pages missing their 4x or SVG output, which the
old existence check skipped permanently. `--force` redoes pages that are already current.

This is the one kind of staleness `barks-check-build` does not see — it compares mtimes and never
reads a recipe id, so `barks-restore-status` is what answers "is this page on the current recipe".

The exception is a page whose outputs are **symlinks to another volume's**, which collection
titles use to borrow pages. Those are reported as `linked` and never written, here or by the
upscale — following the link would replace that volume's page from a different source image.
`--force` does not override it.

```bash
uv run barks-restore-status --volume 1-29    # per-volume table with an ETA
uv run barks-restore-status --steps          # where the time goes, per pipeline step
uv run barks-restore-status --failed         # pages that failed, and where
uv run barks-restore-status --json           # for scripting
just restore-status
```

```
Vol  Title                         Pages  Current  Stale  Incomplete  Missing  Linked  No srce  Est. left
  9  Donald Duck - The Pixilated…    192      192                                                      --
 10  Donald Duck - Terror of the…    194             194                                           14h09m
  1  Donald Duck - Finds Pirate…     283             145                          107       31     10h57m
```

The estimate comes from pages already measured on the current recipe, so it is empty until a
batch has run and sharpens as the run goes on.

Measured over volume 9, a page costs about **272s of wall clock**, spent roughly:

| step | mean s | share |
|---|---:|---:|
| smooth (gmic) | 621 | 48% |
| inpaint (gmic) | 421 | 33% |
| remove jpeg artifacts (numba) | 119 | 9% |
| palette snap | 54 | 4% |
| everything else | 72 | 6% |

Those are per-page means under contention, so they add up to far more than the 272s of wall
clock a page actually costs — several pages are in each step at once. They rank the steps;
they do not sum to the total. The work dir holds about **155MB per page** until cleanup, so a
64-page batch peaks near 10GB.

### Related commands

```bash
uv run barks-single-restore SRCE UPSCALED DEST DEST_4X DEST_SVG   # one page
uv run barks-batch-panel-bounds --work-dir DIR --volume 9         # panel geometry
uv run barks-ink-survey --volume 9-11                             # ink/paper colours
uv run scripts/bench_restore_phases.py --work-file WORK.png       # tune worker counts
```

---

## 3. Build

```bash
uv run barks-build --volume 9
uv run barks-build --title "The Pixilated Parrot"
just build-volume 9
just build-title "the pixilated parrot"
```

Assembles finished comics into `.cbz` archives under `The Comics/`. For each story it takes the
page order and types from the comic's `.ini`, resolves one source file per page, renders it onto
the destination page, adds metadata, and zips the result.

Which source file depends on the page type — the restorable types require a restored page, the
rest come from the original scan with any hand fix applied over it. See
[How one page becomes a comic page](#how-one-page-becomes-a-comic-page) for the full resolution
order and the override rules.

Alongside the chronological archives it generates symlinked views by series and by year, so the
library can be browsed either way.

### Checking a build

```bash
uv run barks-check-build --volume 9
uv run barks-check-build --title "The Pixilated Parrot"
uv run barks-check-build --fix-names --apply
just check-volume 9
```

Verifies previously built comics — see
[What the integrity check verifies](#what-the-integrity-check-verifies) for what that covers and
what it does not.

`--fix-names` is a **separate mode, not an extra**: it repairs artifact names, which follow the
pattern `NNN <title> [<ISSUE>].cbz`, and runs *instead of* the verification rather than alongside
it. Bare `--fix-names` is a dry run that prints the plan, changes nothing and exits 1; `--apply`
performs it. Because the renames have to form a whole-namespace permutation, it rejects `--volume`
and `--title`.

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
├── Fantagraphics-restored-ocr/                  OCR text (not a pipeline stage)
├── Fantagraphics-restored-panel-segments/       panel geometry
├── Fantagraphics-fixes-and-additions/           manually corrected or added pages
├── Fantagraphics-upscayled-fixes-and-additions/ upscaled versions of those fixes
├── Fantagraphics-fixes-and-additions-scraps/    holding area for fix material; per volume it
│                                                has images/standard, /upscayled and /restored
├── upscale-ledger.jsonl                         what each upscale run did
└── restore-ledger.jsonl                         what each restore run did
```

`barks-check-build` requires every one of these per-volume directories to exist, including the
scraps tree and the OCR tree. `Fantagraphics-restored-ocr/` is otherwise outside everything above:
no pipeline stage writes it, nothing in the build reads it, and it is not part of the dependency
chain.

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
| `restore/` | 11 | restoration and upscaling |

Shared bits:

- `log_setup.py` — loguru globals used by every CLI script
- `resources/log-config.yaml` — central log config

Three directories sit outside the package: `scripts/` holds standalone helper scripts (directory
comparisons, image diffs, the cspell hook) and is type checked; `docs/` holds notes too long for
this file, currently how the image-comparison cutoffs were measured; and `scraps/` is a holding
pen for unfinished work, excluded from both ruff and ty.

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

Licensed under the [Apache License, Version 2.0](LICENCE).

The licence covers this project's own source code. The Carl Barks comics themselves — the
artwork, characters and story text — are the copyright of their respective owners and are
not covered by it; see [NOTICE](NOTICE). Intended for personal, non-commercial use with a
legally owned collection.
