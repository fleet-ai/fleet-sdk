from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, Union, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.manager_ur_ls import ManagerURLs


T = TypeVar("T", bound="InstanceURLs")


@_attrs_define
class InstanceURLs:
    """Model for instance URLs.

    Attributes:
        root (str):
        app (str):
        manager (ManagerURLs): Model for manager API URLs.
        api (Union[None, Unset, str]):
        health (Union[None, Unset, str]):
        api_docs (Union[None, Unset, str]):
    """

    root: str
    app: str
    manager: "ManagerURLs"
    api: Union[None, Unset, str] = UNSET
    health: Union[None, Unset, str] = UNSET
    api_docs: Union[None, Unset, str] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        root = self.root

        app = self.app

        manager = self.manager.to_dict()

        api: Union[None, Unset, str]
        if isinstance(self.api, Unset):
            api = UNSET
        else:
            api = self.api

        health: Union[None, Unset, str]
        if isinstance(self.health, Unset):
            health = UNSET
        else:
            health = self.health

        api_docs: Union[None, Unset, str]
        if isinstance(self.api_docs, Unset):
            api_docs = UNSET
        else:
            api_docs = self.api_docs

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "root": root,
                "app": app,
                "manager": manager,
            }
        )
        if api is not UNSET:
            field_dict["api"] = api
        if health is not UNSET:
            field_dict["health"] = health
        if api_docs is not UNSET:
            field_dict["api_docs"] = api_docs

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manager_ur_ls import ManagerURLs

        d = dict(src_dict)
        root = d.pop("root")

        app = d.pop("app")

        manager = ManagerURLs.from_dict(d.pop("manager"))

        def _parse_api(data: object) -> Union[None, Unset, str]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, str], data)

        api = _parse_api(d.pop("api", UNSET))

        def _parse_health(data: object) -> Union[None, Unset, str]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, str], data)

        health = _parse_health(d.pop("health", UNSET))

        def _parse_api_docs(data: object) -> Union[None, Unset, str]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, str], data)

        api_docs = _parse_api_docs(d.pop("api_docs", UNSET))

        instance_ur_ls = cls(
            root=root,
            app=app,
            manager=manager,
            api=api,
            health=health,
            api_docs=api_docs,
        )

        instance_ur_ls.additional_properties = d
        return instance_ur_ls

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
