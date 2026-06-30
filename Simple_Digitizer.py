import sys
import csv
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                               QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
                               QDialog, QFormLayout, QLineEdit, QDialogButtonBox)
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QCursor
from PySide6.QtCore import Qt, QRect

# 1. X, Y 동시 입력을 위한 커스텀 다이얼로그 클래스
class CoordInputDialog(QDialog):
    def __init__(self, title, default_x=0.0, default_y=0.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(250, 120)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.edit_x = QLineEdit(str(default_x))
        self.edit_y = QLineEdit(str(default_y))
 
        form_layout.addRow("Real X:", self.edit_x)
        form_layout.addRow("Real Y:", self.edit_y)
        layout.addLayout(form_layout)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_values(self):
        try: x = float(self.edit_x.text())
        except ValueError: x = 0.0
        try: y = float(self.edit_y.text())
        except ValueError: y = 0.0
        return x, y

# 2. 드래그앤드롭을 지원하는 커스텀 라벨 클래스
class DragDropLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setAcceptDrops(True)
        self.drop_callback = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.drop_callback:
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                    self.drop_callback(file_path)
                    break

# 3. 메인 프로그램
class ProfessionalDigitizer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Professional Digitizer (Drag&Drop, Clipboard Ctrl+V)")
        self.resize(1100, 700)

        self.image_pixmap = None
        self.points = [] 
        self.pixel_points = [] 

        self.is_calibrated = False
        self.calib_state = 0 
        self.p0_pix = (0, 0); self.p0_real = (0.0, 0.0)
        self.p1_pix = (0, 0); self.p1_real = (0.0, 0.0)
        self.p2_pix = (0, 0); self.p2_real = (0.0, 0.0)

        self.init_ui()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        self.image_label = DragDropLabel("이미지 파일 열기, 드래그 앤 드롭, 또는 Ctrl+V (붙여넣기) 하세요.")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #e0e0e0; border: 2px dashed #aaa;")
        self.image_label.setMinimumSize(1, 1) 
        self.image_label.setMouseTracking(True)
        self.image_label.mousePressEvent = self.on_image_clicked
        self.image_label.mouseMoveEvent = self.on_image_mouse_move
        self.image_label.drop_callback = self.load_image_from_path
        main_layout.addWidget(self.image_label, stretch=3)

        control_layout = QVBoxLayout()
        main_layout.addLayout(control_layout, stretch=2)

        upper_right_layout = QHBoxLayout()
        control_layout.addLayout(upper_right_layout)

        self.mag_label = QLabel("돋보기 뷰어")
        self.mag_label.setFixedSize(200, 200)
        self.mag_label.setAlignment(Qt.AlignCenter)
        self.mag_label.setStyleSheet("background-color: #fff; border: 2px solid #333;")
        upper_right_layout.addWidget(self.mag_label)

        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(2)
        self.table_widget.setHorizontalHeaderLabels(["Real_X", "Real_Y"])
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_widget.setEditTriggers(QTableWidget.NoEditTriggers)
        upper_right_layout.addWidget(self.table_widget)

        self.status_label = QLabel("상태: 이미지 로드 대기")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-weight: bold; color: #d32f2f; padding: 10px 0;")
        control_layout.addWidget(self.status_label)

        self.btn_load = QPushButton("1. 이미지 파일 열기")
        self.btn_calib = QPushButton("2. 3점 축 보정 시작")
        self.btn_undo = QPushButton("실행 취소 (Undo)")
        self.btn_clear = QPushButton("추출된 데이터 지우기")
        self.btn_save = QPushButton("3. CSV로 저장")

        control_layout.addWidget(self.btn_load)
        control_layout.addWidget(self.btn_calib)
        control_layout.addWidget(self.btn_undo)
        control_layout.addWidget(self.btn_clear)
        control_layout.addStretch()
        control_layout.addWidget(self.btn_save)

        self.btn_calib.setEnabled(False)
        self.btn_save.setEnabled(False)

        self.btn_load.clicked.connect(self.open_file_dialog)
        self.btn_calib.clicked.connect(self.start_calibration)
        self.btn_undo.clicked.connect(self.undo_point)
        self.btn_clear.clicked.connect(self.clear_points)
        self.btn_save.clicked.connect(self.save_csv)

    # =============== 추가 및 수정된 이미지 로딩 로직 ===============

    def keyPressEvent(self, event):
        # Ctrl + V 단축키 입력 감지
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_V:
            self.paste_from_clipboard()
        super().keyPressEvent(event)

    def paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        # 1. 캡처 도구 등으로 복사한 순수 '이미지 데이터'가 클립보드에 있는 경우
        if mime_data.hasImage():
            pixmap = clipboard.pixmap()
            self.set_image_pixmap(pixmap)
            
        # 2. 탐색기에서 '이미지 파일' 자체를 복사한 경우
        elif mime_data.hasUrls():
            for url in mime_data.urls():
                file_path = url.toLocalFile()
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                    self.load_image_from_path(file_path)
                    break

    def open_file_dialog(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "이미지 열기", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if file_name: self.load_image_from_path(file_name)

    def load_image_from_path(self, file_path):
        pixmap = QPixmap(file_path)
        if not pixmap.isNull():
            self.set_image_pixmap(pixmap)

    def set_image_pixmap(self, pixmap):
        # 공통으로 사용되는 이미지 초기화 및 적용 함수
        self.image_pixmap = pixmap
        self.points.clear()
        self.pixel_points.clear()
        self.is_calibrated = False
        self.calib_state = 0
        self.btn_calib.setEnabled(True)
        self.btn_save.setEnabled(False)
        self.image_label.setCursor(QCursor(Qt.CrossCursor))
        self.image_label.setStyleSheet("background-color: #e0e0e0; border: 1px solid #aaa;")
        self.update_status("상태: 3점 축 보정(Calibration)을 진행해주세요.")
        self.update_image_display()
        self.update_table()

    # ==============================================================

    def update_status(self, msg):
        self.status_label.setText(msg)

    def update_table(self):
        self.table_widget.setRowCount(0)
        for i, (rx, ry) in enumerate(self.points):
            self.table_widget.insertRow(i)
            self.table_widget.setItem(i, 0, QTableWidgetItem(f"{rx:.6f}"))
            self.table_widget.setItem(i, 1, QTableWidgetItem(f"{ry:.6f}"))
        self.table_widget.scrollToBottom()

    def update_image_display(self):
        if self.image_pixmap is None: return

        display_pixmap = self.image_pixmap.copy()
        painter = QPainter(display_pixmap)
        
        painter.setPen(QPen(QColor(255, 0, 0), 8))
        for x, y in self.pixel_points:
            painter.drawPoint(x, y)
            
        painter.setPen(QPen(QColor(0, 0, 255), 8)) # P0
        if self.calib_state > 1 or self.is_calibrated:
            painter.drawPoint(self.p0_pix[0], self.p0_pix[1])
            
        painter.setPen(QPen(QColor(0, 200, 200), 8)) # P1
        if self.calib_state > 2 or self.is_calibrated:
            painter.drawPoint(self.p1_pix[0], self.p1_pix[1])
            painter.setPen(QPen(QColor(0, 200, 200), 3, Qt.DashLine))
            painter.drawLine(self.p0_pix[0], self.p0_pix[1], self.p1_pix[0], self.p1_pix[1])
            
        painter.setPen(QPen(QColor(255, 0, 255), 8)) # P2
        if self.is_calibrated:
            painter.drawPoint(self.p2_pix[0], self.p2_pix[1])
            painter.setPen(QPen(QColor(255, 0, 255), 3, Qt.DashLine))
            painter.drawLine(self.p0_pix[0], self.p0_pix[1], self.p2_pix[0], self.p2_pix[1])

        painter.end()
        scaled_pixmap = display_pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        if self.image_pixmap: self.update_image_display()
        super().resizeEvent(event)

    def get_real_pixel_coords(self, event_pos):
        label_w, label_h = self.image_label.width(), self.image_label.height()
        if self.image_label.pixmap() is None: return None, None
        pix_w, pix_h = self.image_label.pixmap().width(), self.image_label.pixmap().height()
        offset_x, offset_y = (label_w - pix_w) / 2, (label_h - pix_h) / 2
        click_x, click_y = event_pos.x(), event_pos.y()

        if offset_x <= click_x <= offset_x + pix_w and offset_y <= click_y <= offset_y + pix_h:
            orig_w, orig_h = self.image_pixmap.width(), self.image_pixmap.height()
            return int((click_x - offset_x) * (orig_w / pix_w)), int((click_y - offset_y) * (orig_h / pix_h))
        return None, None

    def on_image_mouse_move(self, event):
        if self.image_pixmap is None: return
        orig_x, orig_y = self.get_real_pixel_coords(event.position())
        if orig_x is not None:
            rect = QRect(orig_x - 20, orig_y - 20, 40, 40)
            zoomed = self.image_pixmap.copy(rect).scaled(200, 200, Qt.KeepAspectRatio, Qt.FastTransformation)
            painter = QPainter(zoomed)
            painter.setPen(QPen(QColor(0, 255, 0), 2))
            painter.drawLine(100, 0, 100, 200)
            painter.drawLine(0, 100, 200, 100)
            painter.end()
            self.mag_label.setPixmap(zoomed)

    def start_calibration(self):
        self.points.clear(); self.pixel_points.clear()
        self.is_calibrated = False; self.calib_state = 1
        self.btn_save.setEnabled(False)
        self.update_status("단계 1/3: 그래프의 [첫 번째 기준점]을 클릭하세요.")
        self.update_image_display()
        self.update_table()

    def on_image_clicked(self, event):
        if self.image_pixmap is None: return
        orig_x, orig_y = self.get_real_pixel_coords(event.position())
        if orig_x is None: return

        if self.calib_state == 1:
            dialog = CoordInputDialog("Point 1 (원점) 실제 좌표 입력", 0.0, 0.0, self)
            if dialog.exec(): 
                self.p0_pix = (orig_x, orig_y)
                self.p0_real = dialog.get_values()
                self.calib_state = 2
                self.update_status("단계 2/3: 두 번째 기준점을 클릭하세요.")
            else: self.calib_state = 0 

        elif self.calib_state == 2:
            dialog = CoordInputDialog("Point 2 실제 좌표 입력", 0.0, 0.0, self)
            if dialog.exec():
                if self.p0_pix == (orig_x, orig_y):
                    QMessageBox.warning(self, "오류", "첫 번째 점과 같은 위치입니다.")
                    return
                self.p1_pix = (orig_x, orig_y)
                self.p1_real = dialog.get_values()
                self.calib_state = 3
                self.update_status("단계 3/3: 세 번째 기준점을 클릭하세요.")
            else: self.calib_state = 1

        elif self.calib_state == 3:
            dialog = CoordInputDialog("Point 3 실제 좌표 입력", 0.0, 0.0, self)
            if dialog.exec():
                det = (self.p1_pix[0] - self.p0_pix[0]) * (orig_y - self.p0_pix[1]) - \
                      (self.p1_pix[1] - self.p0_pix[1]) * (orig_x - self.p0_pix[0])
                if det == 0:
                    QMessageBox.warning(self, "오류", "선택한 세 점이 일직선에 있습니다. 다시 설정하세요.")
                    self.calib_state = 1; return

                self.p2_pix = (orig_x, orig_y)
                self.p2_real = dialog.get_values()
                self.calib_state = 0; self.is_calibrated = True
                self.btn_save.setEnabled(True)
                self.update_status("보정 완료! 추출할 데이터 점들을 클릭하세요.")
            else: self.calib_state = 2

        elif self.is_calibrated:
            vxx = self.p1_pix[0] - self.p0_pix[0]
            vxy = self.p1_pix[1] - self.p0_pix[1]
            vyx = self.p2_pix[0] - self.p0_pix[0]
            vyy = self.p2_pix[1] - self.p0_pix[1]

            tx = orig_x - self.p0_pix[0]
            ty = orig_y - self.p0_pix[1]

            det = vxx * vyy - vxy * vyx
            alpha = (tx * vyy - ty * vyx) / det
            beta = (vxx * ty - vxy * tx) / det

            real_x = self.p0_real[0] + alpha * (self.p1_real[0] - self.p0_real[0]) + beta * (self.p2_real[0] - self.p0_real[0])
            real_y = self.p0_real[1] + alpha * (self.p1_real[1] - self.p0_real[1]) + beta * (self.p2_real[1] - self.p0_real[1])
            
            self.points.append((real_x, real_y))
            self.pixel_points.append((orig_x, orig_y))
            self.update_table()

        self.update_image_display()

    def undo_point(self):
        if self.pixel_points and self.points:
            self.pixel_points.pop(); self.points.pop()
            self.update_image_display()
            self.update_table()

    def clear_points(self):
        self.pixel_points.clear(); self.points.clear()
        self.update_image_display()
        self.update_table()

    def save_csv(self):
        if not self.points:
            QMessageBox.warning(self, "경고", "저장할 데이터가 없습니다.")
            return

        file_name, _ = QFileDialog.getSaveFileName(self, "CSV 저장", "digitized_data.csv", "CSV Files (*.csv)")
        if file_name:
            try:
                with open(file_name, mode='w', newline='', encoding='utf-8') as file:
                    writer = csv.writer(file)
                    writer.writerow(['Real_X', 'Real_Y'])
                    for p in self.points:
                        writer.writerow([f"{p[0]:.6f}", f"{p[1]:.6f}"])
                QMessageBox.information(self, "성공", "데이터 저장 성공.")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"저장 중 오류: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ProfessionalDigitizer()
    window.show()
    sys.exit(app.exec())