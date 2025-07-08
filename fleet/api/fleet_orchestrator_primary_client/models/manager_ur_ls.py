from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="ManagerURLs")


@_attrs_define
class ManagerURLs:
    """Model for manager API URLs.

    Attributes:
        api (str):
        docs (str):
        reset (str):
        diff (str):
        snapshot (str):
        execute_verifier_function (str):
        execute_verifier_function_with_upload (str):
    """

    api: str
    docs: str
    reset: str
    diff: str
    snapshot: str
    execute_verifier_function: str
    execute_verifier_function_with_upload: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        api = self.api

        docs = self.docs

        reset = self.reset

        diff = self.diff

        snapshot = self.snapshot

        execute_verifier_function = self.execute_verifier_function

        execute_verifier_function_with_upload = self.execute_verifier_function_with_upload

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "api": api,
                "docs": docs,
                "reset": reset,
                "diff": diff,
                "snapshot": snapshot,
                "execute_verifier_function": execute_verifier_function,
                "execute_verifier_function_with_upload": execute_verifier_function_with_upload,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        api = d.pop("api")

        docs = d.pop("docs")

        reset = d.pop("reset")

        diff = d.pop("diff")

        snapshot = d.pop("snapshot")

        execute_verifier_function = d.pop("execute_verifier_function")

        execute_verifier_function_with_upload = d.pop("execute_verifier_function_with_upload")

        manager_ur_ls = cls(
            api=api,
            docs=docs,
            reset=reset,
            diff=diff,
            snapshot=snapshot,
            execute_verifier_function=execute_verifier_function,
            execute_verifier_function_with_upload=execute_verifier_function_with_upload,
        )

        manager_ur_ls.additional_properties = d
        return manager_ur_ls

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
