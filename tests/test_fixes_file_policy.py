"""Tests for what may sit in a fixes tree, and how original scans must be numbered.

Both checks used to be written twice - once for the standard fixes tree and once for
the upscayled one, around 160 lines of near-duplicate. Two copies of a rule drift, and
these had: the upscayled check tested whether the *standard* fixes directory existed
while naming the upscayled one in its message, so the upscayled tree's own existence was
never actually checked by the check that exists to check it.

The page-numbering half had a different failure. `int(file.stem)` was unguarded, so one
stray non-numeric filename anywhere in the originals raised a ValueError out of a
function whose contract is to return 0 or 1 - taking all thirty volumes with it. The
same line also incremented the expected page number before parsing, so a stray file
shifted the expectation for every page after it and corrupted the count.

The boundaries below are the part worth pinning: which page numbers an added fixes page
may use is a policy nobody can re-derive from the code at a glance.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from barks_fantagraphics.comic_book_info import (
    ONE_PAGER_COLLECTION_VOLUME,
    get_collection_page_nums,
)

from barks_comic_building.build.comics_integrity import (
    MAX_EXTRA_FIXES_PAGE_NUM,
    STANDARD_FIXES,
    UPSCAYLED_FIXES,
    AddedFixesFault,
    AddedPagePolicy,
    FixesFault,
    FixesFileFacts,
    FixesTreeSpec,
    check_contiguous_page_numbers,
    classify_fixes_file,
)

# A volume with 250 real scanned pages, so the ordinary extra-pages band is 251..300.
NUM_FANTA_PAGES = 250
FIRST_EXTRA_PAGE = NUM_FANTA_PAGES + 1

JPG = ".jpg"
PNG = ".png"

NO_COLLECTION_PAGES: frozenset[int] = frozenset()

# The page count of the small runs the numbering tests use.
THREE_PAGES = 3


def policy(
    *,
    collection_page_nums: frozenset[int] = NO_COLLECTION_PAGES,
    used: frozenset[str] = frozenset(),
) -> AddedPagePolicy:
    """Make an added-page policy for a 250-page volume.

    Args:
        collection_page_nums: Staged collection pages the volume may also hold.
        used: Page nums referenced by the volume's ini files.

    Returns:
        The policy.

    """
    return AddedPagePolicy(NUM_FANTA_PAGES, collection_page_nums, used)


def facts(
    *,
    is_note: bool = False,
    note_pair_present: bool = False,
    original_exists: bool = True,
    present_in_other_tree: bool = False,
    added_page_allowed: bool = False,
) -> FixesFileFacts:
    """Make one fixes file's filesystem facts, defaulting to an ordinary valid fix."""
    return FixesFileFacts(
        is_note=is_note,
        note_pair_present=note_pair_present,
        original_exists=original_exists,
        present_in_other_tree=present_in_other_tree,
        added_page_allowed=added_page_allowed,
    )


class TestTheAddedPageBand:
    """Which page numbers a fixes file with no original scan may use.

    A page inside the band is a real extra page appended past the end of a volume;
    anything below it should have had an original scan and does not.
    """

    def test_the_last_real_page_is_not_an_added_page(self) -> None:
        assert policy().classify(str(NUM_FANTA_PAGES)) is AddedFixesFault.OUT_OF_RANGE

    def test_the_page_after_the_last_real_one_opens_the_band(self) -> None:
        used = frozenset({str(FIRST_EXTRA_PAGE)})

        assert policy(used=used).classify(str(FIRST_EXTRA_PAGE)) is None

    def test_the_ceiling_page_is_still_in_the_band(self) -> None:
        used = frozenset({str(MAX_EXTRA_FIXES_PAGE_NUM)})

        assert policy(used=used).classify(str(MAX_EXTRA_FIXES_PAGE_NUM)) is None

    def test_the_page_after_the_ceiling_is_out(self) -> None:
        over = str(MAX_EXTRA_FIXES_PAGE_NUM + 1)

        assert policy().classify(over) is AddedFixesFault.OUT_OF_RANGE

    def test_a_page_in_the_band_must_still_be_used_by_an_ini(self) -> None:
        # In range but referenced by nothing: a fix for a page no comic includes.
        assert policy().classify(str(FIRST_EXTRA_PAGE)) is AddedFixesFault.UNUSED

    @pytest.mark.parametrize("stem", ["", "078a", "notes", "12.5", "-1", " 251"])
    def test_a_stem_that_is_not_a_page_number_is_reported_not_raised(self, stem: str) -> None:
        # The counterpart of the unguarded `int(file.stem)`: this one always answered
        # with `isnumeric` first, and now both do.
        assert policy().classify(stem) is AddedFixesFault.NOT_NUMERIC


class TestTheStagedCollectionRange:
    """The synthetic collections' staged pages sit far outside the ordinary band.

    Checked against the real collection table rather than a made-up range, so authoring
    a new one-pager location cannot silently put every staged page out of range.
    """

    def test_a_staged_collection_page_is_allowed_though_far_past_the_ceiling(self) -> None:
        collection_pages = get_collection_page_nums(ONE_PAGER_COLLECTION_VOLUME)
        assert collection_pages, "the one-pager collection should have staged pages"

        page = min(collection_pages)
        assert page > MAX_EXTRA_FIXES_PAGE_NUM, "otherwise this proves nothing"

        allowed = policy(collection_page_nums=collection_pages, used=frozenset({str(page)}))
        assert allowed.classify(str(page)) is None

    def test_the_range_is_named_in_the_message_only_when_there_is_one(self) -> None:
        assert policy().collection_range_msg() == ""
        assert (
            "staged collection range"
            in policy(collection_page_nums=frozenset({501, 502})).collection_range_msg()
        )


class TestWhatMaySitInAFixesTree:
    @pytest.mark.parametrize(
        ("spec", "suffix", "expected"),
        [
            (STANDARD_FIXES, JPG, None),
            (STANDARD_FIXES, PNG, None),
            (STANDARD_FIXES, ".txt", FixesFault.NOT_AN_IMAGE),
            (STANDARD_FIXES, ".svg", FixesFault.NOT_AN_IMAGE),
            # The upscayled tree is png-only: its whole point is the upscaled output.
            (UPSCAYLED_FIXES, PNG, None),
            (UPSCAYLED_FIXES, JPG, FixesFault.NOT_AN_IMAGE),
        ],
    )
    def test_each_tree_accepts_only_its_own_extensions(
        self, spec: FixesTreeSpec, suffix: str, expected: FixesFault | None
    ) -> None:
        assert classify_fixes_file(suffix, spec, facts()) is expected

    @pytest.mark.parametrize("spec", [STANDARD_FIXES, UPSCAYLED_FIXES])
    def test_a_page_fixed_in_both_trees_is_a_fault_either_way(self, spec: FixesTreeSpec) -> None:
        # Which of the two fixes would win is not defined, so holding both is the fault.
        result = classify_fixes_file(PNG, spec, facts(present_in_other_tree=True))

        assert result is FixesFault.IN_BOTH_TREES

    def test_a_fix_with_no_original_and_no_permission_is_a_fault(self) -> None:
        result = classify_fixes_file(PNG, STANDARD_FIXES, facts(original_exists=False))

        assert result is FixesFault.ADDED_WITHOUT_ORIGINAL

    def test_a_fix_with_no_original_is_fine_where_the_tree_allows_added_pages(self) -> None:
        result = classify_fixes_file(
            PNG, STANDARD_FIXES, facts(original_exists=False, added_page_allowed=True)
        )

        assert result is None


class TestFixesNotes:
    """A `-fix.txt` note records why the page beside it was fixed."""

    def test_a_note_with_its_image_beside_it_is_fine(self) -> None:
        result = classify_fixes_file(
            ".txt", STANDARD_FIXES, facts(is_note=True, note_pair_present=True)
        )

        assert result is None

    def test_a_note_with_no_image_is_a_fault(self) -> None:
        result = classify_fixes_file(
            ".txt", STANDARD_FIXES, facts(is_note=True, note_pair_present=False)
        )

        assert result is FixesFault.NOTE_WITHOUT_IMAGE

    def test_a_note_is_not_judged_on_its_extension(self) -> None:
        # A note is a .txt in a tree that otherwise allows only images, so the note
        # branch has to come first or every note reads as a stray file.
        result = classify_fixes_file(
            ".txt", UPSCAYLED_FIXES, facts(is_note=True, note_pair_present=True)
        )

        assert result is None

    def test_a_note_is_not_judged_on_having_an_original(self) -> None:
        result = classify_fixes_file(
            ".txt",
            STANDARD_FIXES,
            facts(is_note=True, note_pair_present=True, original_exists=False),
        )

        assert result is None


class TestOriginalPageNumbering:
    def test_a_contiguous_run_has_no_faults(self) -> None:
        faults = check_contiguous_page_numbers(["001", "002", "003"])

        assert faults.non_numeric == []
        assert faults.out_of_order == []
        assert faults.actual_count == THREE_PAGES

    def test_a_gap_names_the_number_that_was_expected(self) -> None:
        faults = check_contiguous_page_numbers(["001", "003"])

        assert faults.out_of_order == [("003", 2)]

    def test_every_page_after_a_gap_is_reported(self) -> None:
        # One missing scan misnumbers the whole tail, and seeing the run is what says
        # whether a file is missing or the numbering restarts.
        faults = check_contiguous_page_numbers(["001", "003", "004"])

        assert faults.out_of_order == [("003", 2), ("004", 3)]

    def test_a_stray_file_is_collected_rather_than_raised(self) -> None:
        # Previously a ValueError out of a function contracted to return 0 or 1, which
        # aborted the check for all thirty volumes.
        faults = check_contiguous_page_numbers(["001", "notes", "002"])

        assert faults.non_numeric == ["notes"]

    def test_a_stray_file_does_not_shift_the_pages_after_it(self) -> None:
        # The increment used to happen before the parse, so a stray file made every
        # later page look out of order and the count come up one short.
        faults = check_contiguous_page_numbers(["001", "notes", "002", "003"])

        assert faults.out_of_order == []
        assert faults.actual_count == THREE_PAGES

    def test_a_duplicate_page_shows_up_as_out_of_order(self) -> None:
        faults = check_contiguous_page_numbers(["001", "001"])

        assert faults.out_of_order == [("001", 2)]

    def test_an_empty_directory_counts_nothing(self) -> None:
        faults = check_contiguous_page_numbers([])

        assert faults.actual_count == 0


class TestTheTreesAreNamedApart:
    """Each tree names itself in its own messages, and the other tree as the conflict.

    The two used to be able to disagree, and did: one check's guard and its message
    referred to different directories.
    """

    def test_each_tree_names_the_other_as_its_conflict(self) -> None:
        assert STANDARD_FIXES.conflicting_label == UPSCAYLED_FIXES.tree_label
        assert UPSCAYLED_FIXES.conflicting_label == STANDARD_FIXES.tree_label

    def test_the_upscayled_tree_is_the_stricter_one(self) -> None:
        assert set(UPSCAYLED_FIXES.allowed_exts) < set(STANDARD_FIXES.allowed_exts)


class TestPathsAreNotNeeded:
    def test_the_whole_policy_runs_without_touching_a_filesystem(self) -> None:
        # Every I/O answer is passed in, which is what lets the two trees share one
        # classifier. A path that does not exist proves it.
        gone = Path("/definitely/not/here/251.png")

        assert classify_fixes_file(gone.suffix, STANDARD_FIXES, facts()) is None
        assert policy().classify(gone.stem) is AddedFixesFault.UNUSED
