"""时间线控件 - QGraphicsView + 自定义 QGraphicsScene 横向时间轴.

节点按 node_order 排列，支持拖拽调整顺序；order_changed 信号触发冲突检测；
冲突节点高亮显示。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPainter
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QWidget,
)


class _TimelineNodeItem(QGraphicsEllipseItem):
    """单个时间线节点圆圈，承载节点数据与拖拽支持."""

    def __init__(self, node_id: str, event_name: str, x: float, y: float, radius: float = 18.0) -> None:
        super().__init__(x - radius, y - radius, radius * 2, radius * 2)
        self.node_id: str = node_id
        self.event_name: str = event_name
        self._radius: float = radius
        self._conflict: bool = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setBrush(QBrush(QColor("#4CAF50")))
        self.setPen(QPen(QColor("#2E7D32"), 2))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(2)

        label = QGraphicsTextItem(event_name, self)
        label.setFont(QFont("Microsoft YaHei", 9))
        label.setPos(x - label.boundingRect().width() / 2, y + radius + 4)
        label.setDefaultTextColor(QColor("#333333"))

    def set_conflict(self, conflict: bool) -> None:
        self._conflict = conflict
        if conflict:
            self.setBrush(QBrush(QColor("#F44336")))
            self.setPen(QPen(QColor("#B71C1C"), 3))
        else:
            self.setBrush(QBrush(QColor("#4CAF50")))
            self.setPen(QPen(QColor("#2E7D32"), 2))
        self.update()

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        scene_rect = self.scene().sceneRect()
        if scene_rect.height() > 0:
            target_y = scene_rect.center().y()
            if abs(self.pos().y() - target_y) > 0.5:
                self.setPos(self.pos().x(), target_y)


class TimelineWidget(QGraphicsView):
    """横向时间轴控件：节点按 node_order 排列，可拖拽调整顺序."""

    order_changed = Signal(list)
    node_double_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene: QGraphicsScene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nodes: list[dict] = []
        self._node_items: dict[str, _TimelineNodeItem] = {}
        self._conflict_ids: set[str] = set()
        self._axis_line: QGraphicsLineItem | None = None
        self._node_radius: float = 18.0
        self._spacing: float = 140.0
        self._axis_y: float = 80.0

    def set_nodes(self, nodes: list[dict]) -> None:
        """设置节点列表并重绘.

        Args:
            nodes: 节点字典列表，每个节点应包含 node_id/event_name/node_order 等字段。
        """
        self._nodes = sorted(nodes, key=lambda n: n.get("node_order", 0))
        self._render()

    def set_conflicts(self, conflict_ids: list[str]) -> None:
        """设置冲突节点ID列表，冲突节点高亮显示."""
        self._conflict_ids = set(conflict_ids)
        for node_id, item in self._node_items.items():
            item.set_conflict(node_id in self._conflict_ids)

    def get_node_order(self) -> list[str]:
        """按当前场景中节点的X坐标顺序返回 node_id 列表."""
        items = sorted(
            self._node_items.values(),
            key=lambda it: it.pos().x(),
        )
        return [it.node_id for it in items]

    def clear_nodes(self) -> None:
        self._scene.clear()
        self._nodes = []
        self._node_items = {}
        self._conflict_ids = set()
        self._axis_line = None

    def _render(self) -> None:
        self._scene.clear()
        self._node_items = {}
        if not self._nodes:
            return
        total_width = max(len(self._nodes) * self._spacing, 800)
        self._scene.setSceneRect(QRectF(0, 0, total_width, self._axis_y * 2))
        self._axis_line = QGraphicsLineItem(0, self._axis_y, total_width, self._axis_y)
        self._axis_line.setPen(QPen(QColor("#9E9E9E"), 2))
        self._scene.addItem(self._axis_line)

        for idx, node in enumerate(self._nodes):
            x = 60 + idx * self._spacing
            node_id = node.get("node_id", "")
            event_name = node.get("event_name", "")
            item = _TimelineNodeItem(node_id, event_name, x, self._axis_y, self._node_radius)
            item.set_conflict(node_id in self._conflict_ids)
            self._scene.addItem(item)
            self._node_items[node_id] = item

            order_label = QGraphicsTextItem(str(idx + 1), self._scene)
            order_label.setFont(QFont("Microsoft YaHei", 8))
            order_label.setPos(x - 6, self._axis_y - self._node_radius - 20)
            order_label.setDefaultTextColor(QColor("#666666"))

    def mouseDoubleClickEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        if isinstance(item, _TimelineNodeItem):
            self.node_double_clicked.emit(item.node_id)
        else:
            super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        moved = False
        for item in self._node_items.values():
            if abs(item.pos().y() - self._axis_y) > 0.5:
                item.setPos(item.pos().x(), self._axis_y)
                moved = True
        super().mouseReleaseEvent(event)
        if moved or self._has_order_change():
            self._rearrange_labels()
            self.order_changed.emit(self.get_node_order())

    def _has_order_change(self) -> bool:
        current_order = self.get_node_order()
        original_order = [n.get("node_id", "") for n in self._nodes]
        return current_order != original_order

    def _rearrange_labels(self) -> None:
        items = sorted(self._node_items.values(), key=lambda it: it.pos().x())
        for idx, item in enumerate(items):
            x = 60 + idx * self._spacing
            item.setPos(x, self._axis_y)
        order = self.get_node_order()
        self._nodes.sort(
            key=lambda n: order.index(n.get("node_id", "")) if n.get("node_id", "") in order else len(order)
        )