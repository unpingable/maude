# SPDX-License-Identifier: Apache-2.0
"""Run one closed .pyz in-process and report where every loaded module came from.

Usage: python3 -I -S closure_probe.py REPORT.json PROGRAM.pyz ARG...
(the same flags as the shipped shebang).
The program's stdout, stderr and stdin pass through unchanged. The report
classifies each module as coming from the archive, the interpreter's standard
library, or somewhere else ("outside"). The gate requires "outside" to be empty.
"""

import json
import runpy
import sys
import sysconfig

BASELINE = set(sys.modules)
FORBIDDEN = ("ag_shell_client", "agent_gov", "governor", "classic", "textual", "pydantic")


def main() -> int:
    report_path, program, *arguments = sys.argv[1:]
    stdlib = {sysconfig.get_path("stdlib"), sysconfig.get_path("platstdlib")}
    sys.argv = [program, *arguments]
    code = 0
    try:
        runpy.run_path(program, run_name="__main__")
    except SystemExit as exit_:
        code = exit_.code if isinstance(exit_.code, int) else (0 if exit_.code is None else 1)
        if not isinstance(exit_.code, int) and exit_.code is not None:
            print(exit_.code, file=sys.stderr)
    classes = {"archive": [], "stdlib": [], "builtin_or_frozen": [], "outside": []}
    startup = {name: getattr(sys.modules[name], "__file__", None) for name in sorted(BASELINE) if name in sys.modules}
    for name, module in sorted(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if name == "__main__" or origin == __file__ or name in BASELINE:
            continue
        if origin is None:
            classes["builtin_or_frozen"].append(name)
        elif origin.startswith(program + "/"):
            classes["archive"].append(name)
        elif any(origin.startswith(root + "/") for root in stdlib) and "dist-packages" not in origin:
            classes["stdlib"].append(name)
        else:
            classes["outside"].append(f"{name}={origin}")
    startup_outside = [f"{name}={origin}" for name, origin in startup.items()
                       if origin is not None and origin != __file__
                       and not any(origin.startswith(root + "/") for root in stdlib)]
    forbidden = [name for name in sys.modules if any(part in name.lower() for part in FORBIDDEN)]
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump({"program": program, "arguments": arguments, "exit": code, "python": sys.version,
                   "isolated": bool(sys.flags.isolated), "no_site": bool(sys.flags.no_site),
                   "interpreter_startup_modules": startup, "stdlib_roots": sorted(stdlib),
                   "modules": classes, "startup_outside": startup_outside,
                   "forbidden_loaded": forbidden}, handle, indent=2, sort_keys=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
