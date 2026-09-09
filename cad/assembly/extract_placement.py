"""Extract footprint placement + 3D model paths from the routed PCB.

Writes pcb_assembly.json — input for build_assembly.py (CadQuery side).
Decouples pcbnew (system Python) from cadquery (.venv).
"""

import json
import os
from pathlib import Path

import pcbnew

PCB_PATH = Path("cad/dlr_carrier.kicad_pcb")
OUT_PATH = Path("cad/assembly/pcb_assembly.json")

# Named groups for the GLB hierarchy. Matched by ref prefix or exact ref.
# Drives material spec + explode offsets in the bake pipeline.
GROUPS: dict[str, list[str]] = {
    "cm4_socket": ["J5", "C14", "C15", "C16", "C17"],
    "cellular_modem": ["U3", "C18", "C19", "C20", "C21", "C22", "R5"],
    "cellular_io": ["U4", "J6", "J7", "C23", "C24", "R6", "R7"],
    "vision_thermal": ["J8"],
    "atmospherics": [
        "J9",
        "J10",
        "U5",
        "U6",
        "C25",
        "C26",
        "C27",
        "C28",
        "C29",
        "R8",
        "R9",
        "R10",
        "R11",
    ],
    "power_harvest": [
        "J1",
        "U8",
        "L1",
        "R1",
        "D1",
        "D4",
        "Q1",
        "Q2",
        "C1",
        "C2",
        "C3",
        "C31",
        "C32",
        "C33",
        "C34",
        "C35",
        "R17",
        "R18",
        "R19",
        "R20",
        "R21",
        "R22",
        "R23",
        "R24",
        "R25",
    ],
    "power_buck": ["U9", "L2", "C7", "C4", "C5", "C6", "C8", "C9", "C36", "R2", "R3"],
    "power_ldo": ["U1", "U2", "C10", "C11", "C12", "C13"],
    "bat_terminal": ["J3"],
    "debug_header": ["J11"],
    "commissioning_usb": ["J12", "R12", "R13"],
    "anemometer_port": ["U7", "J13", "C30", "R14", "R15", "R16", "D2", "D3", "F1"],
}


def _resolve_model_path(raw: str) -> str | None:
    """Expand ${KICAD9_3DMODEL_DIR} and similar env vars in the model path."""
    candidates = ["KICAD9_3DMODEL_DIR", "KICAD8_3DMODEL_DIR", "KICAD7_3DMODEL_DIR"]
    fallback = "/usr/share/kicad/3dmodels"
    for var in candidates:
        os.environ.setdefault(var, fallback)
    expanded = os.path.expandvars(raw)
    return expanded if Path(expanded).exists() else None


def main() -> None:
    """Walk the board, write JSON of footprint placements and 3D models."""
    ref_to_group = {ref: g for g, refs in GROUPS.items() for ref in refs}
    board = pcbnew.LoadBoard(str(PCB_PATH))
    bb = board.GetBoardEdgesBoundingBox()

    out: dict = {
        "board": {
            "left_mm": pcbnew.ToMM(bb.GetLeft()),
            "top_mm": pcbnew.ToMM(bb.GetTop()),
            "width_mm": pcbnew.ToMM(bb.GetWidth()),
            "height_mm": pcbnew.ToMM(bb.GetHeight()),
            "thickness_mm": 1.6,
        },
        "groups": {g: [] for g in GROUPS},
        "ungrouped": [],
    }

    footprints = board.Footprints()
    # Reason: KiCad 10 SWIG iterators lack `.next()` on Python 3.14 — index instead
    for fp in (footprints[i] for i in range(len(footprints))):
        ref = fp.GetReference()
        models = fp.Models()
        models = [models[i] for i in range(len(models))]
        if not models:
            continue
        path = _resolve_model_path(models[0].m_Filename)
        pos = fp.GetPosition()
        fbb = fp.GetBoundingBox(False, False)
        entry = {
            "ref": ref,
            "value": fp.GetValue(),
            "x_mm": pcbnew.ToMM(pos.x),
            "y_mm": pcbnew.ToMM(pos.y),
            "rotation_deg": fp.GetOrientationDegrees(),
            "flipped": fp.IsFlipped(),
            "model_path": path,  # may be None — build_assembly.py synthesizes a box
            "bbox_w_mm": pcbnew.ToMM(fbb.GetWidth()),
            "bbox_h_mm": pcbnew.ToMM(fbb.GetHeight()),
        }
        group = ref_to_group.get(ref, "ungrouped")
        if group == "ungrouped":
            out["ungrouped"].append(entry)
        else:
            out["groups"][group].append(entry)

    OUT_PATH.write_text(json.dumps(out, indent=2))
    grouped = sum(len(v) for v in out["groups"].values())
    print(f"Wrote {OUT_PATH}: {grouped} grouped + {len(out['ungrouped'])} ungrouped")


if __name__ == "__main__":
    main()
