from enum import IntEnum, auto

class SpotSize(IntEnum):
    SMALL = auto()   # 1
    MEDIUM = auto()  # 2
    LARGE = auto()   # 3

    def can_hold(self, needed: "SpotSize") -> bool:
        return self >= needed