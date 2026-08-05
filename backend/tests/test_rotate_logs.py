import gzip

import pipeline.rotate_logs as rotate_logs


def test_small_log_is_left_untouched(tmp_path):
    log_path = tmp_path / "small.log"
    log_path.write_bytes(b"tiny content")

    archive = rotate_logs._rotate_one(log_path)

    assert archive is None
    assert log_path.read_bytes() == b"tiny content"
    assert list(tmp_path.glob("*.gz")) == []


def test_large_log_is_gzipped_and_truncated_in_place(tmp_path):
    log_path = tmp_path / "big.log"
    content = b"x" * (rotate_logs.ROTATE_SIZE_THRESHOLD_BYTES + 1)
    log_path.write_bytes(content)

    archive = rotate_logs._rotate_one(log_path)

    assert archive is not None
    assert archive.parent == tmp_path
    assert archive.name.startswith("big.log.") and archive.name.endswith(".gz")
    with gzip.open(archive, "rb") as f:
        assert f.read() == content
    # Truncated in place, not deleted/recreated -- the original path still exists, empty.
    assert log_path.exists()
    assert log_path.read_bytes() == b""


def test_rotate_one_preserves_an_open_file_handles_fd(tmp_path):
    """A writer that already has the file open (e.g. a live uvicorn process)
    must keep writing successfully after rotation, since rotate_logs uses
    ftruncate rather than unlink+recreate."""
    log_path = tmp_path / "live.log"
    content = b"x" * (rotate_logs.ROTATE_SIZE_THRESHOLD_BYTES + 1)
    log_path.write_bytes(content)

    with open(log_path, "ab") as writer:
        rotate_logs._rotate_one(log_path)
        writer.write(b"new line after rotation\n")

    assert log_path.read_bytes() == b"new line after rotation\n"


def test_prune_old_archives_keeps_only_the_most_recent(tmp_path):
    log_path = tmp_path / "app.log"
    log_path.write_bytes(b"")
    names = [f"app.log.2026080{i}_120000.gz" for i in range(1, 6)]
    for name in names:
        (tmp_path / name).write_bytes(b"fake")

    deleted = rotate_logs._prune_old_archives(log_path, keep=3)

    remaining = sorted(p.name for p in tmp_path.glob("app.log.*.gz"))
    assert remaining == names[-3:]
    assert sorted(p.name for p in deleted) == names[:2]


def test_rotate_all_only_processes_dot_log_files(tmp_path):
    (tmp_path / "big.log").write_bytes(b"x" * (rotate_logs.ROTATE_SIZE_THRESHOLD_BYTES + 1))
    (tmp_path / "small.log").write_bytes(b"tiny")
    (tmp_path / "not_a_log.txt").write_bytes(b"x" * (rotate_logs.ROTATE_SIZE_THRESHOLD_BYTES + 1))

    rotated = rotate_logs.rotate_all(logs_dir=tmp_path)

    assert len(rotated) == 1
    assert rotated[0].name.startswith("big.log.")
    assert list(tmp_path.glob("not_a_log.txt*.gz")) == []
