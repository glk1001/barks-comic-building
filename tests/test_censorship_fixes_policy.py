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

The second is that the one asymmetry runs in only one direction. A story Fantagraphics
cut entirely comes back as pages with no original scan, so the CSV may legitimately cite
an addition. It does not follow that an uncited addition is a missing CSV row - almost
all of them are just additions - so that direction stays silent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from barks_comic_building.build.comics_integrity import (
    CensorshipCsvFault,
    CensorshipPageFacts,
    classify_censorship_page,
)


def facts(
    *,
    cited_in_csv: bool = True,
    has_edited_image: bool = True,
    added_page_allowed: bool = False,
) -> CensorshipPageFacts:
    """Make one page's facts, defaulting to a fix that is recorded and was applied."""
    return CensorshipPageFacts(
        cited_in_csv=cited_in_csv,
        has_edited_image=has_edited_image,
        added_page_allowed=added_page_allowed,
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


class TestTheWholeTruthTable:
    """Every combination of the three facts, so no case is left undecided."""

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
        self, cited: bool, edited: bool, added: bool, expected: CensorshipCsvFault | None
    ) -> None:
        verdict = classify_censorship_page(
            facts(cited_in_csv=cited, has_edited_image=edited, added_page_allowed=added)
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
