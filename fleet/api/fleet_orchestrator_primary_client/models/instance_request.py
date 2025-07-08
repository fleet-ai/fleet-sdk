from collections.abc import Mapping
from typing import Any, TypeVar, Union, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="InstanceRequest")


@_attrs_define
class InstanceRequest:
    """Model for creating a new instance.

    Attributes:
        env_key (str):
        version (Union[None, Unset, str]):
        region (Union[None, Unset, str]):  Default: 'us-east-2'.
        seed (Union[None, Unset, int]):
        timestamp (Union[None, Unset, int]):
        p_error (Union[None, Unset, float]):
        avg_latency (Union[None, Unset, float]):
        run_id (Union[None, Unset, str]):
        task_id (Union[None, Unset, str]):
    """

    env_key: str
    version: Union[None, Unset, str] = UNSET
    region: Union[None, Unset, str] = "us-east-2"
    seed: Union[None, Unset, int] = UNSET
    timestamp: Union[None, Unset, int] = UNSET
    p_error: Union[None, Unset, float] = UNSET
    avg_latency: Union[None, Unset, float] = UNSET
    run_id: Union[None, Unset, str] = UNSET
    task_id: Union[None, Unset, str] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        env_key = self.env_key

        version: Union[None, Unset, str]
        if isinstance(self.version, Unset):
            version = UNSET
        else:
            version = self.version

        region: Union[None, Unset, str]
        if isinstance(self.region, Unset):
            region = UNSET
        else:
            region = self.region

        seed: Union[None, Unset, int]
        if isinstance(self.seed, Unset):
            seed = UNSET
        else:
            seed = self.seed

        timestamp: Union[None, Unset, int]
        if isinstance(self.timestamp, Unset):
            timestamp = UNSET
        else:
            timestamp = self.timestamp

        p_error: Union[None, Unset, float]
        if isinstance(self.p_error, Unset):
            p_error = UNSET
        else:
            p_error = self.p_error

        avg_latency: Union[None, Unset, float]
        if isinstance(self.avg_latency, Unset):
            avg_latency = UNSET
        else:
            avg_latency = self.avg_latency

        run_id: Union[None, Unset, str]
        if isinstance(self.run_id, Unset):
            run_id = UNSET
        else:
            run_id = self.run_id

        task_id: Union[None, Unset, str]
        if isinstance(self.task_id, Unset):
            task_id = UNSET
        else:
            task_id = self.task_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "env_key": env_key,
            }
        )
        if version is not UNSET:
            field_dict["version"] = version
        if region is not UNSET:
            field_dict["region"] = region
        if seed is not UNSET:
            field_dict["seed"] = seed
        if timestamp is not UNSET:
            field_dict["timestamp"] = timestamp
        if p_error is not UNSET:
            field_dict["p_error"] = p_error
        if avg_latency is not UNSET:
            field_dict["avg_latency"] = avg_latency
        if run_id is not UNSET:
            field_dict["run_id"] = run_id
        if task_id is not UNSET:
            field_dict["task_id"] = task_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        env_key = d.pop("env_key")

        def _parse_version(data: object) -> Union[None, Unset, str]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, str], data)

        version = _parse_version(d.pop("version", UNSET))

        def _parse_region(data: object) -> Union[None, Unset, str]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, str], data)

        region = _parse_region(d.pop("region", UNSET))

        def _parse_seed(data: object) -> Union[None, Unset, int]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, int], data)

        seed = _parse_seed(d.pop("seed", UNSET))

        def _parse_timestamp(data: object) -> Union[None, Unset, int]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, int], data)

        timestamp = _parse_timestamp(d.pop("timestamp", UNSET))

        def _parse_p_error(data: object) -> Union[None, Unset, float]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, float], data)

        p_error = _parse_p_error(d.pop("p_error", UNSET))

        def _parse_avg_latency(data: object) -> Union[None, Unset, float]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, float], data)

        avg_latency = _parse_avg_latency(d.pop("avg_latency", UNSET))

        def _parse_run_id(data: object) -> Union[None, Unset, str]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, str], data)

        run_id = _parse_run_id(d.pop("run_id", UNSET))

        def _parse_task_id(data: object) -> Union[None, Unset, str]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, str], data)

        task_id = _parse_task_id(d.pop("task_id", UNSET))

        instance_request = cls(
            env_key=env_key,
            version=version,
            region=region,
            seed=seed,
            timestamp=timestamp,
            p_error=p_error,
            avg_latency=avg_latency,
            run_id=run_id,
            task_id=task_id,
        )

        instance_request.additional_properties = d
        return instance_request

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
