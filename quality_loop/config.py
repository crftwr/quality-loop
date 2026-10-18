"""A product's quality-loop settings: ``qa/quality-loop.toml``.

```toml
command = ".venv/bin/quality-loop"   # which installation the conductor uses
command_windows = ".venv/Scripts/quality-loop.exe"   # the same, on Windows
adapter = "qa/run.py:Product"        # the adapter: a file, and optionally its class
rooms = "rooms"                      # where runs are kept (default: the adapter's)
```

Paths are relative to the product's checkout, the directory holding ``qa/``.
`quality-loop init` writes the file; the adapter line is written once there
is an adapter.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import inspect
import os
import pathlib
import sys
import tomllib

NAMES = (pathlib.Path("qa") / "quality-loop.toml", pathlib.Path("quality-loop.toml"))


class ConfigError(Exception):
    pass


@dataclasses.dataclass
class Config:
    path: pathlib.Path | None
    root: pathlib.Path
    values: dict

    @property
    def command(self) -> str:
        """The quality-loop command: the settings file is committed and
        shared across OSes, and a venv's scripts live in different places."""
        if os.name == "nt" and self.values.get("command_windows"):
            return self.values["command_windows"]
        return self.values.get("command", "quality-loop")

    @property
    def adapter_spec(self) -> str | None:
        return self.values.get("adapter")

    def rooms(self, adapter=None) -> pathlib.Path:
        if self.values.get("rooms"):
            return (self.root / self.values["rooms"]).resolve()
        if adapter is None:
            adapter = load_adapter(self)
        return pathlib.Path(adapter.rooms)


def find(start: pathlib.Path | None = None, explicit: str | None = None) -> Config:
    """The settings for the checkout ``start`` is in."""
    if explicit:
        path = pathlib.Path(explicit).resolve()
        return _read(path)
    here = pathlib.Path(start or os.getcwd()).resolve()
    for directory in [here, *here.parents]:
        for name in NAMES:
            if (directory / name).is_file():
                return _read(directory / name)
    return Config(path=None, root=here, values={})


def _read(path: pathlib.Path) -> Config:
    try:
        values = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"{path}: {error}") from None
    root = path.parent.parent if path.parent.name == "qa" else path.parent
    return Config(path=path, root=root, values=values)


def load_adapter(config: Config):
    """An instance of the adapter the settings name.

    ``qa/run.py:Product`` names the class; ``qa/run.py`` alone takes the one
    Adapter subclass the file defines. The file is imported under its own
    name with its directory on sys.path, as running it would.
    """
    from quality_loop import adapter as base

    spec = config.adapter_spec
    if not spec:
        raise ConfigError(f"no adapter in {config.path or 'qa/quality-loop.toml'} - "
                          f'add adapter = "qa/run.py:Product"')
    file, _colon, name = spec.partition(":")
    path = (config.root / file).resolve()
    if not path.is_file():
        raise ConfigError(f"the adapter {path} does not exist")
    sys.path.insert(0, str(path.parent))
    module_name = path.stem
    loaded = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(loaded)
    sys.modules[module_name] = module
    loaded.loader.exec_module(module)
    if name:
        cls = getattr(module, name, None)
        if cls is None:
            raise ConfigError(f"{path} has no {name}")
    else:
        found = [c for _n, c in inspect.getmembers(module, inspect.isclass)
                 if issubclass(c, base.Adapter) and c is not base.Adapter
                 and c.__module__ == module_name]
        if len(found) != 1:
            raise ConfigError(f"{path} defines {len(found)} Adapter subclasses - name one: "
                              f'adapter = "{file}:<Class>"')
        cls = found[0]
    return cls()
