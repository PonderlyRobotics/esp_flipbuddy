"""Host tests: MPU live-settle uses g-units and injected face names."""

from util import SETTLE_STABLE_SAMPLES, accel_delta, settle_step


def _run(samples, needed=SETTLE_STABLE_SAMPLES, move_g=0.16):
    prev = None
    prev_face = None
    count = 0
    last = None
    for accel, face in samples:
        last = settle_step(
            prev,
            accel,
            face,
            prev_face,
            count,
            needed=needed,
            move_g=move_g,
        )
        prev = accel
        prev_face = last["face"]
        count = last["stable_count"]
    return last


def test_settle_fifty_same_face_commits():
    front = ((0.0, 1.0, 0.0), "front")
    last = _run([front] * SETTLE_STABLE_SAMPLES)
    assert last["face"] == "front"
    assert last["committed"] is True
    assert last["stable_count"] == SETTLE_STABLE_SAMPLES


def test_settle_forty_nine_same_face_does_not_commit():
    front = ((0.0, 1.0, 0.0), "front")
    n = SETTLE_STABLE_SAMPLES - 1
    last = _run([front] * n)
    assert last["face"] == "front"
    assert last["committed"] is False
    assert last["stable_count"] == n


def test_settle_rotation_resets_dwell():
    last = _run(
        [
            ((0.0, 1.0, 0.0), "front"),
            ((0.0, 0.0, -1.0), "right"),
        ]
    )
    assert last["face"] == "right"
    assert last["moved"] is True
    assert last["stable_count"] == 1
    assert last["committed"] is False


def test_settle_out_margin_does_not_commit_or_keep_count():
    front = ((0.0, 1.0, 0.0), "front")
    last = _run(
        [front, front, ((0.0, 0.0, 0.0), "out_margin"), front, front]
    )
    assert last["face"] == "front"
    assert last["stable_count"] == 2
    assert last["committed"] is False


def test_settle_out_margin_sample_clears_stability():
    last = _run([((0.0, 1.0, 0.0), "front"), ((0.0, 0.0, 0.0), "out_margin")])
    assert last["face"] == "out_margin"
    assert last["moved"] is True
    assert last["stable_count"] == 0
    assert last["committed"] is False


def test_accel_delta_euclidean_in_g():
    assert accel_delta((0, 0, 0), (0.3, 0.4, 0.0)) == 0.5
    assert accel_delta(None, (1, 0, 0)) == 0.0
