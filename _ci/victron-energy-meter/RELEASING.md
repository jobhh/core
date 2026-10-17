# Releasing `victron-energy-meter`

This document describes how to release a new version of `victron-energy-meter` to PyPI.

## Tagging Convention

> [!IMPORTANT]
> **Release tags must be bare semantic versions without a leading `v`** (e.g. `0.2.0`, `1.0.0`).
> Do not use `v`-prefixed tags like `v0.2.0`.

Release tags are directly substituted into `pyproject.toml` during the release workflow to set the package version according to PEP 440.

## Release Process

1. **Verify CI**: Ensure that the `CI` workflow is green on the `main` branch.
2. **Draft a GitHub Release**:
   - Go to GitHub Releases: **Draft a new release**.
   - **Choose a tag**: Enter the new version number as a bare tag (e.g. `0.2.0`).
   - **Target**: `main`.
   - **Title**: Enter the version number (e.g. `0.2.0`).
   - **Description**: Provide release notes / changelog.
3. **Publish the Release**:
   - Click **Publish release**.
   - The `.github/workflows/publish.yml` workflow will automatically trigger, build the wheel and source distribution, and publish the package to PyPI via Trusted Publishing.

## One-time setup: Trusted Publishing

The publish workflow uploads to PyPI without an API token. PyPI has to trust
this repository first:

1. Sign in to [PyPI](https://pypi.org) and open **Your projects** → **Publishing**.
2. Under **Add a new pending publisher**, choose **GitHub** and fill in:
   - **PyPI project name**: `victron-energy-meter`
   - **Owner**: `jobhh`
   - **Repository name**: `victron-energy-meter`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `pypi`
3. In this repository on GitHub, open **Settings** → **Environments** and create
   an environment named `pypi`.

The first published release turns the pending publisher into the project.
