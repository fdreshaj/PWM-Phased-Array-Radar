import sys
import math
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QPushButton, QFrame, QSizePolicy, QStatusBar,
    QDoubleSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QScrollArea, QDialog, QCheckBox, QOpenGLWidget
)
from PyQt5.QtCore import Qt, QRectF, QPointF, QSizeF
from PyQt5.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QFont,
    QFontMetrics, QSurfaceFormat
)

# ── attempt OpenGL import (graceful fallback) ─────────────────────────────────
try:
    from PyQt5.QtWidgets import QOpenGLWidget
    _HAS_OPENGL = True
except ImportError:
    _HAS_OPENGL = False

C_BG             = QColor(18, 18, 20)
C_SURFACE        = QColor(28, 28, 32)
C_SURFACE2       = QColor(34, 34, 40)
C_BORDER         = QColor(55, 55, 62)
C_TEXT           = QColor(220, 220, 225)
C_MUTED          = QColor(130, 130, 140)
C_COPPER         = QColor(184, 115, 18)
C_SLOT           = QColor(12, 12, 14)
C_FEED           = QColor(60, 140, 220)
C_STUB_F         = QColor(210, 90, 40)
C_STUB_B         = QColor(50, 190, 100)
C_ACCENT         = QColor(90, 160, 230)
C_DIM            = QColor(200, 190, 80)
C_BTN_ACTIVE     = QColor(35, 70, 120)
C_BTN_BORDER_ACT = QColor(80, 140, 220)
C_GRID           = QColor(38, 38, 46)

FEED_DESC = {
    'microstrip': 'Microstrip-to-slot (Knorr): λm/4 open stub on B.Cu crosses slot perpendicularly. Widest bandwidth for PCB Vivaldi.',
    'cpw':        'CPW on F.Cu feeds slot directly. No via needed. Good for MMIC.',
    'coax':       'SMA inner conductor forms semicircular loop over slot throat. Narrower bandwidth.'
}
STUB_DESC = {
    'none': 'No radial stub — straight λs/4 short. Narrowest bandwidth, simplest fab.',
    'fcu':  'Radial stub F.Cu (slot side short). Schüppert/Zinieris — best single-layer BW.',
    'bcu':  'Radial stub B.Cu (feed side open). Better BW over straight stub.',
    'both': 'Both layers (Schaubert). Highest BW, most complex.'
}


# ── dimension helpers ─────────────────────────────────────────────────────────
def draw_hdim(painter, x1, y, x2, label):
    if abs(x2 - x1) < 10: return
    painter.setPen(QPen(C_DIM, 1.0))
    painter.setBrush(QBrush(C_DIM))
    mid_x = (x1 + x2) / 2.0; arr = 7; th = 5
    painter.drawLine(int(x1),int(y),int(x2),int(y))
    painter.drawLine(int(x1),int(y-th),int(x1),int(y+th))
    painter.drawLine(int(x2),int(y-th),int(x2),int(y+th))
    for bx,tip in [(x1,x1+arr),(x2,x2-arr)]:
        p=QPainterPath(); p.moveTo(bx,y); p.lineTo(tip,y-3); p.lineTo(tip,y+3)
        p.closeSubpath(); painter.drawPath(p)
    font=QFont('Segoe UI',8,QFont.Bold); painter.setFont(font)
    fm=QFontMetrics(font); tw=fm.horizontalAdvance(label); fh=fm.height(); pad=5
    bx=mid_x-tw/2-pad; by=y-fh-6
    painter.fillRect(int(bx),int(by),int(tw+pad*2),int(fh+2),C_SURFACE)
    painter.setPen(QPen(C_DIM))
    painter.drawText(int(mid_x-tw/2),int(by+fh-1),label)


def draw_vdim(painter, x, y1, y2, label, right=True):
    if abs(y2-y1) < 10: return
    painter.setPen(QPen(C_DIM,1.0)); painter.setBrush(QBrush(C_DIM))
    mid_y=(y1+y2)/2.0; arr=7; tk=5; sign=1 if right else -1
    painter.drawLine(int(x),int(y1),int(x),int(y2))
    painter.drawLine(int(x-tk),int(y1),int(x+tk),int(y1))
    painter.drawLine(int(x-tk),int(y2),int(x+tk),int(y2))
    for byt,d in [(y1,1),(y2,-1)]:
        p=QPainterPath(); p.moveTo(x,byt); p.lineTo(x-3,byt+d*arr); p.lineTo(x+3,byt+d*arr)
        p.closeSubpath(); painter.drawPath(p)
    font=QFont('Segoe UI',8,QFont.Bold); painter.setFont(font)
    fm=QFontMetrics(font); lw=fm.horizontalAdvance(label); fh=fm.height(); pad=4
    lx=x+sign*10; ly=mid_y-fh/2
    painter.fillRect(int(lx-pad),int(ly-2),int(lw+pad*2),int(fh+4),C_SURFACE)
    painter.setPen(QPen(C_DIM)); painter.drawText(int(lx),int(ly+fh-2),label)


# ── core render function (shared) ─────────────────────────────────────────────
def render_antenna(painter, W, H, params, sc=None, ox=None, oy=None):
    p=params['p']; wmax=params['wmax']; wtotal=params['wtotal']
    L=params['L']; fw=params['fw']; sr=params['sr']; sa=params['sa']
    fl=params['fl']; stub_m=params['stub_m']; A=params['A']
    feed=params['feed']; stub=params['stub']
    half_wmax=wmax/2.0; half_wtotal=wtotal/2.0

    if sc is None:
        # ── FIT SCALE: use W_total for vertical, (fl+L) for horizontal ────────
        avail_x = W * 0.68
        avail_y = H * 0.62
        sc = min(avail_x / (fl + L), avail_y / wtotal)
        ox = W * 0.16 + fl * sc
        oy = H * 0.50

    def tx(x): return ox + x * sc
    def ty(y): return oy - y * sc

    # grid
    painter.setPen(QPen(C_GRID, 0.5))
    gmm=2.0
    x0=math.floor(-fl/gmm)*gmm; x1c=math.ceil(L/gmm)*gmm
    yb=half_wtotal+3
    xg=x0
    while xg<=x1c:
        painter.drawLine(int(tx(xg)),int(ty(-yb)),int(tx(xg)),int(ty(yb))); xg+=gmm
    yg=-math.ceil(yb/gmm)*gmm
    while yg<=yb:
        painter.drawLine(int(tx(x0)),int(ty(yg)),int(tx(x1c)),int(ty(yg))); yg+=gmm

    # ── ground plane: height = W_total, width = fl + L ────────────────────────
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(C_COPPER))
    painter.drawRect(
        int(tx(-fl)),
        int(ty(half_wtotal)),
        int((fl + L) * sc),
        int(wtotal * sc)          # ← wtotal drives the full rectangle height
    )

    # slot
    N=300
    xs=[i/(N-1)*L for i in range(N)]
    yt=[min(A*math.exp(p*x),half_wmax) for x in xs]
    yb2=[-y for y in yt]
    slot=QPainterPath()
    slot.moveTo(tx(xs[0]),ty(yt[0]))
    for i in range(1,N): slot.lineTo(tx(xs[i]),ty(yt[i]))
    for i in range(N-1,-1,-1): slot.lineTo(tx(xs[i]),ty(yb2[i]))
    slot.closeSubpath()
    painter.setBrush(QBrush(C_SLOT)); painter.drawPath(slot)

    def radial(cx,cy,rpx,angle_deg,direction):
        half=math.radians(angle_deg/2.0)
        # screen Y is inverted: 'up' on screen = -y = base angle pi/2 in Qt coords
        # 'down' on screen = +y = base angle -pi/2 in Qt coords
        base=math.pi/2.0 if direction=='up' else -math.pi/2.0
        path=QPainterPath(); path.moveTo(cx,cy)
        for i in range(65):
            t=base-half+(2*half*i/64)
            path.lineTo(cx+rpx*math.cos(t),cy+rpx*math.sin(t))
        path.lineTo(cx,cy); path.closeSubpath(); painter.drawPath(path)

    # radial stubs centered exactly at throat (tx(0), ty(0))
    if stub in ('fcu','both'):
        painter.setBrush(QBrush(C_STUB_F)); radial(tx(0),ty(0),sr*sc,sa,'up')
    if stub in ('bcu','both'):
        painter.setBrush(QBrush(C_STUB_B)); radial(tx(0),ty(0),sr*sc,sa,'down')

    painter.setPen(Qt.NoPen)
    if feed=='microstrip':
        painter.setBrush(QBrush(C_FEED))
        # feed line: right edge flush at throat x=tx(0), centered on ty(0)
        painter.drawRect(int(tx(-fl)), int(ty(fw/2)), int(fl*sc), int(fw*sc))
        # open stub: top edge flush at throat y=ty(0), centered on tx(0)
        painter.drawRect(int(tx(-fw/2)), int(ty(0)), int(fw*sc), int(stub_m*sc))
    elif feed=='cpw':
        painter.setBrush(QBrush(C_FEED))
        painter.drawRect(int(tx(-fl)),int(ty(fw/2)),int(fl*sc),int(fw*sc))
        painter.setBrush(QBrush(C_COPPER))
        gw=max(int(fw*0.4*sc),1)
        painter.drawRect(int(tx(-fl)),int(ty(fw*1.5)),int(fl*sc),gw)
        painter.drawRect(int(tx(-fl)),int(ty(-fw*1.1)),int(fl*sc),gw)
    elif feed=='coax':
        painter.setPen(QPen(C_FEED,2)); painter.setBrush(Qt.NoBrush)
        r=fw*sc*2.2
        painter.drawArc(QRectF(tx(0)-r,ty(0)-r,r*2,r*2),0,180*16)

    # dimension lines
    dim_top=ty(half_wtotal)-16
    dim_bot=ty(-half_wtotal)+28
    draw_hdim(painter,tx(0),dim_top,tx(L),f'L = {L:.1f} mm')
    draw_hdim(painter,tx(-fl),dim_top,tx(0),f'fl = {fl:.1f} mm')
    draw_vdim(painter,tx(L)+26,ty(half_wtotal),ty(-half_wtotal),
              f'W_tot = {wtotal:.1f} mm',right=True)
    draw_vdim(painter,tx(L)+58,ty(half_wmax),ty(-half_wmax),
              f'W_max = {wmax:.1f} mm',right=True)
    draw_vdim(painter,tx(0)-22,ty(A),ty(-A),
              f'Wmin={A*2:.2f}mm',right=False)
    if stub in ('fcu','both','bcu'):
        draw_hdim(painter,tx(0),dim_bot,tx(0)+sr*sc,f'sr = {sr:.1f} mm')

    painter.setPen(QPen(C_MUTED,0.5,Qt.DashLine))
    painter.drawLine(int(tx(0)),int(ty(half_wtotal*0.92)),
                     int(tx(0)),int(ty(-half_wtotal*0.92)))
    return sc, ox, oy


# ── infinite canvas (pure QWidget or QOpenGLWidget depending on setting) ──────
class InfiniteCanvas(QWidget):
    use_opengl = False   # class-level flag, toggled by settings

    def __init__(self, params_fn, parent=None):
        super().__init__(parent)
        self.params_fn=params_fn
        self._zoom=1.0; self._offset=QPointF(0,0); self._drag_last=None
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(400,200)
        if InfiniteCanvas.use_opengl:
            self.setAttribute(Qt.WA_PaintOnScreen, False)
            fmt=QSurfaceFormat()
            fmt.setSamples(4)          # 4× MSAA
            fmt.setSwapInterval(1)     # vsync
            QSurfaceFormat.setDefaultFormat(fmt)

    def reset_view(self):
        self._zoom=1.0; self._offset=QPointF(0,0); self.update()

    def wheelEvent(self,e):
        factor=1.15 if e.angleDelta().y()>0 else 1/1.15
        mouse=QPointF(e.pos())
        self._offset=mouse-factor*(mouse-self._offset)
        self._zoom=max(0.05,min(self._zoom*factor,80.0)); self.update()

    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton:
            self._drag_last=e.pos(); self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self,e):
        if self._drag_last is not None:
            d=e.pos()-self._drag_last
            self._offset+=QPointF(d); self._drag_last=e.pos(); self.update()

    def mouseReleaseEvent(self,e):
        self._drag_last=None; self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self,e): self.reset_view()

    def paintEvent(self,event):
        painter=QPainter(self)
        if InfiniteCanvas.use_opengl:
            painter.setRenderHints(
                QPainter.Antialiasing|QPainter.SmoothPixmapTransform)
        else:
            painter.setRenderHint(QPainter.Antialiasing)

        W=self.width(); H=self.height()
        painter.fillRect(0,0,W,H,C_BG)
        params=self.params_fn()
        fl=params['fl']; L=params['L']; wtotal=params['wtotal']

        avail_x=W*0.68; avail_y=H*0.62
        base_sc=min(avail_x/(fl+L), avail_y/wtotal)
        sc=base_sc*self._zoom
        ox=W*0.16+fl*base_sc+self._offset.x()
        oy=H*0.50+self._offset.y()

        render_antenna(painter,W,H,params,sc_override=sc,
                       ox_override=ox,oy_override=oy) if False else \
        render_antenna(painter,W,H,params,sc,ox,oy)

        # HW indicator
        mode='GPU' if InfiniteCanvas.use_opengl else 'CPU'
        painter.setFont(QFont('Monospace',9))
        painter.setPen(QPen(C_MUTED))
        painter.drawText(8,H-8,
            f'[{mode}]  zoom {self._zoom:.2f}×  scroll=zoom  drag=pan  dbl-click=reset')
        self._legend(painter,W,H,params)

    def _legend(self,painter,W,H,params):
        items=[(C_COPPER,'F.Cu ground'),(C_FEED,'feed/B.Cu')]
        if params['stub'] in ('fcu','both'): items.append((C_STUB_F,'stub F.Cu'))
        if params['stub'] in ('bcu','both'): items.append((C_STUB_B,'stub B.Cu'))
        painter.setFont(QFont('Monospace',8))
        x=10; y=H-28-len(items)*15
        for color,label in items:
            painter.fillRect(x,y,10,10,color); painter.setPen(QPen(C_MUTED))
            painter.drawText(x+14,y+9,label); y+=15


class DetachedWindow(QDialog):
    def __init__(self,params_fn,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Vivaldi — Infinite Canvas')
        self.setMinimumSize(900,600)
        self.setStyleSheet(f'background:{C_BG.name()};')
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        self.canvas=InfiniteCanvas(params_fn,self)
        layout.addWidget(self.canvas)

    def refresh(self): self.canvas.update()


# ── param row ─────────────────────────────────────────────────────────────────
class ParamRow(QWidget):
    def __init__(self,label,mn,mx,val,step,decimals,unit,callback):
        super().__init__()
        self.decimals=decimals; self.callback=callback; self._updating=False
        layout=QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0); layout.setSpacing(6)
        lbl=QLabel(label); lbl.setFixedWidth(120)
        lbl.setStyleSheet(f'color:{C_MUTED.name()};font-size:12px;')
        scale=10**decimals
        self.slider=QSlider(Qt.Horizontal)
        self.slider.setMinimum(int(mn*scale)); self.slider.setMaximum(int(mx*scale))
        self.slider.setValue(int(val*scale)); self.slider.setSingleStep(int(step*scale))
        self._scale=scale
        self.spin=QDoubleSpinBox()
        self.spin.setMinimum(mn); self.spin.setMaximum(mx)
        self.spin.setValue(val); self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setSuffix(f' {unit}' if unit else '')
        self.spin.setFixedWidth(90); self.spin.setAlignment(Qt.AlignRight)
        self.spin.setStyleSheet(
            f'QDoubleSpinBox{{background:{C_SURFACE2.name()};color:{C_TEXT.name()};'
            f'border:1px solid {C_BORDER.name()};border-radius:4px;'
            f'font-size:12px;font-weight:bold;padding:2px 4px;}}'
            f'QDoubleSpinBox::up-button,QDoubleSpinBox::down-button{{'
            f'width:16px;background:{C_SURFACE.name()};border:none;}}')
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        layout.addWidget(lbl); layout.addWidget(self.slider); layout.addWidget(self.spin)

    def _from_slider(self,v):
        if self._updating: return
        self._updating=True; self.spin.setValue(v/self._scale); self._updating=False
        self.callback(v/self._scale)

    def _from_spin(self,v):
        if self._updating: return
        self._updating=True; self.slider.setValue(int(v*self._scale)); self._updating=False
        self.callback(v)

    def value(self): return self.spin.value()


class ToggleGroup(QWidget):
    def __init__(self,options,callback):
        super().__init__()
        layout=QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0); layout.setSpacing(4)
        self.buttons={}; self.callback=callback; self.current=options[0][0]
        for key,label in options:
            btn=QPushButton(label); btn.setCheckable(True); btn.setFixedHeight(26)
            btn.setStyleSheet(self._style(False))
            btn.clicked.connect(lambda _,k=key: self._select(k))
            self.buttons[key]=btn; layout.addWidget(btn)
        layout.addStretch()
        self.buttons[self.current].setChecked(True)
        self.buttons[self.current].setStyleSheet(self._style(True))

    def _style(self,active):
        if active:
            return (f'QPushButton{{background:{C_BTN_ACTIVE.name()};'
                    f'border:1px solid {C_BTN_BORDER_ACT.name()};'
                    f'color:{C_ACCENT.name()};border-radius:4px;font-size:12px;padding:0 10px;}}')
        return (f'QPushButton{{background:transparent;border:1px solid {C_BORDER.name()};'
                f'color:{C_MUTED.name()};border-radius:4px;font-size:12px;padding:0 10px;}}'
                f'QPushButton:hover{{background:{C_SURFACE.name()};'
                f'border-color:{C_MUTED.name()};color:{C_TEXT.name()};}}')

    def _select(self,key):
        self.current=key
        for k,btn in self.buttons.items():
            btn.setChecked(k==key); btn.setStyleSheet(self._style(k==key))
        self.callback(key)

    def value(self): return self.current


class VarTable(QTableWidget):
    def __init__(self):
        super().__init__(0,4)
        self.setHorizontalHeaderLabels(['variable','value','unit','description'])
        for i,mode in enumerate([QHeaderView.ResizeToContents]*3+[QHeaderView.Stretch]):
            self.horizontalHeader().setSectionResizeMode(i,mode)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionMode(QTableWidget.NoSelection)
        self.setShowGrid(False); self.setAlternatingRowColors(True)
        self.setStyleSheet(f'''
            QTableWidget{{background:{C_SURFACE.name()};color:{C_TEXT.name()};
                border:1px solid {C_BORDER.name()};border-radius:6px;font-size:12px;}}
            QHeaderView::section{{background:{C_SURFACE2.name()};color:{C_MUTED.name()};
                border:none;padding:4px 8px;font-size:11px;}}
            QTableWidget::item{{padding:3px 8px;}}
            QTableWidget::item:alternate{{background:{C_SURFACE2.name()};}}''')

    def refresh(self,p,wmax,wtotal,L,fw,sr,sa,fl,stub_m,A,feed,stub):
        er=3.66
        lam0=round(3e8/(17e9*math.sqrt(er))*1e3,2)
        lam_m=round(3e8/(10e9*math.sqrt(er))*1e3,2)
        rows=[
            ('f₀','17','GHz','center frequency'),
            ('f_min','10','GHz','minimum frequency'),
            ('εᵣ',f'{er}','—','substrate relative permittivity'),
            ('h','0.51','mm','substrate thickness'),
            ('λ₀',f'{lam0}','mm','wavelength at f₀ in substrate'),
            ('λ_min',f'{lam_m}','mm','wavelength at f_min in substrate'),
            ('W_max1',f'{round(lam0,2)}','mm','lower aperture bound ≈ λ₀'),
            ('W_max2',f'{round(lam_m/2,2)}','mm','upper aperture bound ≈ λ_min/2'),
            ('A',f'{A:.3f}','mm','half of W_min'),
            ('W_min',f'{A*2:.3f}','mm','throat slot width = 2A'),
            ('p',f'{p:.3f}','—','exponential taper rate'),
            ('L',f'{L:.1f}','mm','antenna length'),
            ('W_max',f'{wmax:.1f}','mm','aperture slot width'),
            ('W_total',f'{wtotal:.1f}','mm','total copper board height'),
            ('margin',f'{(wtotal-wmax)/2:.2f}','mm','copper margin above/below slot'),
            ('f_w',f'{fw:.2f}','mm','50Ω microstrip line width'),
            ('f_l',f'{fl:.1f}','mm','feed line length'),
            ('stub_m',f'{stub_m:.2f}','mm','open stub length λm/4'),
            ('stub_r',f'{sr:.1f}','mm','radial stub radius'),
            ('stub_ang',f'{sa:.0f}','°','radial stub fan angle'),
            ('feed',feed,'—','feed transition type'),
            ('stub_lay',stub,'—','radial stub layer(s)'),
        ]
        self.setRowCount(len(rows))
        for i,(var,val,unit,desc) in enumerate(rows):
            self.setItem(i,0,QTableWidgetItem(var))
            vi=QTableWidgetItem(val); vi.setTextAlignment(Qt.AlignRight|Qt.AlignVCenter)
            vi.setForeground(C_ACCENT); self.setItem(i,1,vi)
            self.setItem(i,2,QTableWidgetItem(unit))
            self.setItem(i,3,QTableWidgetItem(desc))
        self.resizeRowsToContents()


# ── main window ───────────────────────────────────────────────────────────────
class VivaldiGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self._ready=False; self._detached=None
        self.setWindowTitle('Vivaldi Antenna Designer')
        self.setMinimumSize(960,820)
        self._apply_style()

        central=QWidget(); self.setCentralWidget(central)
        root=QVBoxLayout(central)
        root.setContentsMargins(14,10,14,10); root.setSpacing(8)

        splitter=QSplitter(Qt.Vertical)
        splitter.setStyleSheet(
            f'QSplitter::handle:vertical{{background:{C_BORDER.name()};height:2px;}}')

        # canvas + toolbar
        canvas_wrap=QWidget(); cw=QVBoxLayout(canvas_wrap)
        cw.setContentsMargins(0,0,0,4); cw.setSpacing(4)

        toolbar=QWidget(); tb=QHBoxLayout(toolbar)
        tb.setContentsMargins(0,0,0,0); tb.setSpacing(6)

        hint=QLabel('scroll=zoom  ·  drag=pan  ·  dbl-click=reset')
        hint.setStyleSheet(f'color:{C_MUTED.name()};font-size:11px;')
        tb.addWidget(hint); tb.addStretch()

        # ── hardware acceleration toggle ──────────────────────────────────────
        self.hw_chk=QCheckBox('hardware acceleration (GPU)')
        self.hw_chk.setChecked(False)
        self.hw_chk.setStyleSheet(
            f'QCheckBox{{color:{C_MUTED.name()};font-size:11px;}}'
            f'QCheckBox::indicator{{width:14px;height:14px;}}'
            f'QCheckBox::indicator:checked{{background:{C_ACCENT.name()};'
            f'border:1px solid {C_ACCENT.name()};border-radius:3px;}}'
            f'QCheckBox::indicator:unchecked{{background:transparent;'
            f'border:1px solid {C_BORDER.name()};border-radius:3px;}}')
        self.hw_chk.toggled.connect(self._toggle_hw)
        tb.addWidget(self.hw_chk)

        def mk_btn(text, slot, accent=False):
            btn=QPushButton(text); btn.setFixedHeight(24)
            if accent:
                btn.setStyleSheet(
                    f'QPushButton{{background:{C_BTN_ACTIVE.name()};'
                    f'border:1px solid {C_BTN_BORDER_ACT.name()};'
                    f'color:{C_ACCENT.name()};border-radius:4px;font-size:11px;padding:0 8px;}}'
                    f'QPushButton:hover{{background:#1e4a80;}}')
            else:
                btn.setStyleSheet(
                    f'QPushButton{{background:transparent;border:1px solid {C_BORDER.name()};'
                    f'color:{C_MUTED.name()};border-radius:4px;font-size:11px;padding:0 8px;}}'
                    f'QPushButton:hover{{color:{C_TEXT.name()};border-color:{C_MUTED.name()};}}')
            btn.clicked.connect(slot); tb.addWidget(btn); return btn

        mk_btn('reset view', self._reset_view)
        mk_btn('↗  open in window', self._open_detached, accent=True)

        cw.addWidget(toolbar)
        self.canvas=InfiniteCanvas(self._get_params)
        self.canvas.setMinimumHeight(220)
        cw.addWidget(self.canvas)
        splitter.addWidget(canvas_wrap)

        # bottom: controls + table
        bottom=QWidget(); bl=QHBoxLayout(bottom)
        bl.setContentsMargins(0,0,0,0); bl.setSpacing(10)

        ctrl_scroll=QScrollArea(); ctrl_scroll.setWidgetResizable(True)
        ctrl_scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}')
        ctrl_w=QWidget(); cl=QVBoxLayout(ctrl_w)
        cl.setContentsMargins(0,4,0,4); cl.setSpacing(5)

        def sl(label,mn,mx,val,step,dec,unit):
            s=ParamRow(label,mn,mx,val,step,dec,unit,self._on_param)
            cl.addWidget(s); return s

        self.sl_p      = sl('taper p',         0.05,0.5,  0.25,0.01,2,'')
        self.sl_wmax   = sl('W_max (mm)',       4.0, 14.0, 8.5, 0.5, 1,'mm')
        self.sl_wtotal = sl('W_total (mm)',     6.0, 24.0,11.5, 0.5, 1,'mm')
        self.sl_L      = sl('length L (mm)',    8.0, 30.0,16.0, 0.5, 1,'mm')
        self.sl_fw     = sl('feed width (mm)',  0.5, 3.0,  1.1, 0.05,2,'mm')
        self.sl_sr     = sl('stub radius (mm)', 1.0, 6.0,  2.9, 0.1, 1,'mm')
        self.sl_sa     = sl('stub angle (°)',  30.0,150.0,90.0, 5.0, 0,'°')

        def toggle_row(label,options,cb):
            row=QWidget(); rl=QHBoxLayout(row)
            rl.setContentsMargins(0,0,0,0); rl.setSpacing(6)
            lbl=QLabel(label); lbl.setFixedWidth(120)
            lbl.setStyleSheet(f'color:{C_MUTED.name()};font-size:12px;')
            tg=ToggleGroup(options,cb); rl.addWidget(lbl); rl.addWidget(tg)
            cl.addWidget(row); return tg

        self.feed_toggle=toggle_row('feed type',[
            ('microstrip','microstrip'),('cpw','CPW'),('coax','coaxial'),
        ],self._on_param_generic)
        self.stub_toggle=toggle_row('radial stub',[
            ('none','none'),('fcu','F.Cu'),('bcu','B.Cu'),('both','both'),
        ],self._on_param_generic)

        self.desc_lbl=QLabel(); self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setStyleSheet(
            f'color:{C_MUTED.name()};font-size:11px;'
            f'background:{C_SURFACE.name()};border:1px solid {C_BORDER.name()};'
            f'border-radius:6px;padding:6px;')
        cl.addWidget(self.desc_lbl)

        gen_btn=QPushButton('generate KiCad script')
        gen_btn.setFixedHeight(34)
        gen_btn.setStyleSheet(
            f'QPushButton{{background:{C_BTN_ACTIVE.name()};'
            f'border:1px solid {C_BTN_BORDER_ACT.name()};'
            f'color:{C_ACCENT.name()};border-radius:6px;font-size:13px;}}'
            f'QPushButton:hover{{background:#1e4a80;}}'
            f'QPushButton:pressed{{background:#163860;}}')
        gen_btn.clicked.connect(self._generate)
        cl.addWidget(gen_btn); cl.addStretch()
        ctrl_scroll.setWidget(ctrl_w); ctrl_scroll.setMinimumWidth(390)

        self.var_table=VarTable()
        bl.addWidget(ctrl_scroll,stretch=2); bl.addWidget(self.var_table,stretch=3)
        splitter.addWidget(bottom)
        splitter.setSizes([360,460])
        root.addWidget(splitter)

        self.status=QStatusBar()
        self.status.setStyleSheet(f'color:{C_MUTED.name()};font-size:11px;')
        self.setStatusBar(self.status); self.status.showMessage('ready — GPU off')

        self._ready=True; self._refresh()

    # ── hardware toggle ───────────────────────────────────────────────────────
    def _toggle_hw(self, checked):
        InfiniteCanvas.use_opengl = checked
        if checked:
            # enable Qt's OpenGL-backed raster engine via WA_NativeWindow
            self.canvas.setAttribute(Qt.WA_NativeWindow, True)
            if self._detached:
                self._detached.canvas.setAttribute(Qt.WA_NativeWindow, True)
            self.status.showMessage('GPU acceleration ON — reopen detached window to apply there')
        else:
            self.canvas.setAttribute(Qt.WA_NativeWindow, False)
            self.status.showMessage('GPU acceleration OFF')
        self.canvas.update()

    def _get_params(self):
        if not self._ready:
            return dict(p=0.25,wmax=8.5,wtotal=11.5,L=16.0,fw=1.1,sr=2.9,
                        sa=90.0,fl=10.0,stub_m=2.59,A=0.05,
                        feed='microstrip',stub='fcu')
        return dict(
            p=self.sl_p.value(), wmax=self.sl_wmax.value(),
            wtotal=self.sl_wtotal.value(), L=self.sl_L.value(),
            fw=self.sl_fw.value(), sr=self.sl_sr.value(),
            sa=self.sl_sa.value(), fl=10.0, stub_m=2.59, A=0.05,
            feed=self.feed_toggle.value(), stub=self.stub_toggle.value()
        )

    def _apply_style(self):
        self.setStyleSheet(f'''
            QMainWindow,QWidget{{background-color:{C_BG.name()};
                color:{C_TEXT.name()};font-family:"Segoe UI",sans-serif;}}
            QSplitter::handle:vertical{{background:{C_BORDER.name()};height:2px;}}
            QSlider::groove:horizontal{{height:4px;background:{C_BORDER.name()};border-radius:2px;}}
            QSlider::handle:horizontal{{background:{C_ACCENT.name()};
                width:14px;height:14px;margin:-5px 0;border-radius:7px;}}
            QSlider::sub-page:horizontal{{background:{C_ACCENT.name()};border-radius:2px;}}
            QScrollBar:vertical{{background:{C_SURFACE.name()};width:8px;}}
            QScrollBar::handle:vertical{{background:{C_BORDER.name()};border-radius:4px;}}''')

    def _on_param(self,_=None):
        if not self._ready: return
        self._refresh()

    def _on_param_generic(self,_=None):
        if not self._ready: return
        self._refresh()

    def _reset_view(self): self.canvas.reset_view()

    def _open_detached(self):
        if self._detached is None or not self._detached.isVisible():
            self._detached=DetachedWindow(self._get_params,self)
            self._detached.show()
        else:
            self._detached.raise_(); self._detached.activateWindow()

    def _refresh(self):
        if not self._ready: return
        p=self.sl_p.value(); wmax=self.sl_wmax.value()
        wtotal=self.sl_wtotal.value(); L=self.sl_L.value()
        fw=self.sl_fw.value(); sr=self.sl_sr.value(); sa=self.sl_sa.value()
        feed=self.feed_toggle.value(); stub=self.stub_toggle.value()

        # clamp W_total >= W_max + 1mm
        if wtotal < wmax+1.0:
            self.sl_wtotal.spin.blockSignals(True)
            self.sl_wtotal.slider.blockSignals(True)
            wtotal=wmax+1.0
            self.sl_wtotal.spin.setValue(wtotal)
            self.sl_wtotal.slider.setValue(int(wtotal*10))
            self.sl_wtotal.spin.blockSignals(False)
            self.sl_wtotal.slider.blockSignals(False)

        self.canvas.update()
        if self._detached and self._detached.isVisible():
            self._detached.refresh()

        self.var_table.refresh(p,wmax,wtotal,L,fw,sr,sa,10.0,2.59,0.05,feed,stub)
        self.desc_lbl.setText(f'feed: {FEED_DESC[feed]}\nstub: {STUB_DESC[stub]}')
        mode='GPU' if InfiniteCanvas.use_opengl else 'CPU'
        self.status.showMessage(
            f'[{mode}]  p={p:.2f}  W_max={wmax:.1f}  W_tot={wtotal:.1f}  '
            f'L={L:.1f}  fw={fw:.2f}  sr={sr:.1f}  sa={sa:.0f}°  '
            f'feed={feed}  stub={stub}')

    def _generate(self):
        if not self._ready: return
        p=self.sl_p.value(); wmax=self.sl_wmax.value()
        wtotal=self.sl_wtotal.value(); L=self.sl_L.value()
        fw=self.sl_fw.value(); sr=self.sl_sr.value(); sa=self.sl_sa.value()
        margin=(wtotal-wmax)/2.0
        script_path=r'C:\Users\fdreshaj\Documents\GitHub\PWM-Phased-Array-Radar\pwm_radar\vivaldi_ant\vivaldi_gen.py'
        try:
            with open(script_path,'r', encoding='utf-8') as f: src=f.read()
            replacements={
                'p           =':f'p           = {p}',
                'W_max       =':f'W_max       = {wmax}',
                'L           =':f'L           = {L}',
                'f_w         =':f'f_w         = {fw}',
                'stub_r      =':f'stub_r      = {sr}',
                'stub_angle  =':f'stub_angle  = {sa}',
                'margin      =':f'margin      = {margin:.3f}',
            }
            lines=src.splitlines(); new_lines=[]
            for line in lines:
                replaced=False
                for key,new_val in replacements.items():
                    if line.strip().startswith(key.strip()):
                        indent=len(line)-len(line.lstrip())
                        new_lines.append(' '*indent+new_val+'      # GUI')
                        replaced=True; break
                if not replaced: new_lines.append(line)
            with open(script_path,'w', encoding='utf-8') as f: f.write('\n'.join(new_lines))
            self.status.showMessage(
                f'vivaldi_gen.py updated — exec(open(r"{script_path}").read()) in KiCad')
        except FileNotFoundError:
            self.status.showMessage(f'ERROR: vivaldi_gen.py not found at {script_path}')


if __name__=='__main__':
    # enable Qt's AA raster acceleration regardless of GPU toggle
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app=QApplication(sys.argv)
    win=VivaldiGUI()
    win.show()
    sys.exit(app.exec_())