"""Direct default format editing, reusing GraphDefaults capture/application."""
import json
from PySide6 import QtCore, QtGui, QtWidgets
from tailor.compact_controls import CheckButton
from tailor.settings_pages import page, card, row, button


def build(widget):
    from tailor import graph_defaults as defaults
    from tailor.plot_types import MODE_ITEMS
    from tailor.line_styles import LINE_STYLES
    from tailor.ui_widgets import ColorButton, FontFamilyCombo
    root = QtWidgets.QVBoxLayout(widget); root.setContentsMargins(28, 28, 28, 24); root.setSpacing(12)
    title = QtWidgets.QLabel('默认格式'); title.setObjectName('settingsPageTitle')
    clear = button('一键清除',lambda:clear_defaults())
    clear.setObjectName('clearDrawingDefaults'); clear.setMaximumWidth(120)
    clear.setToolTip('清除全部默认格式和旧坐标轴默认值；不修改已有图形和其他设置。')
    from tailor.ui_theme import action_icon
    clear.setIcon(action_icon('delete',clear,'#d8504a'))
    clear.setStyleSheet('QPushButton {color:#d8504a;}')
    root.addWidget(row(title,clear)); widget.clear_button=clear
    note = QtWidgets.QLabel('仅用于之后新建的图形，不改动当前或已保存的工程。设置立即保存。'); note.setWordWrap(True); root.addWidget(note)
    widget.controls = {}

    def put(group, key, value):
        data = defaults.read(group) or {}; data[key] = value
        defaults.settings().setValue(group, json.dumps(data, ensure_ascii=False))
        sync_status()

    def combo(items, value, callback):
        box = QtWidgets.QComboBox()
        for label, key in items: box.addItem(label, key)
        box.setCurrentIndex(max(0, box.findData(value)))
        box.activated.connect(lambda i: callback(box.itemData(i))); return box

    def spin(value, low, high, callback, decimals=1):
        from tailor.compact_controls import CompactDoubleSpinBox
        box = CompactDoubleSpinBox(); box.setRange(low, high); box.setDecimals(decimals)
        box.setKeyboardTracking(False); box.setValue(value); box.valueChanged.connect(callback); return box

    def color(value, callback):
        box = ColorButton(value)
        def choose():
            result = QtWidgets.QColorDialog.getColor(QtGui.QColor(box.text()), widget)
            if result.isValid(): box.setText(result.name()); callback(result.name())
        box.clicked.connect(choose); return box

    curve = defaults.new_style()
    form = card(root, '曲线与数据点')
    for key, label, control in (
        ('mode', '绘制方式', combo(MODE_ITEMS, curve.mode, lambda v: put('curve', 'mode', v))),
        ('line_width', '线条宽度', spin(curve.line_width, .1, 20, lambda v: put('curve', 'line_width', v))),
        ('line_style', '线条样式', combo(LINE_STYLES, curve.line_style, lambda v: put('curve','line_style',v))),
        ('color', '默认颜色', color(curve.color, lambda v: put('curve', 'color', v))),
        ('opacity', '不透明度', spin(curve.opacity*100, 0, 100, lambda v: put('curve', 'opacity', v/100), 0)),
        ('marker_size', '标记大小', spin(curve.marker_size, 1, 30, lambda v: put('curve','marker_size',v))),
        ('marker', '标记形状', combo([('圆形','o'),('方形','s'),('三角形','t'),('菱形','d'),('加号','+'),('叉号','x'),('星形','star')],curve.marker,lambda v:put('curve','marker',v))),
    ):
        form.addRow(label, row(control, QtWidgets.QLabel({'line_width':'px/pt','marker_size':'px/pt','opacity':'%'}.get(key,''))))
        if key in {'line_width','marker_size'}:control.setToolTip('二维、柱状和组图使用px；三维使用pt。沿用绘图后端的原数值单位。')
        widget.controls[key] = control
    CAP_ITEMS = [("圆形端点","round"),("平直端点","flat"),("方形延伸端点","square")]
    JOIN_ITEMS = [("圆角","round"),("斜角","bevel"),("尖角","miter")]
    for key,label,items in [('cap','线端',CAP_ITEMS),('join','连接',JOIN_ITEMS)]:
        control=combo(items,getattr(curve,key),lambda v,k=key:put('curve',k,v))
        form.addRow(label,control);widget.controls[key]=control
    fill = CheckButton('曲线下方填充'); fill.setChecked(curve.fill); fill.toggled.connect(lambda v:put('curve','fill',v))
    marker_fill = CheckButton('填充数据点'); marker_fill.setChecked(curve.marker_fill); marker_fill.toggled.connect(lambda v:put('curve','marker_fill',v))
    fill_color=color(curve.fill_color, lambda v:put('curve','fill_color',v))
    widget.controls.update(fill=fill,marker_fill=marker_fill,fill_color=fill_color)
    form.addRow(row(fill, marker_fill)); form.addRow('填充颜色',fill_color)
    form = card(root, '文字默认格式')
    target = combo([('普通文字/标注','general'),('四轴标题','labels'),('四轴刻度','ticks'),('图例','legend')], 'general', lambda v:load_font())
    size = spin(14, 6, 48, lambda v:save_font(), 0)
    family = FontFamilyCombo(); family.add_system_fonts(); family.addItem('系统无衬线','sans-serif'); family.setEditable(True)
    family.lineEdit().setMaxLength(128)
    bold = CheckButton('粗体'); italic = CheckButton('斜体'); underline = CheckButton('下划线')
    ink = color('#202020', lambda v:save_font())
    orientation = combo([('横排','horizontal'),('逆90度','ccw90'),('顺90度','cw90')], 'horizontal', lambda v:save_font())
    box_fill = CheckButton('文本填充')
    box_color = color('#ffffff', lambda v:save_font())
    box_opacity = spin(18,0,100,lambda v:save_font(),0)
    form.addRow('文字对象', target); form.addRow('字体', family); form.addRow('字号', row(size, QtWidgets.QLabel('pt')))
    form.addRow('样式', row(bold, italic, underline)); form.addRow('颜色', ink); form.addRow('文本排列', orientation)
    form.addRow(row(box_fill,box_color)); form.addRow('填充透明',row(box_opacity,QtWidgets.QLabel('%')))
    loading = [False]
    def keys():
        key = target.currentData()
        return [a + ('_label' if key=='labels' else '_ticks') for a in ('x','y','right','top')] if key in {'labels','ticks'} else ['annotation:default' if key=='general' else key]
    def load_font():
        loading[0] = True
        values = defaults.new_style(); group = target.currentData()
        spec = values.text_styles.get(keys()[0], {})
        size.setValue(spec.get('size', values.font_size)); family.setCurrentText(spec.get('family', values.font_family))
        bold.setChecked(spec.get('bold',False)); italic.setChecked(spec.get('italic',False)); underline.setChecked(spec.get('underline',False))
        ink.setText(spec.get('color','#202020')); orientation.setCurrentIndex(max(0,orientation.findData(spec.get('text_orientation','horizontal'))))
        box_fill.setChecked(bool(spec.get('text_fill'))); box_color.setText(spec.get('text_fill') or '#ffffff'); box_opacity.setValue(spec.get('text_fill_opacity',.18)*100)
        for control in (orientation,box_fill,box_color,box_opacity): control.setEnabled(group=='general')
        loading[0] = False
    def save_font():
        if loading[0]: return
        data = defaults.read('fonts') or {}
        if target.currentData() == 'general': data.update(font_size=size.value(),font_family=family.currentText() or 'sans-serif')
        styles = data.setdefault('text_styles',{})
        for key in keys(): styles[key]={**styles.get(key,{}),'size':size.value(),'family':family.currentText() or 'sans-serif','bold':bold.isChecked(),'italic':italic.isChecked(),'underline':underline.isChecked(),'color':ink.text(),'text_orientation':orientation.currentData()}
        if target.currentData()=='general':
            styles['annotation:default'].update(text_fill=box_color.text() if box_fill.isChecked() else '',text_fill_opacity=box_opacity.value()/100)
        defaults.settings().setValue('fonts',json.dumps(data,ensure_ascii=False))
        sync_status()
    family.currentTextChanged.connect(lambda *args:save_font())
    for control in (bold,italic,underline): control.toggled.connect(lambda *args:save_font())
    box_fill.toggled.connect(lambda *args:save_font())
    load_font(); widget.font_target=target; widget.font_size=size
    widget.font_orientation=orientation; widget.font_fill=box_fill; widget.font_fill_opacity=box_opacity
    form = card(root, '从当前图形保存更多格式')
    widget.rows = {}
    status = QtWidgets.QLabel(); status.setWordWrap(True)
    for key,(label,_) in defaults.GROUPS.items():
        use = button('使用当前',lambda k=key:store(k)); reset = button('恢复预设',lambda k=key:reset_group(k))
        form.addRow(label,row(use,reset)); widget.rows[key]=(use,reset)
    def store(key):
        plot = defaults.current_plot()
        if plot:
            defaults.save(plot,key); status.setText('已保存“'+defaults.GROUPS[key][0]+'”，之后新图使用此格式。')
            refresh()
        else: status.setText('请先切到一张图形，再保存其格式。')
    def reset_group(key):
        defaults.settings().remove(key); status.setText('已恢复“'+defaults.GROUPS[key][0]+'”的预设。'); refresh()
    def clear_defaults():
        defaults.clear_all();refresh()
        status.setText('已清除全部默认格式和旧坐标轴默认值。新图使用预设，已有图形和其他设置保持不变。')
    def refresh():
        values = defaults.new_style()
        for key,control in widget.controls.items():
            with QtCore.QSignalBlocker(control):
                value = getattr(values,key)
                if key=='opacity': value *= 100
                if isinstance(control,QtWidgets.QComboBox): control.setCurrentIndex(max(0,control.findData(value)))
                elif isinstance(control,QtWidgets.QPushButton):
                    if control.isCheckable():control.setChecked(value)
                    else:control.setText(value)
                else: control.setValue(value)
        load_font()
        sync_status()
    def sync_status():
        for key,(use,reset) in getattr(widget,'rows',{}).items():
            use.setEnabled(defaults.current_plot() is not None)
            use.setText('更新当前' if defaults.read(key) is not None else '使用当前')
            reset.setEnabled(defaults.settings().contains(key))
    widget.refresh=refresh
    root.addWidget(status)
    root.addStretch()
    refresh()
