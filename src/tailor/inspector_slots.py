"""Keep native graph inspectors resident when focus moves into an inset."""

from PySide6 import QtCore, QtWidgets


class InspectorSlot(QtWidgets.QStackedWidget):
    def minimumSizeHint(self):
        current = self.currentWidget()
        return current.minimumSizeHint() if current else QtCore.QSize()

    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current else QtCore.QSize()


def splitter_for(widget):
    parent = widget.parentWidget()
    return parent.parentWidget() if isinstance(parent, InspectorSlot) else parent


def prepare(splitter, slot, widget, *, anchor=None):
    """Preparent a completed inspector, keeping the current inspector visible."""
    # Window mode temporarily removes the figure at index zero. Inspector
    # roles stay the same while their physical splitter indexes shift.
    residents = getattr(splitter, '_resident_inspector_slots', {})
    container = residents.get(slot)
    if container is None or splitter.indexOf(container) < 0:
        container = anchor if anchor is not None else splitter.widget(slot)
        if container is not None and isinstance(container.parentWidget(), InspectorSlot):
            container = container.parentWidget()
    if not isinstance(container, InspectorSlot):
        sizes = splitter.sizes()
        previous = container
        index = splitter.indexOf(previous) if previous is not None else -1
        if index < 0:
            raise ValueError('Inspector anchor is not in its graph splitter')
        container = InspectorSlot()
        # QSplitter.replaceWidget does not keep a Python reference to a custom
        # subclass (unlike addWidget); retain the wrapper and its native pages.
        if not hasattr(splitter, '_resident_inspector_slots'):
            splitter._resident_inspector_slots = {}
        splitter._resident_inspector_slots[slot] = container
        container.setMinimumWidth(previous.minimumWidth())
        container.setMaximumWidth(previous.maximumWidth())
        splitter.replaceWidget(index, container)
        container.addWidget(previous)
        splitter.setSizes(sizes)
    if container.indexOf(widget) < 0:
        container.addWidget(widget)
    return container


def show(splitter, slot, widget):
    sizes = splitter.sizes()
    container = prepare(splitter, slot, widget)
    container.setCurrentWidget(widget)
    splitter.setSizes(sizes)
