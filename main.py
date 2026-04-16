import cv2
import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions
import numpy as np
import threading
import queue
import time
import platform
import subprocess
import os
import sys
import math
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any, Callable
from collections import deque
import webbrowser
import json
from PIL import Image, ImageDraw, ImageFont

# ==================== КОНФИГУРАЦИЯ ====================

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# Константы
SAFETY_LOCK_SECONDS = 5.0  # Время для блокировки при закрытых глазах
CLAP_COOLDOWN_SECONDS = 2.0  # Кулдаун хлопка в секундах
FPS_HISTORY_SIZE = 30      # Размер истории FPS

# Цвета (BGR)
COLOR_GREEN = (0, 255, 0)    # Левая рука (громкость)
COLOR_RED = (0, 0, 255)      # Правая рука (пистолет)
COLOR_YELLOW = (0, 255, 255) # Отладочная информация
COLOR_WHITE = (255, 255, 255)
COLOR_CYAN = (255, 255, 0)
COLOR_BLUE = (255, 0, 0)

# ==================== КЛАССЫ ДАННЫХ ====================

class Mode(Enum):
    """Режимы работы приложения"""
    DEBUG = "debug"       # Отладочный режим с полной визуализацией
    PRODUCTION = "silent" # Производственный режим (минимальная нагрузка)


@dataclass
class CalibrationData:
    """Данные калибровки сессии"""
    # Калибровка громкости (в пикселях)
    vol_max_dist: float = 200.0
    vol_min_dist: float = 50.0

    # Калибровка глаз (EAR - Eye Aspect Ratio)
    eye_open_threshold: float = 0.25    # Порог открытых глаз
    eye_closed_threshold: float = 0.15  # Порог закрытых глаз

    # Флаги состояния
    is_calibrated: bool = False

    def to_dict(self) -> dict:
        return {
            'vol_max_dist': self.vol_max_dist,
            'vol_min_dist': self.vol_min_dist,
            'eye_open_threshold': self.eye_open_threshold,
            'eye_closed_threshold': self.eye_closed_threshold,
            'is_calibrated': self.is_calibrated
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CalibrationData':
        return cls(
            vol_max_dist=data.get('vol_max_dist', 200.0),
            vol_min_dist=data.get('vol_min_dist', 50.0),
            eye_open_threshold=data.get('eye_open_threshold', 0.25),
            eye_closed_threshold=data.get('eye_closed_threshold', 0.15),
            is_calibrated=data.get('is_calibrated', False)
        )


@dataclass  
class GestureState:
    """Текущее состояние жестов"""
    # Жесты рук
    gun_active: bool = False
    victory_active: bool = False
    clap_active: bool = False

    # Состояние глаз
    eyes_closed: bool = False
    eyes_closed_start: Optional[float] = None

    # Таймеры
    last_clap_time: float = 0.0
    last_victory_time: float = 0.0


# ==================== ИНДЕКСЫ LANDMARKS ====================

class HandLandmark:
    """Индексы landmarks рук MediaPipe"""
    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_FINGER_MCP = 5
    INDEX_FINGER_PIP = 6
    INDEX_FINGER_DIP = 7
    INDEX_FINGER_TIP = 8
    MIDDLE_FINGER_MCP = 9
    MIDDLE_FINGER_PIP = 10
    MIDDLE_FINGER_DIP = 11
    MIDDLE_FINGER_TIP = 12
    RING_FINGER_MCP = 13
    RING_FINGER_PIP = 14
    RING_FINGER_DIP = 15
    RING_FINGER_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20


class FaceLandmarkIndices:
    """Индексы landmarks лица для глаз (468-точечная модель)"""
    # Левый глаз (указаны как в зеркальном отображении)
    LEFT_EYE_OUTER = 33
    LEFT_EYE_TOP_1 = 160
    LEFT_EYE_TOP_2 = 159
    LEFT_EYE_INNER = 133
    LEFT_EYE_BOTTOM_1 = 144
    LEFT_EYE_BOTTOM_2 = 145

    # Правый глаз
    RIGHT_EYE_OUTER = 362
    RIGHT_EYE_TOP_1 = 385
    RIGHT_EYE_TOP_2 = 386
    RIGHT_EYE_INNER = 263
    RIGHT_EYE_BOTTOM_1 = 380
    RIGHT_EYE_BOTTOM_2 = 374

    # Индексы для расчета EAR
    LEFT_EAR_INDICES = [33, 160, 158, 133, 153, 144]
    RIGHT_EAR_INDICES = [362, 385, 387, 263, 373, 380]


# Соединения для отрисовки скелета руки
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),           # Большой палец
    (0, 5), (5, 6), (6, 7), (7, 8),           # Указательный
    (0, 9), (9, 10), (10, 11), (11, 12),      # Средний
    (0, 13), (13, 14), (14, 15), (15, 16),    # Безымянный
    (0, 17), (17, 18), (18, 19), (19, 20),    # Мизинец
    (5, 9), (9, 13), (13, 17)                 # Ладонь
]

# ==================== МЕНЕДЖЕР СИСТЕМНЫХ ДЕЙСТВИЙ ====================

class SystemActionHandler:
    """
    Обработчик системных действий (громкость, блокировка экрана)
    Кроссплатформенная реализация для Windows и Arch Linux
    """

    def __init__(self):
        self.volume_controller = None
        self._init_volume()

    def _init_volume(self):
        """Инициализация управления громкостью"""
        if IS_WINDOWS:
            try:
                import ctypes
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(
                    IAudioEndpointVolume._iid_, CLSCTX_ALL, None
                )
                self.volume_controller = interface.QueryInterface(IAudioEndpointVolume)
            except Exception as e:
                print(f"[WARN] Не удалось инициализировать управление громкостью Windows: {e}")

    def set_volume(self, percent: int) -> int:
        """
        Установка системной громкости (0-100)

        Args:
            percent: Уровень громкости в процентах

        Returns:
            int: Фактически установленный уровень
        """
        percent = max(0, min(100, percent))

        try:
            if IS_WINDOWS and self.volume_controller:
                self.volume_controller.SetMasterVolumeLevelScalar(percent / 100.0, None)

            elif IS_LINUX:
                subprocess.run(
                    ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"],
                    check=True, capture_output=True
                )

        except Exception as e:
            pass  # В Production mode не выводим ошибки

        return percent

    def get_volume(self) -> int:
        """Получение текущей системной громкости"""
        try:
            if IS_WINDOWS and self.volume_controller:
                return int(self.volume_controller.GetMasterVolumeLevelScalar() * 100)

            elif IS_LINUX:
                result = subprocess.run(
                    ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                    capture_output=True, text=True
                )
                import re
                match = re.search(r'(\d+)%', result.stdout)
                return int(match.group(1)) if match else 50

        except Exception:
            pass

        return 50

    def lock_screen(self):
        """Блокировка рабочей станции"""
        try:
            if IS_WINDOWS:
                import ctypes
                ctypes.windll.user32.LockWorkStation()

            elif IS_LINUX:
                # Пробуем различные методы для Arch Linux
                try:
                    subprocess.run(["loginctl", "lock-session"], check=True, capture_output=True)
                except:
                    try:
                        subprocess.run(["xdg-screensaver", "lock"], check=True, capture_output=True)
                    except:
                        subprocess.run(["i3lock", "-c", "000000"], check=False)

        except Exception as e:
            print(f"[ERROR] Не удалось заблокировать экран: {e}")

    def open_url(self, url: str):
        """Открытие URL в браузере"""
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"[ERROR] Не удалось открыть URL: {e}")


# ==================== ДЕТЕКТОР ЖЕСТОВ ====================

class GestureDetector:
    """Детектор жестов рук и состояния глаз"""

    @staticmethod
    def is_gun_gesture(landmarks: List[Any]) -> bool:
        """
        Жест "пистолет": большой и указательный пальцы подняты, остальные согнуты

        Args:
            landmarks: Список landmarks руки

        Returns:
            bool: True если жест обнаружен
        """
        # Получаем точки пальцев
        thumb_tip = landmarks[HandLandmark.THUMB_TIP]
        thumb_ip = landmarks[HandLandmark.THUMB_IP]
        index_tip = landmarks[HandLandmark.INDEX_FINGER_TIP]
        index_pip = landmarks[HandLandmark.INDEX_FINGER_PIP]
        middle_tip = landmarks[HandLandmark.MIDDLE_FINGER_TIP]
        middle_pip = landmarks[HandLandmark.MIDDLE_FINGER_PIP]
        ring_tip = landmarks[HandLandmark.RING_FINGER_TIP]
        ring_pip = landmarks[HandLandmark.RING_FINGER_PIP]
        pinky_tip = landmarks[HandLandmark.PINKY_TIP]
        pinky_pip = landmarks[HandLandmark.PINKY_PIP]

        # Проверяем подняты ли большой и указательный (y уменьшается вверх)
        thumb_up = thumb_tip.y < thumb_ip.y
        index_up = index_tip.y < index_pip.y

        # Проверяем согнуты ли остальные
        middle_bent = middle_tip.y > middle_pip.y
        ring_bent = ring_tip.y > ring_pip.y
        pinky_bent = pinky_tip.y > pinky_pip.y

        return thumb_up and index_up and middle_bent and ring_bent and pinky_bent

    @staticmethod
    def is_victory_gesture(landmarks: List[Any]) -> bool:
        """
        Жест "Victory" (V): указательный и средний подняты и разведены

        Args:
            landmarks: Список landmarks руки

        Returns:
            bool: True если жест обнаружен
        """
        index_tip = landmarks[HandLandmark.INDEX_FINGER_TIP]
        index_pip = landmarks[HandLandmark.INDEX_FINGER_PIP]
        middle_tip = landmarks[HandLandmark.MIDDLE_FINGER_TIP]
        middle_pip = landmarks[HandLandmark.MIDDLE_FINGER_PIP]
        ring_tip = landmarks[HandLandmark.RING_FINGER_TIP]
        ring_pip = landmarks[HandLandmark.RING_FINGER_PIP]
        pinky_tip = landmarks[HandLandmark.PINKY_TIP]
        pinky_pip = landmarks[HandLandmark.PINKY_PIP]

        # Подняты ли указательный и средний
        index_up = index_tip.y < index_pip.y
        middle_up = middle_tip.y < middle_pip.y

        # Согнуты ли остальные
        ring_bent = ring_tip.y > ring_pip.y
        pinky_bent = pinky_tip.y > pinky_pip.y

        # Проверяем разведение пальцев (V-форма)
        distance = math.sqrt(
            (index_tip.x - middle_tip.x)**2 + 
            (index_tip.y - middle_tip.y)**2
        )
        separated = distance > 0.05  # Нормализованное расстояние

        return index_up and middle_up and ring_bent and pinky_bent and separated

    @staticmethod
    def is_clap_gesture(left_hand: List[Any], right_hand: List[Any]) -> Tuple[bool, float]:
        """
        Обнаружение хлопка по расстоянию между ладонями

        Args:
            left_hand: Landmarks левой руки
            right_hand: Landmarks правой руки

        Returns:
            Tuple[bool, float]: (обнаружен ли хлопок, расстояние)
        """
        left_wrist = left_hand[HandLandmark.WRIST]
        right_wrist = right_hand[HandLandmark.WRIST]

        distance = math.sqrt(
            (left_wrist.x - right_wrist.x)**2 + 
            (left_wrist.y - right_wrist.y)**2
        )

        # Порог для хлопка (нормализованные координаты)
        return distance < 0.12, distance

    @staticmethod
    def calculate_ear(landmarks: List[Any], eye_indices: List[int]) -> float:
        """
        Расчет Eye Aspect Ratio (EAR) для обнаружения морганий
        EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)

        Args:
            landmarks: Landmarks лица
            eye_indices: Индексы точек глаза [внешний, верх1, верх2, внутренний, низ1, низ2]

        Returns:
            float: Значение EAR
        """
        try:
            p1 = landmarks[eye_indices[0]]  # Внешний угол
            p2 = landmarks[eye_indices[1]]  # Верх 1
            p3 = landmarks[eye_indices[2]]  # Верх 2
            p4 = landmarks[eye_indices[3]]  # Внутренний угол
            p5 = landmarks[eye_indices[4]]  # Низ 1
            p6 = landmarks[eye_indices[5]]  # Низ 2

            # Вертикальные расстояния
            v1 = math.sqrt((p2.x - p6.x)**2 + (p2.y - p6.y)**2)
            v2 = math.sqrt((p3.x - p5.x)**2 + (p3.y - p5.y)**2)

            # Горизонтальное расстояние
            h = math.sqrt((p1.x - p4.x)**2 + (p1.y - p4.y)**2)

            if h == 0:
                return 1.0

            ear = (v1 + v2) / (2.0 * h)
            return ear

        except Exception:
            return 1.0

    @staticmethod
    def get_hand_distance(landmarks: List[Any]) -> float:
        """
        Расчет расстояния между большим и указательным пальцами
        для управления громкостью

        Args:
            landmarks: Landmarks руки

        Returns:
            float: Расстояние в пикселях (нормализованное * 1000)
        """
        thumb_tip = landmarks[HandLandmark.THUMB_TIP]
        index_tip = landmarks[HandLandmark.INDEX_FINGER_TIP]

        distance = math.sqrt(
            (thumb_tip.x - index_tip.x)**2 + 
            (thumb_tip.y - index_tip.y)**2
        )

        return distance * 1000  # Масштабируем для удобства


# ==================== ВИЗУАЛИЗАЦИЯ ====================

class Visualizer:
    """Утилиты для отрисовки landmarks и UI"""

    @staticmethod
    def draw_landmarks(
        image: np.ndarray, 
        landmarks: List[Any],
        connections: Optional[List[Tuple[int, int]]] = None,
        landmark_color: Tuple[int, int, int] = COLOR_GREEN,
        connection_color: Tuple[int, int, int] = COLOR_GREEN,
        thickness: int = 2,
        circle_radius: int = 4
    ):
        """Отрисовка landmarks и соединений"""
        h, w = image.shape[:2]

        # Сначала соединения
        if connections:
            for connection in connections:
                start_idx, end_idx = connection
                if start_idx < len(landmarks) and end_idx < len(landmarks):
                    start_pt = (
                        int(landmarks[start_idx].x * w), 
                        int(landmarks[start_idx].y * h)
                    )
                    end_pt = (
                        int(landmarks[end_idx].x * w), 
                        int(landmarks[end_idx].y * h)
                    )
                    cv2.line(
                        image, start_pt, end_pt, 
                        connection_color, thickness, cv2.LINE_AA
                    )

        # Затем точки
        for landmark in landmarks:
            x = int(landmark.x * w)
            y = int(landmark.y * h)
            cv2.circle(image, (x, y), circle_radius, landmark_color, -1, cv2.LINE_AA)

    @staticmethod
    def draw_face_mesh_debug(
        image: np.ndarray,
        face_landmarks: List[Any]
    ):
        """Отрисовка сетки лица в Debug режиме (полная сетка глаз)"""
        h, w = image.shape[:2]

        # Точки глаз
        left_eye_indices = FaceLandmarkIndices.LEFT_EAR_INDICES
        right_eye_indices = FaceLandmarkIndices.RIGHT_EAR_INDICES

        # Отрисовываем контуры глаз
        left_points = []
        right_points = []

        for idx in left_eye_indices:
            pt = face_landmarks[idx]
            x, y = int(pt.x * w), int(pt.y * h)
            left_points.append((x, y))
            cv2.circle(image, (x, y), 2, COLOR_CYAN, -1, cv2.LINE_AA)

        for idx in right_eye_indices:
            pt = face_landmarks[idx]
            x, y = int(pt.x * w), int(pt.y * h)
            right_points.append((x, y))
            cv2.circle(image, (x, y), 2, COLOR_CYAN, -1, cv2.LINE_AA)

        # Соединяем точки глаз
        if len(left_points) >= 6:
            cv2.polylines(image, [np.array(left_points)], True, COLOR_CYAN, 1, cv2.LINE_AA)
        if len(right_points) >= 6:
            cv2.polylines(image, [np.array(right_points)], True, COLOR_CYAN, 1, cv2.LINE_AA)

    @staticmethod
    def draw_face_mesh_production(
        image: np.ndarray,
        face_landmarks: List[Any]
    ):
        """Отрисовка сетки лица в Production режиме (только ключевые точки)"""
        h, w = image.shape[:2]

        # Только центры глаз
        left_center = face_landmarks[FaceLandmarkIndices.LEFT_EYE_INNER]
        right_center = face_landmarks[FaceLandmarkIndices.RIGHT_EYE_INNER]

        lx, ly = int(left_center.x * w), int(left_center.y * h)
        rx, ry = int(right_center.x * w), int(right_center.y * h)

        cv2.circle(image, (lx, ly), 3, COLOR_CYAN, -1, cv2.LINE_AA)
        cv2.circle(image, (rx, ry), 3, COLOR_CYAN, -1, cv2.LINE_AA)

    @staticmethod
    def draw_debug_info(
        image: np.ndarray,
        fps: float,
        volume: int,
        volume_active: bool,
        calibration: CalibrationData,
        gesture_state: GestureState,
        eye_ear: float
    ):
        """Отрисовка отладочной информации (только Debug Mode)"""
        h, w = image.shape[:2]

        # Фон для текста
        overlay = image.copy()
        cv2.rectangle(overlay, (10, 10), (400, 180), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, image, 0.5, 0, image)

        # FPS
        fps_color = COLOR_GREEN if fps > 25 else COLOR_YELLOW if fps > 15 else COLOR_RED
        cv2.putText(
            image, f"FPS: {fps:.1f}", (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, fps_color, 2, cv2.LINE_AA
        )

        # Громкость
        vol_color = COLOR_GREEN if volume_active else COLOR_RED
        cv2.putText(
            image, f"Volume: {volume}%", (20, 70),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, vol_color, 2, cv2.LINE_AA
        )

        # Полоса громкости
        bar_x, bar_y = 180, 55
        cv2.rectangle(image, (bar_x, bar_y), (bar_x + 100, bar_y + 15), (100, 100, 100), -1)
        vol_width = int(volume)
        cv2.rectangle(image, (bar_x, bar_y), (bar_x + vol_width, bar_y + 15), vol_color, -1)

        # Статус калибровки
        calib_text = "Calibrated" if calibration.is_calibrated else "NOT Calibrated"
        calib_color = COLOR_GREEN if calibration.is_calibrated else COLOR_RED
        cv2.putText(
            image, f"Calib: {calib_text}", (20, 100),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, calib_color, 2, cv2.LINE_AA
        )

        # Состояние глаз
        eye_status = "CLOSED" if gesture_state.eyes_closed else "OPEN"
        eye_color = COLOR_RED if gesture_state.eyes_closed else COLOR_GREEN
        cv2.putText(
            image, f"Eyes: {eye_status} (EAR: {eye_ear:.2f})", (20, 130),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, eye_color, 2, cv2.LINE_AA
        )

        # Таймер блокировки
        if gesture_state.eyes_closed and gesture_state.eyes_closed_start:
            elapsed = time.time() - gesture_state.eyes_closed_start
            remaining = max(0, SAFETY_LOCK_SECONDS - elapsed)
            if remaining > 0:
                cv2.putText(
                    image, f"Lock in: {remaining:.1f}s", (20, 160),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_RED, 2, cv2.LINE_AA
                )

        # Подсказки управления
        cv2.putText(
            image, "M: Mode | Q: Quit | C: Calibrate", (20, h - 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_WHITE, 1, cv2.LINE_AA
        )

    @staticmethod
    def put_text_unicode(
        image: np.ndarray,
        text: str,
        position: Tuple[int, int],
        font_size: int = 24,
        color: Tuple[int, int, int] = COLOR_WHITE,
        stroke_width: int = 1
    ):
        """
        Отрисовка текста с поддержкой Unicode (включая русский)
        Использует PIL вместо OpenCV для поддержки кириллицы
        """
        # Конвертируем BGR в RGB
        img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(img_rgb)
        draw = ImageDraw.Draw(pil_image)

        # Пытаемся загрузить системный шрифт с поддержкой кириллицы
        font = None
        font_paths = [
            "/usr/share/fonts/TTF/DejaVuSans.ttf",  # Arch Linux [^31^]
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Debian/Ubuntu
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc",  # macOS
            "C:/Windows/Fonts/arial.ttf",  # Windows
            "C:/Windows/Fonts/segoeui.ttf",  # Windows
            "C:/Windows/Fonts/calibri.ttf",  # Windows
        ]

        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    font = ImageFont.truetype(font_path, font_size)
                    break
                except Exception as e:
                    continue

        if font is None:
            # Если системные шрифты не найдены, используем дефолтный
            print(f"[WARN] Не найдены системные шрифты с поддержкой кириллицы.")
            print(f"[WARN] Установите: sudo pacman -S ttf-dejavu (Arch) или ttf-dejavu (Ubuntu/Debian)")
            font = ImageFont.load_default()

        if font is None:
            # Используем дефолтный шрифт
            font = ImageFont.load_default()

        # Отрисовка текста
        x, y = position
        # Преобразуем BGR в RGB для PIL
        pil_color = (color[2], color[1], color[0])

        # Обводка для лучшей читаемости
        if stroke_width > 0:
            for dx in range(-stroke_width, stroke_width + 1):
                for dy in range(-stroke_width, stroke_width + 1):
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0))

        draw.text((x, y), text, font=font, fill=pil_color)

        # Конвертируем обратно в BGR
        result = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        image[:] = result

    @staticmethod
    def overlay_icon(
        background: np.ndarray, 
        icon: np.ndarray, 
        x: int, 
        y: int
    ):
        """Наложение иконки на изображение с проверкой границ и поддержкой альфа-канала"""
        h, w = icon.shape[:2]
        bh, bw = background.shape[:2]

        # Ограничиваем позицию
        x = max(0, min(x, bw - w))
        y = max(0, min(y, bh - h))

        if y + h > bh or x + w > bw:
            return

        # Обработка иконки с альфа-каналом (RGBA)
        if icon.shape[2] == 4:
            # Выделяем альфа-канал и конвертируем в BGR
            alpha = icon[:, :, 3] / 255.0
            icon_bgr = icon[:, :, :3]

            # Альфа-смешивание
            roi = background[y:y+h, x:x+w]
            for c in range(3):
                roi[:, :, c] = (icon_bgr[:, :, c] * alpha + roi[:, :, c] * (1 - alpha)).astype(np.uint8)
        else:
            # Простое наложение для BGR
            background[y:y+h, x:x+w] = icon


# ==================== КАЛИБРОВКА ====================

class CalibrationWizard:
    """Мастер калибровки системы"""

    def __init__(self, calibration: CalibrationData):
        self.calibration = calibration
        self.stage = 0
        self.stages = [
            "Шаг 1/3: Разведите большой и указательный пальцы (MAX громкость), нажмите ПРОБЕЛ",
            "Шаг 2/3: Сведите большой и указательный пальцы (MIN громкость), нажмите ПРОБЕЛ",
            "Шаг 3/3: Закройте глаза для калибровки, нажмите ПРОБЕЛ",
            "Калибровка завершена! Нажмите ПРОБЕЛ для старта"
        ]
        self.temp_data = {}

    def draw(self, image: np.ndarray, visualizer: Visualizer) -> np.ndarray:
        """Отрисовка экрана калибровки с поддержкой Unicode"""
        h, w = image.shape[:2]

        # Затемнение фона
        overlay = image.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.8, image, 0.2, 0, image)

        # Заголовок (Unicode)
        visualizer.put_text_unicode(
            image, "РЕЖИМ КАЛИБРОВКИ",
            (w//2 - 200, h//2 - 100),
            font_size=32,
            color=COLOR_YELLOW,
            stroke_width=2
        )

        # Инструкция текущего шага
        text = self.stages[self.stage]
        # Разбиваем длинный текст на строки
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            if len(current_line + word) < 50:
                current_line += word + " "
            else:
                lines.append(current_line)
                current_line = word + " "
        lines.append(current_line)

        y_offset = h // 2
        for line in lines:
            visualizer.put_text_unicode(
                image, line.strip(),
                (50, y_offset),
                font_size=20,
                color=COLOR_WHITE,
                stroke_width=1
            )
            y_offset += 35

        # Прогресс
        progress_text = f"Шаг {self.stage + 1} из {len(self.stages)}"
        visualizer.put_text_unicode(
            image, progress_text,
            (50, y_offset + 20),
            font_size=18,
            color=(200, 200, 200)
        )

        return image

    def process(
        self, 
        hand_landmarks: Optional[List[Any]], 
        face_landmarks: Optional[List[Any]]
    ) -> bool:
        """
        Обработка текущего шага калибровки

        Returns:
            bool: True если калибровка завершена
        """
        if self.stage == 0 and hand_landmarks:
            # Максимальное расстояние для громкости
            dist = GestureDetector.get_hand_distance(hand_landmarks)
            self.temp_data['vol_max'] = dist

        elif self.stage == 1 and hand_landmarks:
            # Минимальное расстояние для громкости
            dist = GestureDetector.get_hand_distance(hand_landmarks)
            self.temp_data['vol_min'] = dist

        elif self.stage == 2 and face_landmarks:
            # Калибровка закрытых глаз
            left_ear = GestureDetector.calculate_ear(
                face_landmarks, FaceLandmarkIndices.LEFT_EAR_INDICES
            )
            right_ear = GestureDetector.calculate_ear(
                face_landmarks, FaceLandmarkIndices.RIGHT_EAR_INDICES
            )
            avg_ear = (left_ear + right_ear) / 2
            self.temp_data['eye_closed'] = avg_ear

        elif self.stage == 3:
            # Применяем калибровку
            self._apply()
            return True

        self.stage += 1
        return False

    def _apply(self):
        """Применение откалиброванных значений"""
        if 'vol_max' in self.temp_data:
            self.calibration.vol_max_dist = self.temp_data['vol_max']
        if 'vol_min' in self.temp_data:
            self.calibration.vol_min_dist = self.temp_data['vol_min']
        if 'eye_closed' in self.temp_data:
            # Устанавливаем порог чуть выше измеренного значения
            self.calibration.eye_closed_threshold = self.temp_data['eye_closed'] * 1.2
            self.calibration.eye_open_threshold = self.temp_data['eye_closed'] * 2.0

        self.calibration.is_calibrated = True
        print(f"[INFO] Калибровка завершена: max_dist={self.calibration.vol_max_dist:.1f}, "
              f"min_dist={self.calibration.vol_min_dist:.1f}, "
              f"eye_threshold={self.calibration.eye_closed_threshold:.3f}")


# ==================== ГЛАВНЫЙ КОНТРОЛЛЕР ====================

class GestureController:
    """
    Главный контроллер системы бесконтактного управления

    Интегрирует трекинг рук и лица, детекцию жестов и системные действия
    """

    def __init__(self):
        # Режим работы
        self.mode = Mode.DEBUG

        # Данные и состояние
        self.calibration = CalibrationData()
        self.gesture_state = GestureState()
        self.system = SystemActionHandler()
        self.detector = GestureDetector()
        self.visualizer = Visualizer()

        # Калибровка
        self.calib_wizard: Optional[CalibrationWizard] = None
        self.in_calibration = False

        # MediaPipe детекторы
        self.hand_detector: Optional[vision.HandLandmarker] = None
        self.face_detector: Optional[vision.FaceLandmarker] = None

        # Очереди для многопоточности
        self.frame_queue: queue.Queue = queue.Queue(maxsize=2)
        self.hand_results_queue: queue.Queue = queue.Queue(maxsize=2)
        self.face_results_queue: queue.Queue = queue.Queue(maxsize=2)

        # Потоки
        self.capture_thread: Optional[threading.Thread] = None
        self.is_running = False

        # Состояние приложения
        self.current_volume = 50
        self.volume_control_active = True
        self.prev_victory = False

        # FPS
        self.fps_history = deque(maxlen=FPS_HISTORY_SIZE)
        self.last_frame_time = time.time()

        # Загрузка иконки
        self.icon_image = self._load_icon()

        # URL для хлопка
        self.CLAP_URL = "https://github.com"

        # Файл калибровки
        self.calibration_file = "calibration_data.json"

        # Загружаем сохраненную калибровку
        self._load_calibration()

    def _load_calibration(self):
        """Загрузка данных калибровки из файла"""
        try:
            if os.path.exists(self.calibration_file):
                with open(self.calibration_file, 'r') as f:
                    data = json.load(f)
                    self.calibration = CalibrationData.from_dict(data)
                    print("[INFO] Загружена сохраненная калибровка")
        except Exception as e:
            print(f"[WARN] Не удалось загрузить калибровку: {e}")

    def _save_calibration(self):
        """Сохранение данных калибровки в файл"""
        try:
            with open(self.calibration_file, 'w') as f:
                json.dump(self.calibration.to_dict(), f)
        except Exception as e:
            print(f"[WARN] Не удалось сохранить калибровку: {e}")

    def _load_icon(self) -> np.ndarray:
        """Загрузка иконки для жеста пистолет с поддержкой прозрачности"""
        try:
            if os.path.exists('icon.png'):
                img = cv2.imread('icon.png', cv2.IMREAD_UNCHANGED)
                if img is not None:
                    # Масштабируем до фиксированного размера
                    img = cv2.resize(img, (120, 120))
                    # Если изображение BGR (3 канала), конвертируем в RGBA
                    if img.shape[2] == 3:
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
                        img[:, :, 3] = 255  # Полная непрозрачность
                    return img
        except Exception as e:
            print(f"[WARN] Не удалось загрузить icon.png: {e}")

        # Создаем дефолтную иконку с прозрачностью (RGBA) с прозрачностью (красный круг с текстом) - BGR формат
        icon = np.ones((100, 100, 3), dtype=np.uint8) * 255
        cv2.circle(icon, (50, 50), 40, COLOR_RED, -1)
        cv2.putText(
            icon, "GUN", (15, 55),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLOR_WHITE, 2, cv2.LINE_AA
        )
        return icon

    def _create_default_icon_rgba(self) -> np.ndarray:
        """Создание дефолтной иконки с прозрачностью (RGBA)"""
        icon = np.zeros((100, 100, 4), dtype=np.uint8)
        # Красный круг
        cv2.circle(icon, (50, 50), 40, (0, 0, 255, 255), -1)
        # Белый текст
        cv2.putText(
            icon, "GUN", (15, 55),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255, 255), 2, cv2.LINE_AA
        )
        return icon

    def _download_model(self, model_name: str, url: str) -> str:
        """Загрузка модели MediaPipe если не существует"""
        if not os.path.exists(model_name):
            print(f"[INFO] Загрузка {model_name}...")
            import urllib.request
            try:
                urllib.request.urlretrieve(url, model_name)
                print(f"[INFO] {model_name} загружена")
            except Exception as e:
                print(f"[ERROR] Не удалось загрузить {model_name}: {e}")
                sys.exit(1)
        return model_name

    def initialize(self):
        """Инициализация детекторов MediaPipe"""
        print("[INFO] Инициализация системы...")

        # Загружаем модели
        base_url = "https://storage.googleapis.com/mediapipe-models"

        hand_model = self._download_model(
            "hand_landmarker.task",
            f"{base_url}/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
        )

        face_model = self._download_model(
            "face_landmarker.task",
            f"{base_url}/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
        )

        # Настройка HandLandmarker (VIDEO mode для минимальной задержки)
        # VIDEO mode используется с detect_for_video() для синхронной обработки
        hand_options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=hand_model),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.hand_detector = vision.HandLandmarker.create_from_options(hand_options)

        # Настройка FaceLandmarker (VIDEO mode)
        face_options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=face_model),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False
        )
        self.face_detector = vision.FaceLandmarker.create_from_options(face_options)

        # Получаем текущую громкость
        self.current_volume = self.system.get_volume()

        print("[INFO] Инициализация завершена")

    def _capture_frames(self):
        """Поток захвата кадров с камеры"""
        cap = cv2.VideoCapture(0)

        # Оптимизация: уменьшаем буфер для минимизации задержки
        # CAP_PROP_BUFFERSIZE = 1 уменьшает задержку камеры
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # Устанавливаем максимальное разрешение
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

        # Проверяем фактическое разрешение
        actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[INFO] Разрешение камеры: {actual_width}x{actual_height}")

        while self.is_running:
            ret, frame = cap.read()
            if not ret:
                continue

            # Зеркалирование для естественного взаимодействия
            frame = cv2.flip(frame, 1)

            # Помещаем кадр в очередь (с вытеснением старых)
            try:
                self.frame_queue.put_nowait(frame)
            except queue.Full:
                try:
                    self.frame_queue.get_nowait()
                    self.frame_queue.put_nowait(frame)
                except:
                    pass

        cap.release()
        print("[INFO] Поток захвата остановлен")

    def _process_gestures(
        self, 
        hand_result, 
        face_result, 
        image: np.ndarray
    ) -> np.ndarray:
        """
        Обработка жестов и отрисовка

        Args:
            hand_result: Результат детекции рук
            face_result: Результат детекции лица
            image: Текущий кадр

        Returns:
            np.ndarray: Обработанный кадр
        """
        h, w = image.shape[:2]
        current_time = time.time()

        # Расчет FPS
        dt = current_time - self.last_frame_time
        self.last_frame_time = current_time
        if dt > 0:
            self.fps_history.append(1.0 / dt)
        avg_fps = sum(self.fps_history) / len(self.fps_history) if self.fps_history else 0

        # Переменные для хранения рук
        left_hand = None   # Физическая левая рука (зеленая)
        right_hand = None  # Физическая правая рука (красная)

        # ========== ОБРАБОТКА РУК ==========
        if hand_result and hand_result.hand_landmarks:
            for i, landmarks in enumerate(hand_result.hand_landmarks):
                # После зеркалирования handedness инвертирован
                # MediaPipe "Left" = физическая правая рука пользователя
                # MediaPipe "Right" = физическая левая рука пользователя
                handedness = hand_result.handedness[i][0].category_name

                if handedness == "Left":
                    # Физическая ПРАВАЯ рука (красная) - жест пистолет
                    right_hand = landmarks

                    # Проверяем жест пистолет
                    is_gun = self.detector.is_gun_gesture(landmarks)
                    self.gesture_state.gun_active = is_gun

                    # Отрисовка
                    if self.mode == Mode.DEBUG:
                        self.visualizer.draw_landmarks(
                            image, landmarks, HAND_CONNECTIONS,
                            COLOR_RED, COLOR_RED, 2, 4
                        )
                        cv2.putText(
                            image, "RIGHT: Gun", (w - 200, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_RED, 2, cv2.LINE_AA
                        )
                    else:
                        # Production mode - только ключевые точки
                        for idx in [HandLandmark.WRIST, HandLandmark.THUMB_TIP, 
                                   HandLandmark.INDEX_FINGER_TIP]:
                            pt = landmarks[idx]
                            x, y = int(pt.x * w), int(pt.y * h)
                            cv2.circle(image, (x, y), 4, COLOR_RED, -1, cv2.LINE_AA)

                    # Накладываем иконку при жесте пистолет
                    if is_gun:
                        wrist = landmarks[HandLandmark.WRIST]
                        icon_x = int(wrist.x * w) - 60
                        icon_y = int(wrist.y * h) - 60
                        self.visualizer.overlay_icon(image, self.icon_image, icon_x, icon_y)

                else:  # handedness == "Right"
                    # Физическая ЛЕВАЯ рука (зеленая) - управление громкостью
                    left_hand = landmarks

                    # Проверяем жест Victory для переключения режима громкости
                    is_victory = self.detector.is_victory_gesture(landmarks)

                    # Детекция нажатия (переход из False в True)
                    if is_victory and not self.prev_victory:
                        self.volume_control_active = not self.volume_control_active
                        if self.mode == Mode.DEBUG:
                            status = "ВКЛ" if self.volume_control_active else "ВЫКЛ"
                            print(f"[INFO] Управление громкостью: {status}")
                    self.prev_victory = is_victory

                    # Управление громкостью
                    if self.volume_control_active and self.calibration.is_calibrated:
                        dist = self.detector.get_hand_distance(landmarks)

                        # Маппинг расстояния на громкость
                        vol_range = self.calibration.vol_max_dist - self.calibration.vol_min_dist
                        if vol_range > 0:
                            vol_pct = int(
                                ((dist - self.calibration.vol_min_dist) / vol_range) * 100
                            )
                            vol_pct = max(0, min(100, vol_pct))
                            self.current_volume = self.system.set_volume(vol_pct)

                    # Отрисовка
                    if self.mode == Mode.DEBUG:
                        self.visualizer.draw_landmarks(
                            image, landmarks, HAND_CONNECTIONS,
                            COLOR_GREEN, COLOR_GREEN, 2, 4
                        )

                        # Линия между пальцами для громкости
                        thumb = landmarks[HandLandmark.THUMB_TIP]
                        index = landmarks[HandLandmark.INDEX_FINGER_TIP]
                        t_x, t_y = int(thumb.x * w), int(thumb.y * h)
                        i_x, i_y = int(index.x * w), int(index.y * h)
                        cv2.line(image, (t_x, t_y), (i_x, i_y), COLOR_YELLOW, 2, cv2.LINE_AA)

                        cv2.putText(
                            image, "LEFT: Volume", (30, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_GREEN, 2, cv2.LINE_AA
                        )

                        # Статус Victory
                        vic_color = COLOR_GREEN if is_victory else (100, 100, 100)
                        cv2.putText(
                            image, f"Victory: {is_victory}", (30, 70),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, vic_color, 1, cv2.LINE_AA
                        )
                    else:
                        # Production mode
                        for idx in [HandLandmark.WRIST, HandLandmark.THUMB_TIP, 
                                   HandLandmark.INDEX_FINGER_TIP]:
                            pt = landmarks[idx]
                            x, y = int(pt.x * w), int(pt.y * h)
                            cv2.circle(image, (x, y), 4, COLOR_GREEN, -1, cv2.LINE_AA)

        # ========== ОБРАБОТКА ХЛОПКА ==========
        if left_hand and right_hand:
            is_clap, distance = self.detector.is_clap_gesture(left_hand, right_hand)

            # Проверяем кулдаун
            can_clap = (current_time - self.gesture_state.last_clap_time) > CLAP_COOLDOWN_SECONDS

            if is_clap and can_clap:
                self.system.open_url(self.CLAP_URL)
                self.gesture_state.last_clap_time = current_time
                if self.mode == Mode.DEBUG:
                    print(f"[INFO] Хлопок обнаружен! Открываю URL...")

            if self.mode == Mode.DEBUG:
                # Отображаем расстояние между руками
                mid_x = (left_hand[HandLandmark.WRIST].x + right_hand[HandLandmark.WRIST].x) / 2
                mid_y = (left_hand[HandLandmark.WRIST].y + right_hand[HandLandmark.WRIST].y) / 2
                text = "CLAP!" if is_clap else f"dist: {distance:.2f}"
                color = COLOR_RED if is_clap else COLOR_YELLOW
                cv2.putText(
                    image, text, (int(mid_x * w) - 40, int(mid_y * h) - 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA
                )

        # ========== ОБРАБОТКА ЛИЦА/ГЛАЗ ==========
        eye_ear = 0.0
        if face_result and face_result.face_landmarks:
            face_landmarks = face_result.face_landmarks[0]

            # Расчет EAR для обоих глаз
            left_ear = self.detector.calculate_ear(
                face_landmarks, FaceLandmarkIndices.LEFT_EAR_INDICES
            )
            right_ear = self.detector.calculate_ear(
                face_landmarks, FaceLandmarkIndices.RIGHT_EAR_INDICES
            )
            eye_ear = (left_ear + right_ear) / 2

            # Определяем состояние глаз
            eyes_closed_now = eye_ear < self.calibration.eye_closed_threshold
            self.gesture_state.eyes_closed = eyes_closed_now

            # Safety Lock: блокировка при закрытых глазах более 5 секунд
            if eyes_closed_now:
                if self.gesture_state.eyes_closed_start is None:
                    self.gesture_state.eyes_closed_start = current_time
                else:
                    elapsed = current_time - self.gesture_state.eyes_closed_start
                    if elapsed >= SAFETY_LOCK_SECONDS:
                        if self.mode == Mode.DEBUG:
                            print("[INFO] Safety Lock: Блокировка экрана")
                        self.system.lock_screen()
                        self.gesture_state.eyes_closed_start = None
            else:
                self.gesture_state.eyes_closed_start = None

            # Отрисовка лица
            if self.mode == Mode.DEBUG:
                self.visualizer.draw_face_mesh_debug(image, face_landmarks)
            else:
                self.visualizer.draw_face_mesh_production(image, face_landmarks)

        # ========== ОТРИСОВКА DEBUG ИНФОРМАЦИИ ==========
        if self.mode == Mode.DEBUG:
            self.visualizer.draw_debug_info(
                image, avg_fps, self.current_volume,
                self.volume_control_active, self.calibration,
                self.gesture_state, eye_ear
            )

        return image

    def run(self):
        """Главный цикл приложения"""
        self.initialize()

        # Запускаем поток захвата
        self.is_running = True
        self.capture_thread = threading.Thread(target=self._capture_frames)
        self.capture_thread.daemon = True
        self.capture_thread.start()

        # Выводим инструкции
        print("\n" + "="*60)
        print("СИСТЕМА БЕСКОНТАКТНОГО УПРАВЛЕНИЯ")
        print("="*60)
        print("Управление:")
        print("  Левая рука (зеленая)  = Громкость (большой + указательный)")
        print("  Правая рука (красная)  = Жест 'пистолет' для иконки")
        print("  Victory (V)           = Вкл/Выкл управление громкостью")
        print("  Хлопок                = Открыть GitHub")
        print("  Глаза закрыты 5с      = Блокировка экрана (Safety Lock)")
        print("\nГорячие клавиши:")
        print("  M = Переключить Debug/Production режим")
        print("  C = Запустить калибровку")
        print("  Q = Выход")
        print("="*60 + "\n")

        # Создаем окно
        window_name = "Gesture Control System"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        # Переменные для результатов
        hand_result = None
        face_result = None
        frame_count = 0

        # Проверяем необходимость калибровки
        if not self.calibration.is_calibrated:
            self.in_calibration = True
            self.calib_wizard = CalibrationWizard(self.calibration)
            print("[INFO] Требуется калибровка. Следуйте инструкциям на экране.")

        while self.is_running:
            # Получаем кадр из очереди
            try:
                frame = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Конвертируем в MediaPipe Image
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            # Детекция (в текущем потоке для синхронности)
            timestamp_ms = int(time.time() * 1000)

            try:
                hand_result = self.hand_detector.detect_for_video(mp_image, timestamp_ms)
                face_result = self.face_detector.detect_for_video(mp_image, timestamp_ms)
            except Exception as e:
                if self.mode == Mode.DEBUG:
                    print(f"[ERROR] Ошибка детекции: {e}")

            # Режим калибровки
            if self.in_calibration:
                display = self.calib_wizard.draw(frame, self.visualizer)
                cv2.imshow(window_name, display)

                key = cv2.waitKey(1) & 0xFF
                if key == 32:  # Пробел
                    # Получаем landmarks для калибровки
                    hand_lms = None
                    face_lms = None

                    if hand_result and hand_result.hand_landmarks:
                        hand_lms = hand_result.hand_landmarks[0]
                    if face_result and face_result.face_landmarks:
                        face_lms = face_result.face_landmarks[0]

                    completed = self.calib_wizard.process(hand_lms, face_lms)
                    if completed:
                        self.in_calibration = False
                        self._save_calibration()
                        print("[INFO] Калибровка завершена! Начинаем работу...")

                elif key == ord('q'):
                    break

            else:
                # Основной режим работы
                display = self._process_gestures(hand_result, face_result, frame)
                cv2.imshow(window_name, display)

                # Обработка клавиш
                key = cv2.waitKey(1) & 0xFF

                if key == ord('q'):
                    break

                elif key == ord('m'):
                    # Переключение режима
                    if self.mode == Mode.DEBUG:
                        self.mode = Mode.PRODUCTION
                        print("[INFO] Переключено в Production Mode")
                    else:
                        self.mode = Mode.DEBUG
                        print("[INFO] Переключено в Debug Mode")

                elif key == ord('c'):
                    # Перекалибровка
                    self.in_calibration = True
                    self.calib_wizard = CalibrationWizard(self.calibration)
                    print("[INFO] Запущена перекалибровка")

        self.shutdown()

    def shutdown(self):
        """Корректное завершение работы"""
        print("[INFO] Завершение работы...")
        self.is_running = False

        if self.capture_thread:
            self.capture_thread.join(timeout=2.0)

        cv2.destroyAllWindows()

        # Сохраняем калибровку
        self._save_calibration()

        # Освобождаем ресурсы MediaPipe
        if self.hand_detector:
            self.hand_detector.close()
        if self.face_detector:
            self.face_detector.close()

        print("[INFO] Работа завершена")


# ==================== ТОЧКА ВХОДА ====================

if __name__ == "__main__":
    controller = GestureController()

    try:
        controller.run()
    except KeyboardInterrupt:
        print("\n[INFO] Прервано пользователем")
        controller.shutdown()
    except Exception as e:
        print(f"\n[ERROR] Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        controller.shutdown()