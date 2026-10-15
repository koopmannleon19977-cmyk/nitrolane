# Third-party notices

arc-lane builds on two MIT projects. Their code is not vendored in this repository;
`setup.ps1` clones them at a pinned commit and applies `patches/`.

- **arc-cua** — https://github.com/shhivv/arc-cua — MIT License, Copyright (c) Shiv Shanmugam.
  The decision-model action layer, Chrome backend, runtime and safety model.
- **arc-cua-windows** — https://github.com/GreenKeewi/arc-cua-windows — MIT License.
  Public Windows fork of arc-cua adding the foreground Windows UIA backend.
  Pinned commit: `659696da0134ae4946a40da76fc0ca6d56f292b7`.
  Local modifications are documented in `patches/LOCAL_PATCHES.md` and shipped as
  `patches/arc-cua-windows-local.patch`.

Runtime dependencies installed by the fork's own packaging (pywinauto, comtypes,
httpx and others) keep their respective licenses.

JEV decisions are provided by the hosted TypeSafe service; you need your own API key.
No keys or credentials are contained in this repository.
