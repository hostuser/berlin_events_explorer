from typing import IO, Any
import builtins

"""Top-level package for the Berlin Events Explorer project."""

__author__ = "Markus Binsteiner"
__email__ = "markus@frkl.dev"

try:
    from rich import inspect  # ty: ignore[unresolved-import]
    from rich import (  # ty: ignore[unresolved-import,unused-ignore-comment]
        print as rich_print,
    )

    setattr(builtins, "insp", inspect)

    def dbg(
        *objects: Any,
        sep: str = " ",
        end: str = "\n",
        file: IO[str] | None = None,
        flush: bool = False,
    ) -> None:
        for obj in objects:
            try:
                rich_print(obj, sep=sep, end=end, file=file, flush=flush)
            except Exception:
                rich_print(
                    f"[green]{obj}[/green]", sep=sep, end=end, file=file, flush=flush
                )

    setattr(builtins, "dbg", dbg)

except ImportError:  # Graceful fallback if Rich isn't installed.
    pass

try:
    from devtools import debug  # ty: ignore[unresolved-import,unused-ignore-comment]

    def DBG(
        *objects: Any,
        sep: str = " ",
        end: str = "\n",
        file: IO[str] | None = None,
        flush: bool = False,
    ) -> None:

        return debug(*objects)

    setattr(builtins, "DBG", DBG)
except ImportError:  # Graceful fallback if DevTools isn't installed.
    pass

try:
    from icecream import ic  # ty: ignore[unresolved-import,unused-ignore-comment]

    setattr(builtins, "ic", ic)
except ImportError:  # Graceful fallback if IceCream isn't installed.
    pass

try:
    from wat import wat  # ty: ignore[unresolved-import,unused-ignore-comment]

    setattr(builtins, "wats", wat.s)
    setattr(builtins, "wat", wat)
except ImportError:  # Graceful fallback if IceCream isn't installed.
    pass

try:
    import snoop  # ty: ignore[unresolved-import,unused-ignore-comment]

    snoop.install()
except ImportError:  # Graceful fallback if Snoop isn't installed.
    pass
