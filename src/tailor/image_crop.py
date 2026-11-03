"""Canvas crop mode: bounded native ROI, outside mask and explicit apply/cancel."""

import base64
import copy
import math

import pyqtgraph as pg
import shiboken6
from PySide6 import QtCore, QtGui, QtWidgets

from tailor.resize_handles import round_roi


class ImageCrop(QtCore.QObject):
    def __init__(self, manager, button):
        super().__init__(manager)
        self.manager, self.button = manager, button
        self.roi = self.mask = self.guides = self.toolbar = None
        button.setCheckable(True)
        button.clicked.connect(self.toggle)
        manager.changed.connect(self.sync)
        manager.plot.ui.plot_widget.viewport().installEventFilter(self)
        self.sync()

    def sync(self):
        record = self.manager.current()
        self.button.setEnabled(bool(record and record["kind"] == "image" and not record["locked"]))
        if self.roi is not None and (record is None or record != self.original):
            self.cancel()

    def toggle(self):
        if self.roi is not None:
            self.cancel()
            return
        record = self.manager.current()
        if not record or record["kind"] != "image" or record["locked"]:
            self.button.setChecked(False)
            return
        self.original = copy.deepcopy(record)
        self.key = record["id"]
        item = self.manager.items[self.key]
        self.bounds = QtCore.QRectF(item.path.boundingRect())
        self.image = QtGui.QImage.fromData(base64.b64decode(record["image_data"]))
        if self.image.isNull() or self.bounds.isEmpty():
            return
        self.manager._cropping = self.key
        item.update()
        self.roi = pg.RectROI(self.bounds.topLeft(), self.bounds.size(), parent=item,
                              maxBounds=self.bounds, pen=pg.mkPen("#2878cc", width=1.5))
        for handle in list(self.roi.getHandles()):
            self.roi.removeHandle(handle)
        for point, center in [([0,0],[1,1]),([1,0],[0,1]),([0,1],[1,0]),([1,1],[0,0]),
                              ([.5,0],[.5,1]),([.5,1],[.5,0]),([0,.5],[1,.5]),([1,.5],[0,.5])]:
            self.roi.addScaleHandle(point,center)
        round_roi(self.roi)
        for handle in self.roi.getHandles():
            handle.radius = 9
            handle.buildPath()
            handle._shape = None
        self.roi.setZValue(20002)
        self.mask = QtWidgets.QGraphicsPathItem(item)
        self.mask.setPen(pg.mkPen(None))
        self.mask.setBrush(pg.mkBrush(0,0,0,150))
        self.mask.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self.mask.setZValue(20000)
        self.guides = QtWidgets.QGraphicsPathItem(item)
        self.guides.setPen(pg.mkPen("#ffffff",width=.7,style=QtCore.Qt.DashLine))
        self.guides.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self.guides.setZValue(20001)
        viewport = self.manager.plot.ui.plot_widget.viewport()
        self.toolbar = QtWidgets.QFrame(viewport)
        self.toolbar.setObjectName("cropToolbar")
        self.toolbar.setStyleSheet("QFrame#cropToolbar {background:palette(base);border:1px solid palette(mid);border-radius:6px;}")
        layout = QtWidgets.QVBoxLayout(self.toolbar)
        layout.setContentsMargins(8,5,8,5)
        self.size_label = QtWidgets.QLabel()
        self.apply_button, self.cancel_button = QtWidgets.QPushButton("确认裁剪"), QtWidgets.QPushButton("取消")
        self.apply_button.setProperty("intent","primary")
        self.apply_button.clicked.connect(self.commit)
        self.cancel_button.clicked.connect(self.cancel)
        hint=QtWidgets.QLabel('拖动图片上的8个标记裁剪；Enter确认，Esc取消。')
        hint.setWordWrap(True);layout.addWidget(hint)
        actions=QtWidgets.QHBoxLayout();layout.addLayout(actions)
        for widget in (self.size_label,self.apply_button,self.cancel_button):
            actions.addWidget(widget)
        self.toolbar.show()
        self.toolbar.raise_()
        self.roi.sigRegionChanged.connect(self.update_mask)
        self.update_mask()
        self.button.setChecked(True)
        viewport.setFocus()

    def pixel_rect(self):
        rect = QtCore.QRectF(self.roi.pos(),QtCore.QSizeF(self.roi.size().x(),self.roi.size().y())).intersected(self.bounds)
        sx,sy = self.image.width()/self.bounds.width(),self.image.height()/self.bounds.height()
        left = max(0,min(self.image.width()-1,math.floor((rect.left()-self.bounds.left())*sx+1e-8)))
        top = max(0,min(self.image.height()-1,math.floor((rect.top()-self.bounds.top())*sy+1e-8)))
        right = max(left+1,min(self.image.width(),math.ceil((rect.right()-self.bounds.left())*sx-1e-8)))
        bottom = max(top+1,min(self.image.height(),math.ceil((rect.bottom()-self.bounds.top())*sy-1e-8)))
        return QtCore.QRect(left,top,right-left,bottom-top)

    def update_mask(self):
        if self.roi is None:
            return
        rect = QtCore.QRectF(self.roi.pos(),QtCore.QSizeF(self.roi.size().x(),self.roi.size().y())).intersected(self.bounds)
        path = QtGui.QPainterPath()
        path.setFillRule(QtCore.Qt.OddEvenFill)
        path.addRect(self.bounds)
        path.addRect(rect)
        self.mask.setPath(path)
        grid = QtGui.QPainterPath()
        for n in (1,2):
            x,y=rect.left()+rect.width()*n/3,rect.top()+rect.height()*n/3
            grid.moveTo(x,rect.top());grid.lineTo(x,rect.bottom())
            grid.moveTo(rect.left(),y);grid.lineTo(rect.right(),y)
        self.guides.setPath(grid)
        pixels=self.pixel_rect()
        self.size_label.setText(f"{pixels.width()} × {pixels.height()} px")
        self.place_toolbar()

    def place_toolbar(self):
        if self.toolbar is not None:
            self.toolbar.adjustSize()
            viewport=self.manager.plot.ui.plot_widget.viewport()
            self.toolbar.setMaximumWidth(max(120,min(520,viewport.width()-32)))
            from tailor.notices import bottom_center
            bottom_center(self.toolbar,viewport)
            notice=getattr(self.manager.plot.main_window,'_notice',None)
            if notice is not None and notice.isVisible():notice.place()

    def commit(self):
        if self.roi is None:
            return
        pixels=self.pixel_rect()
        if pixels == self.image.rect():
            self.cancel()
            return
        sx,sy=self.bounds.width()/self.image.width(),self.bounds.height()/self.image.height()
        rect=QtCore.QRectF(self.bounds.left()+pixels.x()*sx,self.bounds.top()+pixels.y()*sy,pixels.width()*sx,pixels.height()*sy)
        cropped=self.image.copy(pixels)
        data=QtCore.QByteArray()
        buffer=QtCore.QBuffer(data)
        buffer.open(QtCore.QIODevice.WriteOnly)
        cropped.save(buffer,"PNG")
        item=self.manager.items[self.key]
        center=item.mapToParent(rect.center())
        first=center-QtCore.QPointF(rect.width()/2,rect.height()/2)
        last=center+QtCore.QPointF(rect.width()/2,rect.height()/2)
        record={**self.original,"image_data":bytes(data.toBase64()).decode(),
                "points":self.manager.from_pixels(self.original["anchor"],[first,last])}
        self.cancel()
        self.manager.replace(record)

    def cancel(self):
        self.manager._cropping=None
        self._mouse_crop = None
        for obj in (self.roi,self.mask,self.guides):
            if obj is not None and shiboken6.isValid(obj):
                scene=obj.scene()
                obj.setParentItem(None)
                if scene is not None:
                    scene.removeItem(obj)
                if isinstance(obj,QtCore.QObject):
                    obj.deleteLater()
        self.roi=self.mask=self.guides=None
        if self.toolbar is not None:
            self.toolbar.hide()
            self.toolbar.deleteLater()
            self.toolbar=None
        self.button.setText("裁剪")
        self.button.setChecked(False)
        for item in self.manager.items.values():
            item.update()
        notice=getattr(self.manager.plot.main_window,'_notice',None)
        if notice is not None and notice.isVisible():notice.place()

    def eventFilter(self, watched, event):
        if self.roi is None:
            return False
        if event.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease):
            item = self.manager.items.get(self.key)
            if item is None:
                self.cancel()
                return False
            scene = self.manager.plot.ui.plot_widget.mapToScene(event.position().toPoint())
            point = item.mapFromScene(scene)
            if event.type() == QtCore.QEvent.MouseButtonPress:
                if event.button() != QtCore.Qt.LeftButton:
                    return True
                rect = QtCore.QRectF(self.roi.pos(), QtCore.QSizeF(self.roi.size().x(), self.roi.size().y()))
                anchors = [rect.topLeft(),rect.topRight(),rect.bottomLeft(),rect.bottomRight(),
                           QtCore.QPointF(rect.center().x(),rect.top()),QtCore.QPointF(rect.center().x(),rect.bottom()),
                           QtCore.QPointF(rect.left(),rect.center().y()),QtCore.QPointF(rect.right(),rect.center().y())]
                hit = next((i for i,p in enumerate(anchors) if QtCore.QLineF(item.mapToScene(p),scene).length() <= 14),None)
                self._mouse_crop = (point, rect, hit) if hit is not None or rect.contains(point) else None
                return True
            drag = getattr(self, "_mouse_crop", None)
            if drag and event.type() == QtCore.QEvent.MouseMove:
                start, before, hit = drag
                rect = QtCore.QRectF(before)
                delta = point - start
                if hit is None:
                    rect.translate(delta)
                    rect.moveLeft(min(max(rect.left(),self.bounds.left()),self.bounds.right()-rect.width()))
                    rect.moveTop(min(max(rect.top(),self.bounds.top()),self.bounds.bottom()-rect.height()))
                else:
                    if hit in (0,2,6): rect.setLeft(min(rect.right()-1,max(self.bounds.left(),point.x())))
                    if hit in (1,3,7): rect.setRight(max(rect.left()+1,min(self.bounds.right(),point.x())))
                    if hit in (0,1,4): rect.setTop(min(rect.bottom()-1,max(self.bounds.top(),point.y())))
                    if hit in (2,3,5): rect.setBottom(max(rect.top()+1,min(self.bounds.bottom(),point.y())))
                with QtCore.QSignalBlocker(self.roi):
                    self.roi.setPos(rect.topLeft())
                    self.roi.setSize(rect.size())
                self.update_mask()
                return True
            if event.type() == QtCore.QEvent.MouseButtonRelease:
                self._mouse_crop = None
                return True
            return True
        if event.type() == QtCore.QEvent.Resize:
            self.place_toolbar()
        if event.type() == QtCore.QEvent.KeyPress:
            if event.key() in (QtCore.Qt.Key_Enter,QtCore.Qt.Key_Return):
                self.commit();return True
            if event.key() == QtCore.Qt.Key_Escape:
                self.cancel();return True
        return False
