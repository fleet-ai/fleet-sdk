from enum import Enum


class InstanceStatus(str, Enum):
    ERROR = "error"
    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"

    def __str__(self) -> str:
        return str(self.value)
