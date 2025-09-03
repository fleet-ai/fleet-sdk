from abc import ABC
from ..instance.models import Resource as ResourceModel, ResourceType, ResourceMode


class Resource(ABC):
    def __init__(self, resource: ResourceModel):
        self.resource = resource

    @property
    def uri(self) -> str:
        return f"{self.resource.type.value}://{self.resource.name}"

    @property
    def name(self) -> str:
        return self.resource.name

    @property
    def type(self) -> ResourceType:
        return self.resource.type

    @property
    def mode(self) -> ResourceMode:
        return self.resource.mode

    def __repr__(self) -> str:
        return f"Resource(uri={self.uri}, mode={self.mode.value})"
