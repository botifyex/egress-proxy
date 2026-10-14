from importlib import import_module


class Missing(ModuleNotFoundError):
    pass


def require(library: str, extra: str) -> None:
    try:
        import_module(library)
    except ModuleNotFoundError as error:
        raise Missing(f"{library} is not installed: pip install 'egress-proxy[{extra}]'") from error
