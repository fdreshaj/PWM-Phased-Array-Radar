import pcbnew
import math
import numpy as np

# ─── Design Parameters (mm) ──────────────────────────────────────────────────
A           = 0.05      # half of Wmin
p           = 0.25      # GUI
L           = 16.0      # GUI
W_max       = 8.5      # GUI
f_w         = 1.1      # GUI
f_l         = 10.0      # feed line length
stub_m      = 2.59      # open microstrip stub length (λm/4 at 17GHz)
stub_r      = 2.9      # GUI
stub_angle  = 90.0      # GUI
margin      = 1.500      # GUI
N           = 200       # taper polygon resolution
N_stub      = 64        # radial stub arc resolution

# ─── Clear board ─────────────────────────────────────────────────────────────
board = pcbnew.GetBoard()
for zone in board.Zones():
    board.Remove(zone)
for track in board.GetTracks():
    board.Remove(track)
pcbnew.Refresh()

# ─── Origin ──────────────────────────────────────────────────────────────────
# ox, oy = throat center (x=0 of antenna, centerline y)
# ALL geometry references this single point so everything is flush
bbox = board.GetBoardEdgesBoundingBox()
ox   = pcbnew.ToMM(bbox.GetCenter().x)
oy   = pcbnew.ToMM(bbox.GetCenter().y)
print(f"Throat origin: ({ox:.2f}, {oy:.2f}) mm")

half_wmax = W_max / 2.0

# ─── Helpers ─────────────────────────────────────────────────────────────────
def add_filled_zone(vertices_mm, layer, board):
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    outline = zone.Outline()
    outline.NewOutline()
    for (x, y) in vertices_mm:
        outline.Append(pcbnew.FromMM(float(x)), pcbnew.FromMM(float(y)))
    board.Add(zone)
    return zone

def add_cutout_zone(vertices_mm, layer, board):
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetIsRuleArea(True)
    zone.SetDoNotAllowCopperPour(True)
    zone.SetDoNotAllowVias(True)
    zone.SetDoNotAllowTracks(True)
    outline = zone.Outline()
    outline.NewOutline()
    for (x, y) in vertices_mm:
        outline.Append(pcbnew.FromMM(float(x)), pcbnew.FromMM(float(y)))
    board.Add(zone)
    return zone

def add_rect_zone(x0, y0, x1, y1, layer, board):
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    outline = zone.Outline()
    outline.NewOutline()
    outline.Append(pcbnew.FromMM(float(x0)), pcbnew.FromMM(float(y0)))
    outline.Append(pcbnew.FromMM(float(x1)), pcbnew.FromMM(float(y0)))
    outline.Append(pcbnew.FromMM(float(x1)), pcbnew.FromMM(float(y1)))
    outline.Append(pcbnew.FromMM(float(x0)), pcbnew.FromMM(float(y1)))
    board.Add(zone)
    return zone

def radial_stub_vertices(cx, cy, radius, angle_deg, direction, n):
    """
    Fan-shaped polygon centered exactly at (cx, cy).
    direction='up'   → fan grows in -y (KiCad Y is flipped: -y = upward on screen)
    direction='down' → fan grows in +y
    The center point cx,cy must equal the feed/slot crossing point.
    """
    half  = math.radians(angle_deg / 2.0)
    # KiCad Y axis is inverted vs screen:
    #   'up' on screen   = -y in KiCad coords → base angle = +pi/2
    #   'down' on screen = +y in KiCad coords → base angle = -pi/2
    base  = math.pi / 2.0 if direction == 'up' else -math.pi / 2.0
    verts = [(cx, cy)]
    for i in range(n + 1):
        theta = base - half + (2 * half * i / n)
        verts.append((
            cx + radius * math.cos(theta),
            cy + radius * math.sin(theta)
        ))
    verts.append((cx, cy))
    return verts

# ─── Taper vertices ───────────────────────────────────────────────────────────
x_vals = np.linspace(0, L, N)
y_top  = [min(A * math.exp(p * x), half_wmax) for x in x_vals]
y_bot  = [-y for y in y_top]

# ─── 1. Solid copper rectangle (F.Cu ground plane) ───────────────────────────
# Spans feed line start → aperture end, height = W_max + margin each side
rect = [
    (ox - f_l,  oy - half_wmax - margin),
    (ox + L,    oy - half_wmax - margin),
    (ox + L,    oy + half_wmax + margin),
    (ox - f_l,  oy + half_wmax + margin),
]
add_filled_zone(rect, pcbnew.F_Cu, board)
print("  [1] F.Cu ground plane added")

# ─── 2. Slot cutout (exponential flare) ──────────────────────────────────────
slot = []
slot += [(ox + x_vals[i], oy + y_top[i]) for i in range(N)]
slot += [(ox + x_vals[i], oy + y_bot[i]) for i in range(N-1, -1, -1)]
add_cutout_zone(slot, pcbnew.F_Cu, board)
print("  [2] Exponential slot cutout added")

# ─── 3. Radial stub on F.Cu (slot-side short circuit) ────────────────────────
# Center = throat = (ox, oy). Extends upward (screen up = -y in KiCad).
# This is the wideband virtual short for the slot line termination.
rs_fcu = radial_stub_vertices(
    cx        = ox,
    cy        = oy,
    radius    = stub_r,
    angle_deg = stub_angle,
    direction = 'up',
    n         = N_stub
)
add_filled_zone(rs_fcu, pcbnew.F_Cu, board)
print(f"  [3] Radial stub F.Cu: center=({ox:.2f},{oy:.2f}), r={stub_r}mm, angle={stub_angle}°, up")

# ─── 4. Microstrip feed line (B.Cu) ──────────────────────────────────────────
# Runs from x = ox-f_l to x = ox (throat), centered on oy.
# Right edge terminates flush at the throat x = ox.
add_rect_zone(
    ox - f_l,          # left edge: SMA end
    oy - f_w / 2.0,    # top edge: centered on oy
    ox,                # right edge: exactly at throat
    oy + f_w / 2.0,    # bottom edge: centered on oy
    pcbnew.B_Cu, board
)
print(f"  [4] Feed line B.Cu: x=[{ox-f_l:.2f}, {ox:.2f}], y=[{oy-f_w/2:.3f}, {oy+f_w/2:.3f}]")

# ─── 5. Open microstrip stub (B.Cu) ──────────────────────────────────────────
# Perpendicular stub on B.Cu, growing downward from throat (screen down = +y in KiCad).
# Left/right edges centered on ox (same x-center as feed line and radial stub).
# Top edge starts at oy (flush with feed line centerline = throat).
add_rect_zone(
    ox - f_w / 2.0,    # left edge: centered on throat x
    oy,                # top edge: starts exactly at throat centerline
    ox + f_w / 2.0,    # right edge: centered on throat x
    oy + stub_m,       # bottom edge: stub_m below throat
    pcbnew.B_Cu, board
)
print(f"  [5] Open stub B.Cu: x=[{ox-f_w/2:.3f}, {ox+f_w/2:.3f}], y=[{oy:.2f}, {oy+stub_m:.2f}]")

# ─── Fill and refresh ────────────────────────────────────────────────────────
board.BuildConnectivity()
filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
pcbnew.Refresh()

print("")
print("Done.")
print(f"  Throat     : ({ox:.2f}, {oy:.2f}) mm  ← all elements share this origin")
print(f"  Taper      : y = {A}*exp({p}*x), x in [0, {L}] mm")
print(f"  Aperture   : ±{half_wmax} mm")
print(f"  Slot throat: Wmin = {A*2} mm")
print(f"  Feed line  : {f_w}mm wide, {f_l}mm long on B.Cu, right edge at x={ox:.2f}")
print(f"  Open stub  : {stub_m}mm long on B.Cu, top edge at y={oy:.2f}, centered at x={ox:.2f}")
print(f"  Radial stub: r={stub_r}mm, {stub_angle}° on F.Cu, centered at ({ox:.2f},{oy:.2f})")