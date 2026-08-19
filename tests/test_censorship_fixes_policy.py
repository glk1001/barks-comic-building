"""Tests for how the censorship-fixes CSV and the fixes trees must agree.

The CSV is the editorial record of every correction made to a Fantagraphics scan - a
line of dialogue restored, a hat recoloured, a glitch cleaned. The fixes trees are the
images that carry those corrections. Nothing tied the two together, so they could drift
in either direction: a fix applied and never written down, or written down and never
applied. Both happened - the first 28 times, and the second once, on a row that named
the wrong page of its story.

Two things about the comparison are policy rather than mechanism, and are what this
file pins.

The first is what counts as a fix at all. A fixes tree holds two kinds of image: an
*edit*, which replaces a scan the volume already had, and an *addition*, which is a page
the volume never had. Only edits are corrections; the 497 additions are covers, essays,
paintings and restored stories, and none of them belongs in the CSV. The distinguishing
fact is whether an original scan sits behind the page - not the file's extension, and
not whether its page number is past the end of the volume. Both of those were tried
while working this out and both are wrong: the extension splits repainted from copied-in
rather than edit from addition, and the page-number rule misfiles the restored *Bill
Collectors* page, which is an addition that really is a censorship fix.

The row checks are the other half: the CSV agreeing with itself rather than with the
trees. Volume and Image are worked out from the story and the page within it, so a
hand-edited one describes a page it does not mean - and because a plain run rewrites
them from the story, being wrong was invisible. One was: a row gave image 134 with comic
page 7 of Turkey Raffle, but 134 is that story's page 4, and the next run would have
moved the image to 137 and undone the row's whole point.

Fanta_page cannot be checked against an absolute here - the printed start pages live in
another repo - but it does not need to be. Both page numbers advance one per page, so a
story implies exactly one offset between them, and a row that breaks it is wrong without
anyone knowing where the story starts.

The second is that the one asymmetry runs in only one direction. A story Fantagraphics
cut entirely comes back as pages with no original scan, so the CSV may legitimately cite
an addition. It does not follow that an uncited addition is a missing CSV row - almost
all of them are just additions - so that direction stays silent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from barks_fantagraphics.censorship_fixes import (
    story_page_offsets,
    story_page_offsets_disagree,
)

from barks_comic_building.build.comics_integrity import (
    CensorshipCsvFault,
    CensorshipPageFacts,
    CensorshipRowFacts,
    CensorshipRowFault,
    classify_censorship_page,
    classify_censorship_row,
)


def facts(
    *,
    cited_in_csv: bool = True,
    has_edited_image: bool = True,
    added_page_allowed: bool = False,
    page_is_non_comic: bool = False,
) -> CensorshipPageFacts:
    """Make one page's facts, defaulting to a fix that is recorded and was applied."""
    return CensorshipPageFacts(
        cited_in_csv=cited_in_csv,
        has_edited_image=has_edited_image,
        added_page_allowed=added_page_allowed,
        page_is_non_comic=page_is_non_comic,
    )


class TestWhenTheCsvAndTheTreesAgree:
    """The two states that are not findings."""

    def test_a_recorded_fix_with_an_edited_image_is_fine(self) -> None:
        assert classify_censorship_page(facts()) is None

    def test_a_page_with_neither_is_not_a_finding(self) -> None:
        # Most pages of most volumes: no fix recorded, no fix applied.
        assert classify_censorship_page(facts(cited_in_csv=False, has_edited_image=False)) is None


class TestARecordedFixWithNoImage:
    """The CSV names a page nobody fixed."""

    def test_it_is_reported(self) -> None:
        assert (
            classify_censorship_page(facts(has_edited_image=False))
            is CensorshipCsvFault.NO_FIX_IMAGE
        )

    def test_an_added_page_may_be_cited_without_being_an_edit(self) -> None:
        # The restored Bill Collectors page: an addition, and a censorship fix.
        assert (
            classify_censorship_page(facts(has_edited_image=False, added_page_allowed=True)) is None
        )


class TestAnEditedImageWithNoCsvRow:
    """A page was fixed and nobody wrote it down."""

    def test_it_is_reported(self) -> None:
        assert (
            classify_censorship_page(facts(cited_in_csv=False))
            is CensorshipCsvFault.UNDOCUMENTED_FIX
        )

    def test_an_uncited_addition_is_not_an_undocumented_fix(self) -> None:
        # The asymmetry: being allowed to cite an addition does not make one required.
        assert (
            classify_censorship_page(
                facts(cited_in_csv=False, has_edited_image=False, added_page_allowed=True)
            )
            is None
        )

    def test_being_an_allowed_addition_does_not_excuse_an_uncited_edit(self) -> None:
        # A page that is both edited and a permitted addition is still an edit, and an
        # edit still has to be recorded.
        assert (
            classify_censorship_page(facts(cited_in_csv=False, added_page_allowed=True))
            is CensorshipCsvFault.UNDOCUMENTED_FIX
        )


class TestAnEssayPageNeedsNoRow:
    """The volumes' essays and articles are retouched too, and are not comics.

    The CSV records what was changed in the comics. Four prose pages - two of the Maggie
    Thompson article, two of the Don Ault essay - were the last findings standing, and
    they were never going to be written down.
    """

    def test_an_unrecorded_fix_to_one_is_not_reported(self) -> None:
        assert classify_censorship_page(facts(cited_in_csv=False, page_is_non_comic=True)) is None

    def test_recording_one_anyway_is_still_allowed(self) -> None:
        # Exempt from having to be recorded, not from being able to be.
        assert classify_censorship_page(facts(page_is_non_comic=True)) is None

    def test_a_recorded_fix_to_one_still_needs_its_image(self) -> None:
        # The exemption is one-directional: it excuses a missing row, not a missing file.
        assert (
            classify_censorship_page(facts(has_edited_image=False, page_is_non_comic=True))
            is CensorshipCsvFault.NO_FIX_IMAGE
        )


class TestTheWholeTruthTable:
    """Every combination of the four facts, so no case is left undecided."""

    @pytest.mark.parametrize("non_comic", [False, True])
    @pytest.mark.parametrize(
        ("cited", "edited", "added", "expected"),
        [
            (False, False, False, None),
            (False, False, True, None),
            (False, True, False, CensorshipCsvFault.UNDOCUMENTED_FIX),
            (False, True, True, CensorshipCsvFault.UNDOCUMENTED_FIX),
            (True, False, False, CensorshipCsvFault.NO_FIX_IMAGE),
            (True, False, True, None),
            (True, True, False, None),
            (True, True, True, None),
        ],
    )
    def test_each_combination_has_one_verdict(
        self,
        cited: bool,
        edited: bool,
        added: bool,
        non_comic: bool,
        expected: CensorshipCsvFault | None,
    ) -> None:
        # Being a non-comic page changes exactly one verdict: it excuses the missing row.
        if non_comic and expected is CensorshipCsvFault.UNDOCUMENTED_FIX:
            expected = None

        verdict = classify_censorship_page(
            facts(
                cited_in_csv=cited,
                has_edited_image=edited,
                added_page_allowed=added,
                page_is_non_comic=non_comic,
            )
        )

        assert verdict is expected


class TestPathsAreNotNeeded:
    """The policy is a function of the facts, so it needs no filesystem to answer.

    The same separation `test_fixes_file_policy.py` pins for `classify_fixes_file`: the
    I/O lives in the checker, the decision lives here, and the decision is testable
    without a volume mounted.
    """

    def test_the_whole_policy_runs_without_touching_a_filesystem(self) -> None:
        gone = Path("/definitely/not/here/153.png")

        assert not gone.exists()
        assert (
            classify_censorship_page(facts(has_edited_image=False))
            is CensorshipCsvFault.NO_FIX_IMAGE
        )


def row_facts(  # noqa: PLR0913 - one keyword per fact, which is the point of the helper
    *,
    stored_volume: int = 4,
    stored_image: str = "134",
    stored_comic_page: str = "4",
    expected_volume: int | None = 4,
    expected_image: str | None = "134",
    image_is_unnumbered_page: bool = False,
) -> CensorshipRowFacts:
    """Make one row's facts, defaulting to a row that agrees with its own story."""
    return CensorshipRowFacts(
        stored_volume=stored_volume,
        stored_image=stored_image,
        stored_comic_page=stored_comic_page,
        expected_volume=expected_volume,
        expected_image=expected_image,
        image_is_unnumbered_page=image_is_unnumbered_page,
    )


class TestARowThatAgreesWithItsStory:
    """The states that are not findings."""

    def test_a_matching_volume_and_image_is_fine(self) -> None:
        assert classify_censorship_row(row_facts()) is None

    def test_a_whole_story_row_names_no_image_and_needs_none(self) -> None:
        # A story censored out of its volume: no one page to point at.
        assert (
            classify_censorship_row(
                row_facts(stored_image="", stored_comic_page="", expected_image=None)
            )
            is None
        )


class TestARowThatDoesNot:
    """Each way a row can describe a page it does not mean."""

    def test_a_story_the_database_does_not_know(self) -> None:
        assert (
            classify_censorship_row(row_facts(expected_volume=None))
            is CensorshipRowFault.UNKNOWN_STORY
        )

    def test_a_wrong_volume(self) -> None:
        assert (
            classify_censorship_row(row_facts(stored_volume=9)) is CensorshipRowFault.WRONG_VOLUME
        )

    def test_a_page_the_story_does_not_have(self) -> None:
        assert (
            classify_censorship_row(row_facts(expected_image=None))
            is CensorshipRowFault.UNKNOWN_PAGE
        )

    def test_an_image_that_is_no_page_of_the_story_at_all(self) -> None:
        # No page number given, and the image is not one of its unnumbered pages either.
        assert (
            classify_censorship_row(row_facts(stored_comic_page="", expected_image=None))
            is CensorshipRowFault.UNKNOWN_PAGE
        )

    def test_a_wrong_image(self) -> None:
        # The Turkey Raffle row: page 7 of a story whose page 4 is image 134.
        assert (
            classify_censorship_row(row_facts(expected_image="137"))
            is CensorshipRowFault.WRONG_IMAGE
        )

    def test_the_volume_is_judged_before_the_image(self) -> None:
        # A wrong volume makes the image meaningless, so it is the finding worth showing.
        assert (
            classify_censorship_row(row_facts(stored_volume=9, expected_image="137"))
            is CensorshipRowFault.WRONG_VOLUME
        )

    def test_a_whole_story_row_still_has_to_name_the_right_volume(self) -> None:
        assert (
            classify_censorship_row(
                row_facts(
                    stored_volume=9, stored_image="", stored_comic_page="", expected_image=None
                )
            )
            is CensorshipRowFault.WRONG_VOLUME
        )


class TestAPageWithNoNumberOfItsOwn:
    """A cover, or back matter: an image and no page, because there is no page to name.

    Ten rows do this today. Judging them by the body pages reported every one as naming
    a page the story does not have, which is true and beside the point - a cover is not
    a body page and never will be.
    """

    def test_a_cover_row_is_fine(self) -> None:
        facts = row_facts(
            stored_image="213",
            stored_comic_page="",
            expected_image=None,
            image_is_unnumbered_page=True,
        )

        assert classify_censorship_row(facts) is None

    def test_an_unnumbered_page_still_has_to_be_in_the_right_volume(self) -> None:
        facts = row_facts(
            stored_volume=9,
            stored_image="213",
            stored_comic_page="",
            expected_image=None,
            image_is_unnumbered_page=True,
        )

        assert classify_censorship_row(facts) is CensorshipRowFault.WRONG_VOLUME

    def test_giving_a_page_number_for_one_is_still_wrong(self) -> None:
        # `Back to Long Ago!` had its back-matter page filed as comic page 24, which the
        # story does not have - the image is right and the page number should not be there.
        facts = row_facts(
            stored_image="209",
            stored_comic_page="24",
            expected_image=None,
            image_is_unnumbered_page=True,
        )

        assert classify_censorship_row(facts) is CensorshipRowFault.UNKNOWN_PAGE


class TestAStoryImpliesOneOffset:
    """Fanta_page and Comic_page advance together, so their gap is the story's start."""

    def test_rows_in_step_imply_one_offset(self) -> None:
        assert story_page_offsets([("1", "95"), ("2", "96"), ("10", "104")]) == {94}

    def test_a_row_out_of_step_shows_up_as_a_second_offset(self) -> None:
        assert story_page_offsets([("1", "95"), ("7", "98")]) == {94, 91}

    def test_a_single_row_cannot_disagree_with_itself(self) -> None:
        assert story_page_offsets([("1", "95")]) == {94}

    def test_a_restored_page_folio_is_skipped_rather_than_parsed(self) -> None:
        # "188a" sits between two printed pages, so it implies no whole-page offset.
        assert story_page_offsets([("1", "187"), ("3", "188a"), ("4", "189")]) == {186, 185}

    def test_a_whole_story_row_contributes_no_offset(self) -> None:
        assert story_page_offsets([("", "")]) == set()


class TestARestoredPageIsAllowedToStepTheOffset:
    """The Bill Collectors: a page put back mid-story shifts every page after it.

    Its printed pages run 187, 188, then the restored folio 188a, then 189 onwards - so
    pages before the restoration sit one printed page higher than pages after it, and two
    offsets is what a correct story looks like.
    """

    def test_two_offsets_are_fine_when_a_folio_explains_one_of_them(self) -> None:
        pairs = [("1", "187"), ("3", "188a"), ("4", "189"), ("9", "194")]

        assert not story_page_offsets_disagree(pairs)

    def test_two_offsets_with_no_folio_is_a_disagreement(self) -> None:
        assert story_page_offsets_disagree([("1", "95"), ("7", "98")])

    def test_rows_in_step_never_disagree(self) -> None:
        assert not story_page_offsets_disagree([("1", "95"), ("2", "96"), ("10", "104")])

    def test_a_folio_does_not_excuse_a_second_unexplained_step(self) -> None:
        # One folio buys one step, not two.
        pairs = [("1", "187"), ("3", "188a"), ("4", "189"), ("9", "300")]

        assert story_page_offsets_disagree(pairs)
