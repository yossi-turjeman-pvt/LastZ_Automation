"""
Fix Hebrew / RTL text in a CrossOver bottle (fonts + he_IL locale).

Copies Hebrew-capable macOS fonts into the bottle's Windows Fonts folder and
sets LANG/LC_ALL=he_IL.UTF-8 in cxbottle.conf. Idempotent — safe to re-run.
"""
from __future__ import annotations

import shutil
from pathlib import Path

DEFAULT_BOTTLE_NAME = "Last Z"
CROSSOVER_BOTTLES = Path.home() / "Library/Application Support/CrossOver/Bottles"

# macOS system fonts that cover Hebrew well enough for Wine/Unity chat
FONT_SOURCES: list[Path] = [
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf"),
]

LOCALE = "he_IL.UTF-8"
ENV_KEYS = ("LANG", "LC_ALL")


def bottle_path(name: str | None = None) -> Path:
    cfg_name = name
    if cfg_name is None:
        try:
            from lastz.config import load_config

            cfg_name = load_config().get("crossover", {}).get("bottle_name")
        except Exception:
            cfg_name = None
    return CROSSOVER_BOTTLES / (cfg_name or DEFAULT_BOTTLE_NAME)


def list_bottles() -> list[str]:
    if not CROSSOVER_BOTTLES.is_dir():
        return []
    return sorted(p.name for p in CROSSOVER_BOTTLES.iterdir() if p.is_dir())


def _set_env_vars(conf_text: str, updates: dict[str, str]) -> tuple[str, list[str]]:
    """Insert or update keys under [EnvironmentVariables]. Returns (text, actions)."""
    lines = conf_text.splitlines(keepends=True)
    actions: list[str] = []
    section_idx: int | None = None
    next_section: int | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[EnvironmentVariables]":
            section_idx = i
            continue
        if section_idx is not None and next_section is None:
            if stripped.startswith("[") and stripped.endswith("]"):
                next_section = i
                break

    if section_idx is None:
        # Append a new section at end of file
        body = conf_text
        if body and not body.endswith("\n"):
            body += "\n"
        body += "\n[EnvironmentVariables]\n"
        for key, value in updates.items():
            body += f'"{key}" = "{value}"\n'
            actions.append(f"added {key}={value}")
        return body, actions

    end = next_section if next_section is not None else len(lines)
    section_lines = lines[section_idx + 1 : end]
    found: dict[str, int] = {}

    for j, line in enumerate(section_lines):
        stripped = line.strip()
        for key in updates:
            # Match: "LANG" = "..."
            if stripped.startswith(f'"{key}"') and "=" in stripped:
                found[key] = j
                break

    for key, value in updates.items():
        new_line = f'"{key}" = "{value}"\n'
        if key in found:
            old = section_lines[found[key]].rstrip("\n")
            if old.strip() == new_line.strip():
                actions.append(f"{key} already set")
            else:
                section_lines[found[key]] = new_line
                actions.append(f"updated {key}={value}")
        else:
            # Insert after the section header (top of env block)
            section_lines.insert(0, new_line)
            # Shift later found indexes
            for k in list(found):
                found[k] += 1
            found[key] = 0
            actions.append(f"added {key}={value}")

    new_lines = lines[: section_idx + 1] + section_lines + lines[end:]
    return "".join(new_lines), actions


def _copy_fonts(fonts_dir: Path) -> list[str]:
    fonts_dir.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []
    for src in FONT_SOURCES:
        if not src.is_file():
            actions.append(f"skip missing source: {src.name}")
            continue
        dest = fonts_dir / src.name
        if dest.is_file() and dest.stat().st_size == src.stat().st_size:
            actions.append(f"font ok: {src.name}")
            continue
        shutil.copy2(src, dest)
        actions.append(f"copied font: {src.name}")
    return actions


def apply_hebrew_fix(*, bottle_name: str | None = None) -> int:
    """
    Apply fonts + locale fix. Returns 0 on success, 1 on failure.
    Prints a short human-readable report.
    """
    path = bottle_path(bottle_name)
    conf = path / "cxbottle.conf"
    fonts_dir = path / "drive_c" / "windows" / "Fonts"

    print(f"Bottle: {path}")

    if not path.is_dir():
        print("[!] Bottle not found.")
        available = list_bottles()
        if available:
            print("    Available bottles:")
            for name in available:
                print(f"      - {name}")
            print('    Set crossover.bottle_name in config.yaml if needed.')
        else:
            print("    No CrossOver bottles under:")
            print(f"      {CROSSOVER_BOTTLES}")
        return 1

    if not conf.is_file():
        print(f"[!] Missing cxbottle.conf at {conf}")
        return 1

    font_actions = _copy_fonts(fonts_dir)
    for line in font_actions:
        print(f"  {line}")

    text = conf.read_text(encoding="utf-8")
    new_text, env_actions = _set_env_vars(
        text,
        {key: LOCALE for key in ENV_KEYS},
    )
    for line in env_actions:
        print(f"  {line}")

    if new_text != text:
        conf.write_text(new_text, encoding="utf-8")
        print("  wrote cxbottle.conf")
    else:
        print("  cxbottle.conf unchanged")

    print()
    print("Done. Fully quit CrossOver / the game, then relaunch the bottle.")
    print("This is a one-time setup (fonts + he_IL locale). Re-run only if you")
    print("recreate the bottle — not needed for normal day-to-day play.")
    return 0


if __name__ == "__main__":
    raise SystemExit(apply_hebrew_fix())
