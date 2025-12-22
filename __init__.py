from aqt import mw
from aqt.qt import *
from aqt.utils import showInfo
from datetime import datetime


# BACKEND

def get_retention_data(target_tag):
    # Fetch ease and tags for all Review cards (type 1)
    query = "SELECT r.ease, n.tags FROM revlog r JOIN cards c ON r.cid = c.id JOIN notes n ON c.nid = n.id WHERE r.type = 1"
    results = mw.col.db.all(query)
    
    pass_count = 0
    total_count = 0
    target_prefix = target_tag + "::"
    
    for ease, tags_string in results:
        # Fast fail
        if not tags_string or target_tag not in tags_string:
            continue

        # Manual split to avoid partial matches
        card_tags = tags_string.strip().split(" ")
        match = False
        for tag in card_tags:
            if tag == target_tag or tag.startswith(target_prefix):
                match = True
                break
        
        if match:
            total_count += 1
            if ease > 1: pass_count += 1
                
    ret = (pass_count / total_count * 100) if total_count > 0 else 0.0
    return pass_count, total_count, ret

def get_hourly_stats(target_tag):
    # Get timestamps (r.id) for circadian rhythm
    query = "SELECT r.id, r.ease, n.tags FROM revlog r JOIN cards c ON r.cid = c.id JOIN notes n ON c.nid = n.id WHERE r.type = 1"
    results = mw.col.db.all(query)
    
    hourly_data = {h: [0, 0] for h in range(24)}
    target_prefix = target_tag + "::"
    
    for log_id, ease, tags_string in results:
        if not tags_string or target_tag not in tags_string:
            continue
            
        card_tags = tags_string.strip().split(" ")
        match = False
        for tag in card_tags:
            if tag == target_tag or tag.startswith(target_prefix):
                match = True
                break
        
        if match:
            try:
                dt = datetime.fromtimestamp(log_id / 1000)
                hour = dt.hour
                hourly_data[hour][1] += 1
                if ease > 1: hourly_data[hour][0] += 1
            except:
                continue
    return hourly_data

def find_direct_children(parent_tag):
    # Scan all tags to find immediate sub-folders
    all_tags = mw.col.tags.all()
    children = set()
    prefix = parent_tag + "::"
    
    for tag in all_tags:
        if tag.startswith(prefix):
            remainder = tag[len(prefix):]
            direct_child = remainder.split("::")[0]
            children.add(prefix + direct_child)
            
    return sorted(list(children))

def has_grandchildren(tag_path):
    # Quick check for the "Expand" arrow
    prefix = tag_path + "::"
    for t in mw.col.tags.all():
        if t.startswith(prefix):
            return True
    return False

def find_deepest_weakness(start_tag):
    # Recursive search for the worst 'leaf' node
    current_tag = start_tag
    current_ret = 100.0
    
    for _ in range(10): 
        children = find_direct_children(current_tag)
        if not children:
            break 
            
        worst_child = None
        worst_score = 101.0
        found_data = False
        
        for child in children:
            p, t, r = get_retention_data(child)
            if t > 3: 
                found_data = True
                if r < worst_score:
                    worst_score = r
                    worst_child = child
        
        if found_data and worst_child:
            current_tag = worst_child
            current_ret = worst_score
        else:
            break
            
    if current_tag == start_tag:
        return None, 0.0
        
    return current_tag, current_ret


# UI: POPUPS & GRAPHS

class HourlyStatsDialog(QDialog):
    def __init__(self, target_tag, hourly_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Circadian Rhythm: {target_tag}")
        self.resize(800, 500)
        
        layout = QVBoxLayout()
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(self.generate_css_graph(target_tag, hourly_data))
        layout.addWidget(self.browser)
        self.setLayout(layout)
        
    def generate_css_graph(self, title, data):
        bars_html = ""
        for hour in range(24):
            passes, total = data[hour]
            if total > 0:
                ret = (passes / total) * 100
                tooltip = f"{hour}:00 - {ret:.1f}% ({passes}/{total})"
                
                if ret < 80: color = "#ff6b6b"
                elif ret < 90: color = "#feca57"
                else: color = "#1dd1a1"
                height = f"{ret}%"
            else:
                ret = 0
                tooltip = f"{hour}:00 - No Data"
                color = "#eee"
                height = "2px"

            bars_html += f"""
            <div style="flex: 1; margin: 0 2px; background-color: {color}; height: {height}; border-radius: 3px 3px 0 0; position: relative;" title="{tooltip}">
                <div style="position: absolute; bottom: -20px; left: 0; width: 100%; text-align: center; font-size: 10px; color: #555;">{hour}</div>
            </div>
            """

        return f"""
        <html>
        <body style="font-family: Segoe UI, sans-serif; padding: 20px; background-color: white;">
            <h2 style="margin-bottom: 5px;">{title}</h2>
            <div style="position: relative; height: 300px; border-left: 2px solid #333; border-bottom: 2px solid #333; background-color: #fafafa; margin-bottom: 30px; display: flex; align-items: flex-end; padding: 0 10px;">
                <div style="position: absolute; bottom: 90%; width: 100%; border-bottom: 1px dashed #1dd1a1; opacity: 0.5;"></div>
                <div style="position: absolute; bottom: 80%; width: 100%; border-bottom: 1px dashed #ff6b6b; opacity: 0.5;"></div>
                {bars_html}
            </div>
        </body></html>
        """


# UI: MAIN DASHBOARD

class ResultsTreeDialog(QDialog):
    def __init__(self, root_tag, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Analysis: {root_tag}")
        self.resize(950, 750)
        
        # Styles for Table and Header
        self.setStyleSheet("""
            QDialog { background-color: #f4f4f4; }
            QTreeWidget { background-color: white; border: 1px solid #dcdcdc; border-radius: 4px; font-size: 13px; }
            QHeaderView::section { background-color: #e1e1e1; padding: 4px; font-weight: bold; border: none; }
        """)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 1. Pre-calculate Header Stats
        p, t, r = get_retention_data(root_tag)
        weakest_tag, weakest_score = find_deepest_weakness(root_tag)

        # 2. Build Dashboard Header
        header_frame = QFrame()
        header_frame.setStyleSheet("QFrame { background-color: white; border-radius: 6px; border: 1px solid #d0d0d0; }")
        h_layout = QHBoxLayout()
        
        # Left Panel: Overall Stats
        stats_layout = QVBoxLayout()
        stat_color = "#27ae60" if r > 90 else ("#c0392b" if r < 80 else "#f39c12")
        
        title_lbl = QLabel(f"CATEGORY: {root_tag}")
        title_lbl.setStyleSheet("color: #555; font-size: 11px; font-weight: bold; border:none;")
        stat_lbl = QLabel(f"{r:.2f}% Retention")
        stat_lbl.setStyleSheet(f"color: {stat_color}; font-size: 24px; font-weight: bold; border:none;")
        sub_lbl = QLabel(f"Based on {t} total reviews")
        sub_lbl.setStyleSheet("color: #777; font-size: 12px; border:none;")
        
        stats_layout.addWidget(title_lbl)
        stats_layout.addWidget(stat_lbl)
        stats_layout.addWidget(sub_lbl)
        h_layout.addLayout(stats_layout)
        
        # Right Panel: Priority Focus (Next Up)
        if weakest_tag:
            full_parts = weakest_tag.split("::")
            leaf_name = full_parts[-1]
            parent_context = full_parts[-2] if len(full_parts) > 1 else ""

            rec_frame = QFrame()
            rec_frame.setStyleSheet("QFrame { background-color: #fff5f5; border: 1px solid #ffcdd2; border-radius: 4px; }")
            rec_layout = QVBoxLayout()
            rec_layout.setContentsMargins(10, 10, 10, 10)
            
            rec_title = QLabel("⚠️ PRIORITY FOCUS")
            rec_title.setStyleSheet("color: #c62828; font-weight: bold; font-size: 10px; border: none;")
            rec_name = QLabel(leaf_name)
            rec_name.setStyleSheet("color: #333; font-weight: bold; font-size: 16px; border: none;")
            
            if parent_context:
                rec_ctx = QLabel(f"in {parent_context}")
                rec_ctx.setStyleSheet("color: #555; font-style: italic; font-size: 11px; border: none;")
            
            rec_score = QLabel(f"Retention: {weakest_score:.1f}%")
            rec_score.setStyleSheet("color: #c62828; font-size: 12px; border: none; margin-top: 5px;")
            
            rec_layout.addWidget(rec_title)
            rec_layout.addWidget(rec_name)
            if parent_context: rec_layout.addWidget(rec_ctx)
            rec_layout.addWidget(rec_score)
            rec_frame.setLayout(rec_layout)
            
            h_layout.addStretch()
            h_layout.addWidget(rec_frame)
            
        header_frame.setLayout(h_layout)
        layout.addWidget(header_frame)
        
        # 3. Build Tree Widget
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Category", "Reviews", "Retention"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setIndentation(20)
        
        # Column Resizing
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 80)
        
        self.tree.itemExpanded.connect(self.on_item_expanded)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        
        layout.addWidget(self.tree)
        self.setLayout(layout)
        
        self.populate_children(self.tree.invisibleRootItem(), root_tag)

    def show_context_menu(self, position):
        item = self.tree.itemAt(position)
        if not item: return
        menu = QMenu()
        action_hourly = QAction("View Circadian Graph", self)
        action_hourly.triggered.connect(lambda: self.launch_hourly_stats(item))
        menu.addAction(action_hourly)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def launch_hourly_stats(self, item):
        full_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not full_path: return
        
        mw.app.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            data = get_hourly_stats(full_path)
        finally:
            mw.app.restoreOverrideCursor()
        d = HourlyStatsDialog(full_path, data, self)
        d.exec()

    def populate_children(self, parent_widget_item, parent_tag):
        mw.app.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            children_tags = find_direct_children(parent_tag)
            node_data = []
            for child_full_path in children_tags:
                p, t, r = get_retention_data(child_full_path)
                if t > 0:
                    node_data.append((child_full_path, t, r))
            
            node_data.sort(key=lambda x: x[2])
            
            for full_path, total, ret in node_data:
                display_name = full_path.split("::")[-1]
                item = QTreeWidgetItem(parent_widget_item)
                item.setText(0, display_name)
                item.setText(1, str(total))
                item.setText(2, f"{ret:.1f}%")
                
                item.setData(0, Qt.ItemDataRole.UserRole, full_path)
                
                item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                
                if ret < 80: 
                    item.setBackground(2, QColor("#ffebee")) 
                    item.setForeground(2, QColor("#c62828")) 
                elif ret > 90: 
                    item.setBackground(2, QColor("#e8f5e9")) 
                    item.setForeground(2, QColor("#2e7d32")) 
                
                if has_grandchildren(full_path):
                    dummy = QTreeWidgetItem(item)
                    dummy.setText(0, "Loading...")
        finally:
            mw.app.restoreOverrideCursor()

    def on_item_expanded(self, item):
        if item.childCount() == 1 and item.child(0).text(0) == "Loading...":
            item.removeChild(item.child(0))
            full_path = item.data(0, Qt.ItemDataRole.UserRole)
            self.populate_children(item, full_path)


# UI: STARTUP 

class TagSelectorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("True Retention Explorer")
        self.resize(400, 150)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Select a Root Tag (e.g. #Bootcamp):"))
        
        self.combo = QComboBox()
        self.combo.setEditable(True) 
        self.combo.addItems(sorted(mw.col.tags.all()))
        self.combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        layout.addWidget(self.combo)
        
        btn = QPushButton("Analyze Tree")
        btn.clicked.connect(self.accept_selection)
        layout.addWidget(btn)
        self.setLayout(layout)

    def accept_selection(self):
        selected_tag = self.combo.currentText()
        if selected_tag:
            self.close()
            d = ResultsTreeDialog(selected_tag, mw)
            d.exec()

def show_tool():
    d = TagSelectorDialog(mw)
    d.exec()

action = QAction("Check Tag Tree", mw)
qconnect(action.triggered, show_tool)
mw.form.menuTools.addAction(action)
