from abc import ABC
from ..env.models import Resource as ResourceModel, ResourceType, ResourceMode


class Resource(ABC):
    def __init__(self, resource: ResourceModel):
        self.resource = resource

    @property
    def uri(self) -> str:
        return f"{self.resource.type}://{self.resource.name}"

    @property
    def name(self) -> str:
        return self.resource.name

    @property
    def type(self) -> ResourceType:
        return self.resource.type

    @property
    def mode(self) -> ResourceMode:
        return self.resource.mode
