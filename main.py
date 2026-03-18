import mediapipe as mp
from mediapipe.tasks.python import vision
import cv2
import numpy as np
import os
import webbrowser
import platform
import subprocess

BaseOptions = mp.tasks.BaseOptions

# Platform detection for cross-platform compatibility
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# Initialize Windows volume control if on Windows
if IS_WINDOWS:
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume_controller = interface.QueryInterface(IAudioEndpointVolume)
    except ImportError:
        print("Warning: pycaw not installed. Windows volume control will be disabled.")
        print("Install with: pip install pycaw comtypes")
        volume_controller = None
    except Exception as e:
        print(f"Warning: Failed to initialize Windows volume control: {e}")
        volume_controller = None
else:
    volume_controller = None

# Drawing utilities (custom implementation since mp.solutions is removed)
class DrawingUtils:
    """Custom drawing utilities to replace mp.solutions.drawing_utils"""
    
    @staticmethod
    def draw_landmarks(image, landmarks, connections=None, landmark_drawing_spec=None, connection_drawing_spec=None):
        """Draw hand landmarks on image."""
        h, w = image.shape[:2]
        
        # Default colors
        landmark_color = (0, 255, 0) if landmark_drawing_spec is None else landmark_drawing_spec.color
        connection_color = (0, 255, 0) if connection_drawing_spec is None else connection_drawing_spec.color
        landmark_thickness = 2 if landmark_drawing_spec is None else landmark_drawing_spec.thickness
        connection_thickness = 2 if connection_drawing_spec is None else connection_drawing_spec.thickness
        circle_radius = 4 if landmark_drawing_spec is None else getattr(landmark_drawing_spec, 'circle_radius', 4)
        
        # Draw connections
        if connections:
            for connection in connections:
                start_idx = connection[0]
                end_idx = connection[1]
                if start_idx < len(landmarks) and end_idx < len(landmarks):
                    start_point = (int(landmarks[start_idx].x * w), int(landmarks[start_idx].y * h))
                    end_point = (int(landmarks[end_idx].x * w), int(landmarks[end_idx].y * h))
                    cv2.line(image, start_point, end_point, connection_color, connection_thickness)
        
        # Draw landmarks
        for landmark in landmarks:
            x = int(landmark.x * w)
            y = int(landmark.y * h)
            cv2.circle(image, (x, y), circle_radius, landmark_color, -1)


class DrawingSpec:
    """Drawing specification for landmarks and connections."""
    def __init__(self, color=(0, 255, 0), thickness=2, circle_radius=4):
        self.color = color
        self.thickness = thickness
        self.circle_radius = circle_radius


# Hand landmark indices (matching original MediaPipe Hands)
class HandLandmark:
    """Hand landmark indices."""
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


# Hand connections (skeleton)
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),  # Thumb
    (0, 5), (5, 6), (6, 7), (7, 8),  # Index finger
    (0, 9), (9, 10), (10, 11), (11, 12),  # Middle finger
    (0, 13), (13, 14), (14, 15), (15, 16),  # Ring finger
    (0, 17), (17, 18), (18, 19), (19, 20),  # Pinky
    (5, 9), (9, 13), (13, 17)  # Palm
]

# Initialize MediaPipe Hand Landmarker with Tasks API
def create_hand_landmarker():
    """Create hand landmarker using MediaPipe Tasks API."""
    # Download model if not exists
    model_path = "hand_landmarker.task"
    if not os.path.exists(model_path):
        print(f"Downloading hand landmarker model...")
        import urllib.request
        url = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
        try:
            urllib.request.urlretrieve(url, model_path)
            print(f"Model saved to {model_path}")
        except Exception as e:
            print(f"Failed to download model: {e}")
            print("Please download manually from: https://developers.google.com/mediapipe/solutions/vision/hand_landmarker")
            return None
    
    base_options = BaseOptions(model_asset_path=model_path)
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        num_hands=2,
        min_hand_detection_confidence=0.75,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5
    )
    return vision.HandLandmarker.create_from_options(options)


# Initialize hand landmarker
try:
    hand_landmarker = create_hand_landmarker()
    if hand_landmarker is None:
        print("Failed to initialize hand landmarker. Exiting.")
        exit(1)
except Exception as e:
    print(f"Error initializing hand landmarker: {e}")
    exit(1)

# Initialize camera capture
cap = cv2.VideoCapture(0)
# Set camera resolution to 720p
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# Volume control variables (right hand)
vol_max_distance = 0
vol_min_distance = 0
vol_is_calibrated = False
vol_calibration_frames = 0

# Current volume value
current_volume = 50

# Gesture control variables
volume_control_active = True  # Volume control activation flag
clap_gesture_detected = False  # Clap gesture detection flag
clap_cooldown = 0  # Cooldown between clap gesture triggers

# URL to open on clap gesture
CLAP_GESTURE_URL = "https://github.com/d0x0day/Hand-Tracking-by-d0x0day"


def load_and_resize_image():
    """
    Load and resize the icon image for left hand display.
    Creates a default image if file is not found.
    """
    try:
        # Try to load the image file
        image = cv2.imread('icon.png')
        if image is None:
            # Create default image if file not found
            image = create_default_image()
        else:
            # Resize image to 200x200 pixels
            image = cv2.resize(image, (200, 200))
        return image
    except Exception as e:
        print(f"Error loading image: {e}")
        return create_default_image()


def create_default_image():
    """Create a default image when icon file is not available."""
    image = np.ones((100, 100, 3), dtype=np.uint8) * 255
    # Draw a red circle
    cv2.circle(image, (50, 50), 40, (0, 0, 255), -1)
    # Add text
    cv2.putText(
        image, "GUN", (20, 55), 
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
    )
    return image


def set_volume(volume_percent):
    """
    Set system volume cross-platform.
    
    Args:
        volume_percent: Volume level (0-100%)
    
    Returns:
        Clamped volume percentage
    """
    # Clamp volume between 0-100%
    volume_percent = max(0, min(100, volume_percent))
    
    try:
        if IS_WINDOWS and volume_controller is not None:
            # Windows: use pycaw
            # Volume range is typically -65.25 to 0.0 dB, or scalar 0.0 to 1.0
            scalar = volume_percent / 100.0
            volume_controller.SetMasterVolumeLevelScalar(scalar, None)
        elif IS_LINUX:
            # Linux: use pactl (PulseAudio)
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{volume_percent}%"],
                check=True,
                capture_output=True
            )
        else:
            print(f"Volume control not supported on this platform: {platform.system()}")
    except Exception as e:
        print(f"Error setting volume: {e}")
    
    return volume_percent


def get_current_volume():
    """Get current system volume level cross-platform."""
    try:
        if IS_WINDOWS and volume_controller is not None:
            # Windows: use pycaw
            current = volume_controller.GetMasterVolumeLevelScalar()
            return int(current * 100)
        elif IS_LINUX:
            # Linux: use pactl
            result = subprocess.run(
                ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                capture_output=True,
                text=True
            )
            # Parse command output to extract current volume
            output = result.stdout
            # Look for percentage in output like "Volume: front-left: 65536 / 100% / -0.00 dB"
            import re
            match = re.search(r'(\d+)%', output)
            if match:
                return int(match.group(1))
            return 50  # Default value
        else:
            return 50  # Default for unsupported platforms
    except Exception as e:
        print(f"Error getting volume: {e}")
        return 50  # Default value


def overlay_image(background, overlay, x, y):
    """
    Overlay an image onto the background at specified position.
    
    Args:
        background: Background image
        overlay: Image to overlay
        x: X coordinate position
        y: Y coordinate position
    
    Returns:
        Modified background image with overlay
    """
    h, w = overlay.shape[:2]
    
    # Check boundaries
    if x < 0:
        x = 0
    if y < 0:
        y = 0
    if x + w > background.shape[1]:
        x = background.shape[1] - w
    if y + h > background.shape[0]:
        y = background.shape[0] - h
    
    # Ensure the insertion area exists
    if y + h <= background.shape[0] and x + w <= background.shape[1]:
        # Region of interest for overlay
        roi = background[y:y+h, x:x+w]
        
        # Ensure dimensions match
        if roi.shape == overlay.shape:
            # Without alpha channel - simply replace the area
            background[y:y+h, x:x+w] = overlay
        else:
            print(f"Dimension mismatch: ROI {roi.shape}, Overlay {overlay.shape}")
    
    return background


def is_gun_gesture(hand_landmarks):
    """
    Detect gun gesture (raised thumb and index finger, others bent).
    
    Args:
        hand_landmarks: MediaPipe hand landmarks
    
    Returns:
        Boolean indicating if gun gesture is detected
    """
    # Get finger tip landmarks
    thumb_tip = hand_landmarks[HandLandmark.THUMB_TIP]
    index_tip = hand_landmarks[HandLandmark.INDEX_FINGER_TIP]
    middle_tip = hand_landmarks[HandLandmark.MIDDLE_FINGER_TIP]
    ring_tip = hand_landmarks[HandLandmark.RING_FINGER_TIP]
    pinky_tip = hand_landmarks[HandLandmark.PINKY_TIP]
    
    # Get finger base landmarks
    thumb_mcp = hand_landmarks[HandLandmark.THUMB_MCP]
    index_mcp = hand_landmarks[HandLandmark.INDEX_FINGER_MCP]
    middle_mcp = hand_landmarks[HandLandmark.MIDDLE_FINGER_MCP]
    ring_mcp = hand_landmarks[HandLandmark.RING_FINGER_MCP]
    pinky_mcp = hand_landmarks[HandLandmark.PINKY_MCP]
    
    # Check if thumb and index fingers are raised
    thumb_raised = thumb_tip.y < thumb_mcp.y
    index_raised = index_tip.y < index_mcp.y
    
    # Check if middle, ring, and pinky fingers are bent
    middle_bent = middle_tip.y > middle_mcp.y
    ring_bent = ring_tip.y > ring_mcp.y
    pinky_bent = pinky_tip.y > pinky_mcp.y
    
    return thumb_raised and index_raised and middle_bent and ring_bent and pinky_bent


def is_victory_gesture(hand_landmarks):
    """
    Detect victory gesture (raised index and middle fingers forming V-shape).
    
    Args:
        hand_landmarks: MediaPipe hand landmarks
    
    Returns:
        Boolean indicating if victory gesture is detected
    """
    # Get finger tip landmarks
    thumb_tip = hand_landmarks[HandLandmark.THUMB_TIP]
    index_tip = hand_landmarks[HandLandmark.INDEX_FINGER_TIP]
    middle_tip = hand_landmarks[HandLandmark.MIDDLE_FINGER_TIP]
    ring_tip = hand_landmarks[HandLandmark.RING_FINGER_TIP]
    pinky_tip = hand_landmarks[HandLandmark.PINKY_TIP]
    
    # Get finger base landmarks
    index_mcp = hand_landmarks[HandLandmark.INDEX_FINGER_MCP]
    middle_mcp = hand_landmarks[HandLandmark.MIDDLE_FINGER_MCP]
    ring_mcp = hand_landmarks[HandLandmark.RING_FINGER_MCP]
    pinky_mcp = hand_landmarks[HandLandmark.PINKY_MCP]
    
    # Check if index and middle fingers are raised
    index_raised = index_tip.y < index_mcp.y
    middle_raised = middle_tip.y < middle_mcp.y
    
    # Check if ring and pinky fingers are bent
    ring_bent = ring_tip.y > ring_mcp.y
    pinky_bent = pinky_tip.y > pinky_mcp.y
    
    # Check if index and middle fingers are separated (V-shape)
    index_middle_distance = np.sqrt(
        (index_tip.x - middle_tip.x)**2 + 
        (index_tip.y - middle_tip.y)**2
    )
    fingers_separated = index_middle_distance > 0.05
    
    return index_raised and middle_raised and ring_bent and pinky_bent and fingers_separated


def is_clap_gesture(left_hand_landmarks, right_hand_landmarks):
    """
    Detect clap gesture (both palms coming together).
    
    Args:
        left_hand_landmarks: Left hand landmarks
        right_hand_landmarks: Right hand landmarks
    
    Returns:
        Tuple of (is_clap, distance) where is_clap is boolean and distance is float
    """
    # Get wrist positions of both hands
    left_wrist = left_hand_landmarks[HandLandmark.WRIST]
    right_wrist = right_hand_landmarks[HandLandmark.WRIST]
    
    # Calculate distance between wrist centers
    distance = np.sqrt(
        (left_wrist.x - right_wrist.x)**2 + 
        (left_wrist.y - right_wrist.y)**2
    )
    
    # Threshold value for clap detection
    clap_threshold = 0.1  # Can be adjusted
    
    # Clap is detected when palms are close together
    is_clap = distance < clap_threshold
    
    return is_clap, distance


# Load image for left hand
left_hand_image = load_and_resize_image()
print(f"Icon size: {left_hand_image.shape}")

# Initialize current volume
current_volume = get_current_volume()

print("Gesture Controls:")
print("Right hand (GREEN) - Volume control (toggle with V gesture)")
print("Left hand (RED) - Display icon only with 'gun' gesture")
print("Both hands - CLAP gesture opens URL")
print("Press 'q' to exit")

# Variables for tracking previous gesture states
prev_victory_detected = False

# Initialize drawing utilities
mp_drawing = DrawingUtils()

# Main loop
while cap.isOpened():
    ret, image = cap.read()
    if not ret:
        break

    # Flip frame horizontally for intuitive control
    image = cv2.flip(image, 1)

    # Convert frame to RGB for MediaPipe
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    
    # Create MediaPipe Image object
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
    
    # Process hand detection
    detection_result = hand_landmarker.detect(mp_image)

    # Hand tracking variables
    left_hand_detected = False
    left_hand_position = None
    left_hand_landmarks = None
    right_hand_landmarks = None
    gun_gesture = False  # Gun gesture flag for left hand
    victory_gesture = False  # Victory gesture flag for right hand
    
    # Draw hand landmarks and process gestures
    if detection_result.hand_landmarks:
        # Process each detected hand
        for i, landmarks in enumerate(detection_result.hand_landmarks):
            # Determine hand type (left or right)
            handedness = detection_result.handedness[i][0].category_name
            
            # Note: Due to mirroring, hand labels are inverted
            if handedness == "Right":
                hand_color = (0, 255, 0)  # Green for right hand (volume)
                control_type = "VOLUME"
                right_hand_landmarks = landmarks
                
                # Check victory gesture for right hand
                victory_gesture = is_victory_gesture(landmarks)
                
                # Toggle volume control with victory gesture
                if victory_gesture and not prev_victory_detected:
                    volume_control_active = not volume_control_active
                    status = "ON" if volume_control_active else "OFF"
                    print(f"Volume control: {status}")
                
                # Update previous state
                prev_victory_detected = victory_gesture
                
                # Process RIGHT hand (volume control) - only if active
                if volume_control_active:
                    # Get thumb and index finger positions
                    thumb_tip = landmarks[HandLandmark.THUMB_TIP]
                    index_tip = landmarks[HandLandmark.INDEX_FINGER_TIP]
                    
                    # Convert coordinates to pixels
                    thumb_x = int(thumb_tip.x * image.shape[1])
                    thumb_y = int(thumb_tip.y * image.shape[0])
                    index_x = int(index_tip.x * image.shape[1])
                    index_y = int(index_tip.y * image.shape[0])
                    
                    # Calculate distance between thumb and index finger
                    distance = np.sqrt((thumb_x - index_x)**2 + (thumb_y - index_y)**2)
                    
                    # Draw line and circles between fingers
                    cv2.line(image, (thumb_x, thumb_y), (index_x, index_y), hand_color, 3)
                    cv2.circle(image, (thumb_x, thumb_y), 8, hand_color, -1)
                    cv2.circle(image, (index_x, index_y), 8, hand_color, -1)
                    
                    # Display distance
                    cv2.putText(
                        image, f"Dist: {int(distance)}", (thumb_x, thumb_y - 20), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, hand_color, 2
                    )

                    # Volume calibration and control
                    if not vol_is_calibrated and vol_calibration_frames < 30:
                        if vol_calibration_frames == 0:
                            vol_max_distance = distance
                            vol_min_distance = distance
                        else:
                            vol_max_distance = max(vol_max_distance, distance)
                            vol_min_distance = min(vol_min_distance, distance)
                        vol_calibration_frames += 1
                        
                        # Display calibration progress
                        cv2.putText(
                            image, "Calibrating VOLUME...", (30, 40), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
                        )
                    elif vol_is_calibrated or vol_calibration_frames >= 30:
                        vol_is_calibrated = True
                        
                        # Convert distance to volume percentage (0-100%)
                        if vol_max_distance > vol_min_distance:
                            volume_percent = int(
                                ((distance - vol_min_distance) / 
                                 (vol_max_distance - vol_min_distance)) * 100
                            )
                            volume_percent = max(0, min(100, volume_percent))
                            
                            # Set volume (with delay to prevent frequent changes)
                            if vol_calibration_frames % 5 == 0:
                                current_volume = set_volume(volume_percent)
                        
                        vol_calibration_frames += 1

                # Display control type information
                cv2.putText(
                    image, f"{control_type}", (30, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, hand_color, 2, cv2.LINE_AA
                )
                
            else:  # Left hand
                hand_color = (0, 0, 255)  # Red for left hand
                control_type = "ICON"
                left_hand_detected = True
                left_hand_landmarks = landmarks
                
                # Check gun gesture for left hand
                gun_gesture = is_gun_gesture(landmarks)
                
                # Get wrist position for icon placement
                wrist = landmarks[HandLandmark.WRIST]
                left_hand_x = int(wrist.x * image.shape[1]) - left_hand_image.shape[1] // 2
                left_hand_y = int(wrist.y * image.shape[0]) - left_hand_image.shape[0] // 2
                left_hand_position = (left_hand_x, left_hand_y)
                
                # Display left hand information
                cv2.putText(
                    image, f"{control_type}", (30, 60), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, hand_color, 2, cv2.LINE_AA
                )
            
            # Draw hand landmarks using custom drawing utility
            landmark_spec = DrawingSpec(color=hand_color, thickness=2, circle_radius=4)
            connection_spec = DrawingSpec(color=hand_color, thickness=2)
            mp_drawing.draw_landmarks(
                image, 
                landmarks, 
                HAND_CONNECTIONS,
                landmark_drawing_spec=landmark_spec,
                connection_drawing_spec=connection_spec
            )

        # Check clap gesture if both hands detected
        if left_hand_landmarks and right_hand_landmarks:
            clap_gesture, clap_distance = is_clap_gesture(
                left_hand_landmarks, right_hand_landmarks
            )
            
            # Display clap gesture status and distance
            clap_status = "CLAP: YES" if clap_gesture else "CLAP: NO"
            cv2.putText(
                image, clap_status, (30, 210), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2, cv2.LINE_AA
            )
            cv2.putText(
                image, f"Dist: {clap_distance:.3f}", (30, 240), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2, cv2.LINE_AA
            )
            
            # If clap gesture detected and cooldown expired
            if clap_gesture and clap_cooldown <= 0:
                print(f"Clap gesture detected! Opening URL: {CLAP_GESTURE_URL}")
                webbrowser.open(CLAP_GESTURE_URL)
                clap_cooldown = 90  # Set cooldown (approximately 1.5-3 seconds)
                
            # Decrement cooldown if active
            if clap_cooldown > 0:
                clap_cooldown -= 1

    # If left hand detected AND gun gesture shown, display image
    if left_hand_detected and left_hand_position and gun_gesture:
        try:
            image = overlay_image(
                image, left_hand_image, left_hand_position[0], left_hand_position[1]
            )
            
            # Display anchor point
            anchor_x = left_hand_position[0] + left_hand_image.shape[1] // 2
            anchor_y = left_hand_position[1] + left_hand_image.shape[0] // 2
            cv2.circle(image, (anchor_x, anchor_y), 5, (0, 0, 255), -1)
        except Exception as e:
            print(f"Error overlaying image: {e}")
            
    # Display current volume value
    volume_status = "ACTIVE" if volume_control_active else "INACTIVE"
    volume_color = (0, 255, 0) if volume_control_active else (0, 0, 255)
    cv2.putText(
        image, f"Volume: {current_volume}% [{volume_status}]", (30, 90), 
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, volume_color, 2, cv2.LINE_AA
    )
    
    # Display gesture statuses
    gun_status = "GUN: YES" if gun_gesture else "GUN: NO"
    victory_status = "VICTORY: YES" if victory_gesture else "VICTORY: NO"
    cv2.putText(
        image, gun_status, (30, 180), 
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA
    )
    cv2.putText(
        image, victory_status, (30, 150), 
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA
    )
    
    # Display instructions
    cv2.putText(
        image, "Right hand (GREEN) - Volume (toggle with V)", (30, 120), 
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA
    )
    cv2.putText(
        image, "Left hand (RED) - Icon (GUN gesture)", (30, 140), 
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA
    )
    cv2.putText(
        image, "Both hands - CLAP gesture opens URL", (30, 160), 
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1, cv2.LINE_AA
    )
    cv2.putText(
        image, "Press 'q' to exit", (30, 270), 
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA
    )

    # Get actual frame size
    frame_height, frame_width = image.shape[:2]
    
    # Create window with frame size (auto-fit)
    cv2.namedWindow('Hand Tracking by d0x0day', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('Hand Tracking by d0x0day', frame_width, frame_height)
    
    # Display frame
    cv2.imshow('Hand Tracking by d0x0day', image)

    # Exit loop on 'q' key press
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Release resources
cap.release()
cv2.destroyAllWindows()
