"""Which PyNIDM the app's NIDM conversion runs, and a build check of it.

Run as a script at the end of an image build (Dockerfile, Singularity
%post), it exits non-zero unless:

- `nidm` imports from this interpreter's site-packages, from the files of the
  installed pynidm distribution, and that distribution is PYNIDM_VERSION
  (the version requirements.txt pins);
- `csv2nidm` is on PATH, and the interpreter named in its shebang imports
  that same `nidm`.

A failed or partial pip install, a second PyNIDM elsewhere on the path, or a
csv2nidm from another environment would otherwise only show up when a job
converts its first IQMs. The app logs pynidm_installation() once per run.
"""
import os
import shutil
import site
import subprocess
import sys

# Must equal the pynidm== pin in requirements.txt (tests/test_build_post_fails.py).
PYNIDM_VERSION = "5.0.0"

_NIDM_LOCATION = "import os, nidm; print(os.path.realpath(os.path.dirname(nidm.__file__)))"


def pynidm_installation():
    """(version, package directory) of the installed pynidm distribution,
    read from its metadata without importing nidm; (None, None) if absent."""
    from importlib import metadata

    try:
        dist = metadata.distribution("pynidm")
    except metadata.PackageNotFoundError:
        return None, None
    return dist.version, os.path.realpath(str(dist.locate_file("nidm")))


def shebang_interpreter(script):
    """argv of the interpreter a script's #! line names (env resolved on PATH)."""
    with open(script, "rb") as f:
        first = f.readline().decode(errors="replace").strip()
    if not first.startswith("#!"):
        return None
    words = first[2:].split()
    if words and os.path.basename(words[0]) == "env" and len(words) > 1:
        found = shutil.which(words[1])
        return [found] + words[2:] if found else None
    return words or None


def problems():
    """Why the image's PyNIDM is not what the app needs; empty when it is."""
    try:
        import nidm
    except ImportError as e:
        return [f"nidm does not import: {e}"]
    imported = os.path.realpath(os.path.dirname(nidm.__file__))
    version, installed = pynidm_installation()
    site_dirs = {os.path.realpath(p) for p in site.getsitepackages()}
    found = []
    if version is None:
        found.append("no pynidm distribution is installed")
    elif version != PYNIDM_VERSION:
        found.append(f"pynidm is {version}, not {PYNIDM_VERSION}")
    if installed is not None and imported != installed:
        found.append(f"nidm imports from {imported}, not from pynidm's {installed}")
    if os.path.dirname(imported) not in site_dirs:
        found.append(f"nidm imports from {imported}, outside site-packages {sorted(site_dirs)}")

    csv2nidm = shutil.which("csv2nidm")
    if csv2nidm is None:
        return found + ["csv2nidm is not on PATH"]
    interpreter = shebang_interpreter(csv2nidm)
    if interpreter is None:
        return found + [f"{csv2nidm} names no interpreter"]
    run = subprocess.run(interpreter + ["-c", _NIDM_LOCATION],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if run.returncode != 0:
        found.append(f"{csv2nidm}'s interpreter {interpreter[0]} cannot import nidm: "
                     + (run.stderr.strip().splitlines() or ["no error output"])[-1])
    elif run.stdout.strip() != imported:
        found.append(f"{csv2nidm} runs nidm from {run.stdout.strip()}, not {imported}")
    return found


def main():
    found = problems()
    if found:
        sys.exit("PyNIDM build check failed: " + "; ".join(found))
    version, installed = pynidm_installation()
    print(f"PyNIDM {version} from {installed}; csv2nidm {shutil.which('csv2nidm')} runs it")


if __name__ == "__main__":
    main()
