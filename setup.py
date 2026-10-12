import json
import subprocess
import sys
from pathlib import Path

from setuptools import find_packages, setup


def get_version():
    """Read version from VERSION file"""
    version_file = Path(__file__).parent / "VERSION"
    with open(version_file) as f:
        data = json.load(f)
        return data["mriqc-nidm"]["version"]


def read_requirements():
    """Read dependencies from requirements.txt"""
    with open('requirements.txt') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]


def git_revision():
    """Commit of the working tree, with "-dirty" if tracked files differ from it.

    Stamped into the image as org.opencontainers.image.revision.
    """
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--"]).returncode != 0
    return sha + ("-dirty" if dirty else "")


def commit_build_arg():
    """The --build-arg that sets the image's revision label."""
    return ["--build-arg", f"GIT_COMMIT={git_revision()}"]


# Shown in the manual build commands printed below.
BUILD_ARG_HINT = "--build-arg GIT_COMMIT=$(git rev-parse HEAD)"


def build_docker():
    """Build Docker container"""
    print("Building Docker image...")
    try:
        subprocess.run(
            ["docker", "build", *commit_build_arg(), "-t", "mriqc-nidm_bidsapp", "."],
            check=True,
        )
        print("Docker image built successfully")
    except subprocess.CalledProcessError as e:
        print(f"Docker build failed: {e}")
        return False
    return True


def build_singularity(output_path=None):
    """Build Singularity/Apptainer container"""
    print("Building container image...")
    try:
        # Check for apptainer first (more common on clusters), then singularity
        if (
            subprocess.run(["which", "apptainer"], capture_output=True).returncode == 0
        ):
            print("\nDetected Apptainer on cluster environment.")
            print("For cluster environments, please build directly with apptainer:")
            print(
                f"\napptainer build --remote {BUILD_ARG_HINT} "
                "mriqc-nidm_bidsapp.sif Singularity"
            )
            print("or")
            print(
                f"apptainer build --fakeroot {BUILD_ARG_HINT} "
                "mriqc-nidm_bidsapp.sif Singularity\n"
            )
            return False
        elif (
            subprocess.run(["which", "singularity"], capture_output=True).returncode == 0
        ):
            container_cmd = "singularity"
        else:
            print("Neither apptainer nor singularity found. Cannot build image.")
            return False

        # Use custom output path if provided, otherwise use default
        output_file = output_path if output_path else "mriqc-nidm_bidsapp.sif"
        output_file = str(Path(output_file).resolve())

        # Build command
        cmd = [container_cmd, "build", *commit_build_arg()]

        # For regular Singularity installations, try fakeroot if available
        if subprocess.run(["which", "fakeroot"], capture_output=True).returncode == 0:
            cmd.append("--fakeroot")

        # Add output file and Singularity definition
        cmd.extend([output_file, "Singularity"])

        print(f"Running command: {' '.join(cmd)}")

        # Run the build command
        subprocess.run(cmd, check=True)
        print(f"Container image built successfully at: {output_file}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Build failed: {e}")
        print("\nFor cluster environments, please build directly with apptainer:")
        print(
            f"apptainer build --remote {BUILD_ARG_HINT} "
            "mriqc-nidm_bidsapp.sif Singularity"
        )
        print("or")
        print(
            f"apptainer build --fakeroot {BUILD_ARG_HINT} "
            "mriqc-nidm_bidsapp.sif Singularity"
        )
        return False


# Read dependencies from requirements.txt to maintain single source of truth
install_requires = read_requirements()

# Check if we're being called with a container build command
if len(sys.argv) > 1 and sys.argv[1] in ["docker", "singularity", "containers"]:
    command = sys.argv[1]
    # Remove the custom argument so setup() doesn't see it
    sys.argv.pop(1)

    if command == "docker":
        build_docker()
    elif command == "singularity":
        # Check for custom output path in the next argument
        output_path = None
        if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
            output_path = sys.argv.pop(1)
        build_singularity(output_path)
    elif command == "containers":
        build_docker()
        build_singularity()

    # Exit if we were just building containers
    if len(sys.argv) == 1:
        sys.exit(0)

setup(
    name="mriqc-nidm",
    version=get_version(),
    description="BIDS App for MRIQC with NIDM Output",
    author="ReproNim",
    author_email="repronim@gmail.com",
    packages=find_packages(exclude=["tests", "tests.*"]),
    include_package_data=True,
    license="MIT",
    url="https://github.com/sensein/mriqc-nidm_bidsapp",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Medical Science Apps.",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    entry_points={
        "console_scripts": [
            "mriqc-nidm=src.run:main",
        ],
    },
    python_requires=">=3.9",
    install_requires=install_requires,
)
