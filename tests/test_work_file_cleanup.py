"""Tests for what the work file cleanup is allowed to delete.

A full restore writes about 155MB of intermediates per page and there are five and a half
thousand pages, so they have to be cleaned up as the run goes or it runs the disk out.
That makes deletion part of the normal path of a very long unattended job, which is
exactly the kind of thing that quietly destroys work when it reaches further than it
meant to.

The work directory is shared by every page of a title, so the property being tested is
that a page's cleanup touches that page's files and nothing else - not its neighbours'
intermediates, not the outputs, not the directory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from barks_comic_building.restore.batch_restore_pipeline import _clean_up_work_files
from barks_comic_building.restore.restore_pipeline import RestorePipeline

if TYPE_CHECKING:
    from pathlib import Path


def make_pipeline(tmp_path: Path, page: str) -> RestorePipeline:
    """Build a pipeline for one page, with the directories and input it validates."""
    work_dir = tmp_path / "work"
    out_dir = tmp_path / "restored"
    svg_dir = tmp_path / "svg"
    for directory in (work_dir, out_dir, svg_dir):
        directory.mkdir(exist_ok=True)

    upscayl_file = tmp_path / f"{page}.png"
    upscayl_file.write_bytes(b"upscayled")

    return RestorePipeline(
        work_dir,
        tmp_path / f"{page}.jpg",
        upscayl_file,
        4,
        out_dir / f"{page}.png",
        out_dir / f"{page}-4x.png",
        svg_dir / f"{page}.svg",
    )


@pytest.fixture
def pipeline(tmp_path: Path) -> RestorePipeline:
    return make_pipeline(tmp_path, "110")


class TestCleanUpWorkFiles:
    def test_deletes_this_page_s_intermediates(self, pipeline: RestorePipeline) -> None:
        for file in pipeline.work_files:
            file.write_bytes(b"intermediate")

        _clean_up_work_files(pipeline)

        assert [f for f in pipeline.work_files if f.is_file()] == []

    def test_covers_the_files_written_by_the_step_modules(self, pipeline: RestorePipeline) -> None:
        """Every intermediate is covered, including the ones written by the step modules.

        Those three are written by the step modules rather than by the pipeline, so they
        are easy to leave out of the list and leave behind forever.
        """
        names = {f.name for f in pipeline.work_files}

        for suffix in (
            "-posterized-pre-remove-colors.png",
            "-remove-mask.png",
            "-input-black-removed.png",
        ):
            assert f"{pipeline.srce_upscale_stem}{suffix}" in names

    def test_leaves_another_page_s_intermediates_alone(self, tmp_path: Path) -> None:
        """The work directory holds a whole title, not one page."""
        page_110 = make_pipeline(tmp_path, "110")
        page_111 = make_pipeline(tmp_path, "111")
        for file in page_110.work_files + page_111.work_files:
            file.write_bytes(b"intermediate")

        _clean_up_work_files(page_110)

        assert all(f.is_file() for f in page_111.work_files)

    def test_leaves_the_outputs_alone(self, pipeline: RestorePipeline) -> None:
        """The deliverables are the point of the run - they are not work files."""
        outputs = [
            pipeline.dest_restored_file,
            pipeline.dest_upscayled_restored_file,
            pipeline.dest_svg_restored_file,
            pipeline.png_of_svg_file,
        ]
        for file in outputs:
            file.write_bytes(b"output")
        for file in pipeline.work_files:
            file.write_bytes(b"intermediate")

        _clean_up_work_files(pipeline)

        assert all(f.is_file() for f in outputs)

    def test_leaves_the_work_directory_itself(self, pipeline: RestorePipeline) -> None:
        for file in pipeline.work_files:
            file.write_bytes(b"intermediate")

        _clean_up_work_files(pipeline)

        assert pipeline.work_dir.is_dir()

    def test_leaves_unrelated_files_in_the_work_directory(self, pipeline: RestorePipeline) -> None:
        """Anything else living in the work directory survives.

        Cleanup names the files it deletes rather than globbing the directory.
        """
        stranger = pipeline.work_dir / "notes.txt"
        stranger.write_text("do not delete me")
        for file in pipeline.work_files:
            file.write_bytes(b"intermediate")

        _clean_up_work_files(pipeline)

        assert stranger.is_file()

    def test_missing_intermediates_are_not_an_error(self, pipeline: RestorePipeline) -> None:
        """Steps that were skipped never wrote theirs, which is the normal case."""
        pipeline.inpainted_file.write_bytes(b"intermediate")

        _clean_up_work_files(pipeline)

        assert not pipeline.inpainted_file.is_file()

    def test_the_4x_ink_render_is_a_work_file(self, pipeline: RestorePipeline) -> None:
        """The 4x ink render is a work file, and the 1x one beside the svg is not.

        They used to share a path. If they still did, cleaning up would delete a shipped
        output.
        """
        assert pipeline.svg_png_4x_file in pipeline.work_files
        assert pipeline.png_of_svg_file not in pipeline.work_files
        assert pipeline.svg_png_4x_file != pipeline.png_of_svg_file
