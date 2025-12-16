from enum import Enum, unique

@unique
class Role(str, Enum):
    ADMIN  = "admin"
    USER   = "user"
