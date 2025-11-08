#!/usr/bin/env python3
"""
Safety check wrapper for pyproject.toml

This script extracts dependencies from pyproject.toml and feeds them to safety check.
"""
import re
import subprocess
import sys

# Python 3.6 compatible TOML reading
try:
    if sys.version_info >= (3, 11):
        import tomllib

        HAS_TOMLLIB = True
    else:
        HAS_TOMLLIB = False
except ImportError:
    HAS_TOMLLIB = False


def read_pyproject_toml():
    """Read pyproject.toml and extract dependencies."""
    try:
        if HAS_TOMLLIB:
            # Python 3.11+
            with open("pyproject.toml", "rb") as f:
                data = tomllib.load(f)
            return data.get("project", {}).get("dependencies", [])
        else:
            # Fallback for older Python versions - simple regex parsing
            with open("pyproject.toml", "r") as f:
                content = f.read()

            # Extract dependencies section
            deps_match = re.search(r"dependencies\s*=\s*\[(.*?)\]", content, re.DOTALL)
            if not deps_match:
                return []

            deps_str = deps_match.group(1)
            # Extract quoted strings
            deps = re.findall(r'"([^"]+)"', deps_str)
            return deps

    except FileNotFoundError:
        print("pyproject.toml not found")
        return []
    except Exception as e:
        print(f"Error reading pyproject.toml: {e}")
        return []


def get_installed_versions(package_names):
    """Get installed versions of specific packages using pip freeze."""
    try:
        result = subprocess.run(
            ["pip", "freeze"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
        )

        if result.returncode != 0:
            return {}

        installed = {}
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if "==" in line:
                name, version = line.split("==", 1)
                installed[name.lower()] = f"{name}=={version}"

        return installed

    except Exception as e:
        print(f"Error getting installed versions: {e}")
        return {}


def main():
    """Run safety check on dependencies from pyproject.toml."""
    dependencies = read_pyproject_toml()

    if not dependencies:
        print("No dependencies found in pyproject.toml")
        return 0

    # Extract package names from PEP 508 dependencies
    package_names = []
    for dep in dependencies:
        dep = dep.strip()
        if dep:
            # Extract package name (before any version specifier)
            name = re.split(r"[<>=!]", dep)[0].strip()
            package_names.append(name.lower())

    if not package_names:
        print("No valid dependencies to check")
        return 0

    # Get installed versions for these packages
    installed_versions = get_installed_versions(package_names)

    # Create requirements list with concrete versions
    requirements_lines = []
    for name in package_names:
        if name in installed_versions:
            requirements_lines.append(installed_versions[name])
        else:
            print(f"Warning: Package '{name}' not found in installed packages")

    if not requirements_lines:
        print("No installed packages found to check")
        return 0

    # Run safety check with stdin
    requirements_text = "\n".join(requirements_lines)
    print(f"Checking security for: {', '.join([line.split('==')[0] for line in requirements_lines])}")

    try:
        result = subprocess.run(
            ["safety", "check", "--full-report", "--stdin"],
            input=requirements_text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Print output
        if result.stdout:
            print(result.stdout.decode("utf-8"))
        if result.stderr:
            print(result.stderr.decode("utf-8"), file=sys.stderr)

        return result.returncode

    except subprocess.CalledProcessError as e:
        print(f"Safety check failed: {e}")
        return 1
    except FileNotFoundError:
        print("Safety command not found. Please install: pip install safety")
        return 1


if __name__ == "__main__":
    sys.exit(main())
