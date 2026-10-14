from enum import StrEnum


class Header(StrEnum):
    KEY = "x-egress-key"
    TARGET = "x-egress-target"
    FAILURE = "x-egress-failure"


class Failure(StrEnum):
    UNAUTHORIZED = "unauthorized"
    INVALID = "invalid"
    TIMEOUT = "timeout"
    UNREACHABLE = "unreachable"
