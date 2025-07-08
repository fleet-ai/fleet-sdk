from collections.abc import Mapping
from typing import Any, TypeVar, Union, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="Instance")


@_attrs_define
class Instance:
    """Model for instance response data.

    Attributes:
        instance_id (str):
        env_key (str):
        version (str):
        status (str):
        subdomain (str):
        created_at (str):
        updated_at (str):
        team_id (str):
        region (str):
        terminated_at (Union[None, Unset, str]):
    """

    instance_id: str
    env_key: str
    version: str
    status: str
    subdomain: str
    created_at: str
    updated_at: str
    team_id: str
    region: str
    terminated_at: Union[None, Unset, str] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        instance_id = self.instance_id

        env_key = self.env_key

        version = self.version

        status = self.status

        subdomain = self.subdomain

        created_at = self.created_at

        updated_at = self.updated_at

        team_id = self.team_id

        region = self.region

        terminated_at: Union[None, Unset, str]
        if isinstance(self.terminated_at, Unset):
            terminated_at = UNSET
        else:
            terminated_at = self.terminated_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "instance_id": instance_id,
                "env_key": env_key,
                "version": version,
                "status": status,
                "subdomain": subdomain,
                "created_at": created_at,
                "updated_at": updated_at,
                "team_id": team_id,
                "region": region,
            }
        )
        if terminated_at is not UNSET:
            field_dict["terminated_at"] = terminated_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        instance_id = d.pop("instance_id")

        env_key = d.pop("env_key")

        version = d.pop("version")

        status = d.pop("status")

        subdomain = d.pop("subdomain")

        created_at = d.pop("created_at")

        updated_at = d.pop("updated_at")

        team_id = d.pop("team_id")

        region = d.pop("region")

        def _parse_terminated_at(data: object) -> Union[None, Unset, str]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, str], data)

        terminated_at = _parse_terminated_at(d.pop("terminated_at", UNSET))

        instance = cls(
            instance_id=instance_id,
            env_key=env_key,
            version=version,
            status=status,
            subdomain=subdomain,
            created_at=created_at,
            updated_at=updated_at,
            team_id=team_id,
            region=region,
            terminated_at=terminated_at,
        )

        instance.additional_properties = d
        return instance

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
