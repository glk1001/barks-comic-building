import sys

import typer
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg

from barks_comic_building.build.comics_integrity import ComicsIntegrityChecker
from barks_comic_building.cli_setup import get_comic_titles, init_logging

APP_LOGGING_NAME = "cbld"

app = typer.Typer()


@app.command(help="Check the integrity of all previously built comics")
def main(  # noqa: PLR0913
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
    no_check_for_unexpected_files: bool = False,
    no_check_symlinks: bool = False,
    no_check_censorship_csv: bool = False,
    censorship_only: bool = False,
    fix_names: bool = False,
    apply: bool = False,
    check_panel_segment_image_size: bool = typer.Option(
        default=False,
        help="Also check each panel segments file's page size against the restored image"
        " (opens every restorable page, so it is slow).",
    ),
    no_check_slot_content: bool = typer.Option(
        default=False,
        help="Skip comparing the collections' real slot files with their members' scans"
        " (decodes every real upscale, about 30s). Only runs that include a collection"
        " - every title, --volume 1 or 2, or its --title - do it at all.",
    ),
) -> None:
    init_logging(APP_LOGGING_NAME, "check-build-comics-integrity.log", log_level_str)

    if apply and not fix_names:
        msg = "Option --apply does nothing without --fix-names."
        raise typer.BadParameter(msg)

    if censorship_only and no_check_censorship_csv:
        msg = "Options --censorship-only and --no-check-censorship-csv contradict each other."
        raise typer.BadParameter(msg)

    if censorship_only and (volumes_str or title_str or fix_names):
        # Each of these would otherwise be dropped without a word - and --fix-names would
        # look like a rename run that decided there was nothing to rename.
        msg = (
            "Option --censorship-only runs the whole-library censorship check on its own,"
            " so it cannot be combined with --volume, --title or --fix-names."
        )
        raise typer.BadParameter(msg)

    if censorship_only:
        # The censorship check is whole-library, so it takes no volume or title filter
        # and nothing else needs to run first. Kept separate so a recipe that only wants
        # this one does not quietly become a full build check once the tree is clean.
        checker = ComicsIntegrityChecker(
            ComicsDatabase(),
            no_check_for_unexpected_files=True,
            no_check_symlinks=True,
        )
        sys.exit(checker.check_censorship_fixes_csv())

    if fix_names and (volumes_str or title_str):
        # The renames form a permutation over the whole namespace. A filtered subset
        # is not a permutation: the artifact blocking a rename may sit outside the
        # filter, so the ordering could not be completed. Reject it up front rather
        # than failing obscurely half-way through.
        msg = (
            "Option --fix-names works on the whole tree, so it cannot be combined"
            " with --volume or --title."
        )
        raise typer.BadParameter(msg)

    if volumes_str or title_str:
        comics_database, titles = get_comic_titles(volumes_str, title_str)
    else:
        # No volume/title filter given: check every title. An empty title list is what
        # `check_comics_integrity` widens to every story title; `get_comic_titles`
        # cannot express that, since it asserts on an empty volume list.
        comics_database, titles = ComicsDatabase(), []

    integrity_checker = ComicsIntegrityChecker(
        comics_database,
        no_check_for_unexpected_files,
        no_check_symlinks,
        no_check_censorship_csv,
        check_panel_segment_image_size=check_panel_segment_image_size,
        check_slot_content=not no_check_slot_content,
    )
    exit_code = integrity_checker.check_comics_integrity(
        titles, fix_names=fix_names, apply_fixes=apply
    )

    if exit_code != 0:
        # A dry-run fix exits non-zero because the tree is still stale, but it found
        # no errors of its own - it already said what it would do, so do not follow
        # that with an error banner.
        if not (fix_names and not apply):
            print(f"\nThere were errors: exit code = {exit_code}.")  # noqa: T201
        sys.exit(exit_code)


if __name__ == "__main__":
    app()
