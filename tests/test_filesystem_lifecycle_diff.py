from fleet.instance.models import Resource, ResourceMode, ResourceType
from fleet.resources.filesystem import FilesystemResource


class _Response:
    status_code = 200
    text = ""

    def json(self):
        return {
            "success": True,
            "files": [
                {
                    "path": "/home/desktop/Documents/example.txt",
                    "size": 5,
                    "modified_time": "2026-08-08T12:00:00",
                    "file_type": "file",
                    "entry_type": "file",
                    "change_type": "created",
                    "content": "hello",
                    "encoding": "utf-8",
                }
            ],
            "total_files": 1,
            "total_size": 5,
            "source": "snapshot_service",
            "message": "ok",
        }


class _Client:
    def __init__(self):
        self.request_json = None

    def request(self, method, path, json):
        assert method == "POST"
        assert path == "/diff/fs"
        self.request_json = json
        return _Response()


def test_filesystem_diff_sends_post_start_contract_and_parses_lifecycle_fields():
    client = _Client()
    resource = FilesystemResource(
        Resource(name="fs", type=ResourceType.api, mode=ResourceMode.rw), client
    )

    diff = resource.diff(diff_mode="post_start", max_content_size=2048)

    assert client.request_json["diff_mode"] == "post_start"
    assert client.request_json["max_content_size"] == 2048
    diff.expect_exactly(
        [
            {
                "path": "/home/desktop/Documents/example.txt",
                "content": "hello",
                "change_type": "created",
                "entry_type": "file",
                "encoding": "utf-8",
            }
        ]
    )
