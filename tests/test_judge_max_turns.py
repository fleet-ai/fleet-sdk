"""max_turns must reach the request body from both grade() entry points."""

from fleet.judge import _build_grade_request


def test_builder_includes_max_turns():
    body = _build_grade_request("inst-1", "rubric", "answer", max_turns=30)
    assert body["max_turns"] == 30


def test_builder_omits_max_turns_by_default():
    body = _build_grade_request("inst-1", "rubric", "answer")
    assert "max_turns" not in body


def _grade_body(judge_cls, **kwargs):
    captured = {}

    class _Resp:
        @staticmethod
        def json():
            return {
                "normalized_score": 1.0,
                "total_score": 1.0,
                "max_score": 1.0,
                "feedback": "",
                "model_used": "m",
                "execution_id": "e",
            }

    class _Client:
        def request(self, method, path, json=None, extra_headers=None):
            captured.update(json)
            return _Resp()

    judge = judge_cls.__new__(judge_cls)
    judge._instance_id = "inst-1"
    judge._client = _Client()
    judge.grade("rubric", "answer", **kwargs)
    return captured


def test_sync_grade_passes_max_turns():
    from fleet.judge import SyncJudge as JudgeClient

    body = _grade_body(JudgeClient, max_turns=25)
    assert body["max_turns"] == 25


def test_sync_grade_defaults_to_no_max_turns():
    from fleet.judge import SyncJudge as JudgeClient

    body = _grade_body(JudgeClient)
    assert "max_turns" not in body
