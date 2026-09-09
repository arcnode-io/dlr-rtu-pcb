"""Root sheet: one sheet symbol per functional block + cross-net sheet pins.

Every coordinate is a multiple of the 1.27 mm connection grid — anything else
makes ERC flag each sheet-pin stub as `endpoint_off_grid`. Power nets need no
sheet pins (power symbols are global); no PWR_FLAG lives here either — the
flags sit on the POWER child sheet, anchored to real pins (see multi_sheet).
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Final

import kicad_sch_api as ksa

from cad.schematic.multi_sheet import SHEET_PIN_TYPE
from cad.schematic.schematic import BLOCK_TITLES

ROOT_SHEET_SIZE: Final = (
    "A2"  # 594x420 mm; fits 4x2 sheet symbols left of the title block
)
GRID_MM: Final = 1.27
COLS: Final = 4
CELL_W: Final = 56 * GRID_MM
CELL_H: Final = 102 * GRID_MM
GAP: Final = 24 * GRID_MM
TITLE_BLOCK_LEFT_MM: Final = 445.0  # A2 title block occupies bottom-right ~150x60 mm
SHEET_H_MM: Final = 420.0
PIN_MARGIN: Final = 4 * GRID_MM  # first / last sheet pin inset from the symbol corners
PIN_PITCH: Final = 2 * GRID_MM
STUB: Final = 10 * GRID_MM  # wire from sheet pin outward to its label


def _snap(v: float) -> float:
    return round(v / GRID_MM) * GRID_MM


def link_hierarchy(root_path: str, pages: dict[str, tuple[str, int]]) -> None:
    """Repair the hierarchy metadata kicad-sch-api emits.

    Two defects, both invisible to KiCad 10 and fatal to KiCad 9 — which cannot
    resolve the hierarchy and then reports every sheet pin as having no matching
    hierarchical label and every root label as dangling:

      * the root's sheet instance block is written as `(project None ...)`, with a
        literal Python None where the project name belongs
      * every child declares `(sheet_instances (path "/" (page "1")))`, i.e. each
        one claims to be the root page, instead of its own instance path and page

    `pages` maps child filename -> (sheet symbol uuid, page number).
    """
    root = Path(root_path)
    project = root.stem
    text = root.read_text()
    text = text.replace("(project None", f'(project "{project}"')
    root.write_text(text)

    for filename, (uuid, page) in pages.items():
        child = root.parent / filename
        body = child.read_text()
        body = re.sub(
            r'\(sheet_instances\s*\n\s*\(path "[^"]*"\s*\n\s*\(page "[^"]*"\)\s*\n\s*\)\s*\n\s*\)',
            f'(sheet_instances\n\t\t(path "/{uuid}"\n\t\t\t(page "{page}")\n\t\t)\n\t)',
            body,
            count=1,
        )
        child.write_text(body)


def build_root_sheet(
    block_sheets: list[tuple[str, str, set[str]]],
    sheet_path: str,
    title: str,
    sheet_size: str = ROOT_SHEET_SIZE,
) -> dict[str, tuple[str, int]]:
    """Emit the root .kicad_sch.

    block_sheets: (block_name, child_filename, cross_net_names) per child. Each
    cross net gets a sheet pin plus a same-named label on a short stub, so
    KiCad's same-name-on-one-sheet resolution binds every child's pin for that
    net into a single parent net.
    """
    ksa.use_grid_units(False)  # mm coords; everything below is a GRID_MM multiple
    sch = ksa.create_schematic(title)
    sch.set_paper_size(sheet_size)
    sch.set_title_block(title=title, company="Engineering With AI", rev="1.0")

    grid_w = COLS * CELL_W + (COLS - 1) * GAP
    margin_x = _snap((TITLE_BLOCK_LEFT_MM - grid_w) / 2)
    margin_y = _snap((SHEET_H_MM - 2 * CELL_H - GAP) / 2)
    pages: dict[str, tuple[str, int]] = {}

    for i, (block_name, child_file, child_cross) in enumerate(block_sheets):
        row, col = divmod(i, COLS)
        x = margin_x + col * (CELL_W + GAP)
        y = margin_y + row * (CELL_H + GAP)
        sheet_uuid = sch.add_sheet(
            name=BLOCK_TITLES.get(block_name, block_name.upper()),
            filename=child_file,
            position=(x, y),
            size=(CELL_W, CELL_H),
            stroke_width=0.2,
        )
        pages[child_file] = (sheet_uuid, i + 2)  # root is page 1
        nets_sorted = sorted(child_cross)
        if not nets_sorted:
            continue
        usable = CELL_H - 2 * PIN_MARGIN
        spacing = max(
            PIN_PITCH, math.floor(usable / len(nets_sorted) / PIN_PITCH) * PIN_PITCH
        )
        for j, net_name in enumerate(nets_sorted):
            along = (
                PIN_MARGIN + j * spacing
            )  # measured from the symbol's bottom-left corner
            sch.add_sheet_pin(
                sheet_uuid=sheet_uuid,
                name=net_name,
                pin_type=SHEET_PIN_TYPE,
                edge="left",
                position_along_edge=along,
            )
            pin_y = (y + CELL_H) - along
            sch.add_wire(start=(x, pin_y), end=(x - STUB, pin_y))
            sch.add_label(
                text=net_name,
                position=(x - STUB, pin_y),
                rotation=180,
                size=1.0,
                grid_units=False,
            )

    sch.save_as(sheet_path)
    link_hierarchy(sheet_path, pages)
    return pages
