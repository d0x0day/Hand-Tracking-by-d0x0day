import mediapipe as mp
import cv2
import numpy as np
import matplotlib.pyplot as plt
import os
import webbrowser

# Initialize MediaPipe components
mp_drawing = mp.solutions.drawing_utils
mp_hands = mp.solutions.hands

# Initialize MediaPipe Hands
hands = mp_hands.Hands(
    max_num_hands=2,
    min_detection_confidence=0.75,
    min_tracking_confidence=0.5,
)

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
    Set system volume on Linux (PulseAudio).
    
    Args:
        volume_percent: Volume level (0-100%)
    
    Returns:
        Clamped volume percentage
    """
    # Clamp volume between 0-100%
    volume_percent = max(0, min(100, volume_percent))
    
    # Set volume using pactl (PulseAudio)
    os.system(f"pactl set-sink-volume @DEFAULT_SINK@ {volume_percent}%")
    
    return volume_percent


def get_current_volume():
    """Get current system volume level."""
    result = os.popen("pactl get-sink-volume @DEFAULT_SINK@").read()
    # Parse command output to extract current volume
    try:
        volume_str = result.split('/')[1].strip().split(' ')[0]
        return int(volume_str.replace('%', ''))
    except Exception:
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
    thumb_tip = hand_landmarks.landmark[mp_hands.HandLandmark.THUMB_TIP]
    index_tip = hand_landmarks.landmark[mp_hands.HandLandmark.INDEX_FINGER_TIP]
    middle_tip = hand_landmarks.landmark[mp_hands.HandLandmark.MIDDLE_FINGER_TIP]
    ring_tip = hand_landmarks.landmark[mp_hands.HandLandmark.RING_FINGER_TIP]
    pinky_tip = hand_landmarks.landmark[mp_hands.HandLandmark.PINKY_TIP]
    
    # Get finger base landmarks
    thumb_mcp = hand_landmarks.landmark[mp_hands.HandLandmark.THUMB_MCP]
    index_mcp = hand_landmarks.landmark[mp_hands.HandLandmark.INDEX_FINGER_MCP]
    middle_mcp = hand_landmarks.landmark[mp_hands.HandLandmark.MIDDLE_FINGER_MCP]
    ring_mcp = hand_landmarks.landmark[mp_hands.HandLandmark.RING_FINGER_MCP]
    pinky_mcp = hand_landmarks.landmark[mp_hands.HandLandmark.PINKY_MCP]
    
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
    thumb_tip = hand_landmarks.landmark[mp_hands.HandLandmark.THUMB_TIP]
    index_tip = hand_landmarks.landmark[mp_hands.HandLandmark.INDEX_FINGER_TIP]
    middle_tip = hand_landmarks.landmark[mp_hands.HandLandmark.MIDDLE_FINGER_TIP]
    ring_tip = hand_landmarks.landmark[mp_hands.HandLandmark.RING_FINGER_TIP]
    pinky_tip = hand_landmarks.landmark[mp_hands.HandLandmark.PINKY_TIP]
    
    # Get finger base landmarks
    index_mcp = hand_landmarks.landmark[mp_hands.HandLandmark.INDEX_FINGER_MCP]
    middle_mcp = hand_landmarks.landmark[mp_hands.HandLandmark.MIDDLE_FINGER_MCP]
    ring_mcp = hand_landmarks.landmark[mp_hands.HandLandmark.RING_FINGER_MCP]
    pinky_mcp = hand_landmarks.landmark[mp_hands.HandLandmark.PINKY_MCP]
    
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
    left_wrist = left_hand_landmarks.landmark[mp_hands.HandLandmark.WRIST]
    right_wrist = right_hand_landmarks.landmark[mp_hands.HandLandmark.WRIST]
    
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

# Main loop
while cap.isOpened():
    ret, image = cap.read()
    if not ret:
        break

    # Flip frame horizontally for intuitive control
    image = cv2.flip(image, 1)

    # Convert frame to RGB
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # Process hand detection
    results = hands.process(rgb_image)

    # Hand tracking variables
    left_hand_detected = False
    left_hand_position = None
    left_hand_landmarks = None
    right_hand_landmarks = None
    gun_gesture = False  # Gun gesture flag for left hand
    victory_gesture = False  # Victory gesture flag for right hand
    
    # Draw hand landmarks and process gestures
    if results.multi_hand_landmarks:
        # Process each detected hand
        for i, hand_landmarks in enumerate(results.multi_hand_landmarks):
            # Determine hand type (left or right)
            hand_label = results.multi_handedness[i].classification[0].label
            
            # Note: Due to mirroring, hand labels are inverted
            if hand_label == "Right":
                hand_color = (0, 255, 0)  # Green for right hand (volume)
                control_type = "VOLUME"
                right_hand_landmarks = hand_landmarks
                
                # Check victory gesture for right hand
                victory_gesture = is_victory_gesture(hand_landmarks)
                
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
                    thumb_tip = hand_landmarks.landmark[mp_hands.HandLandmark.THUMB_TIP]
                    index_tip = hand_landmarks.landmark[mp_hands.HandLandmark.INDEX_FINGER_TIP]
                    
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
                left_hand_landmarks = hand_landmarks
                
                # Check gun gesture for left hand
                gun_gesture = is_gun_gesture(hand_landmarks)
                
                # Get wrist position for icon placement
                wrist = hand_landmarks.landmark[mp_hands.HandLandmark.WRIST]
                left_hand_x = int(wrist.x * image.shape[1]) - left_hand_image.shape[1] // 2
                left_hand_y = int(wrist.y * image.shape[0]) - left_hand_image.shape[0] // 2
                left_hand_position = (left_hand_x, left_hand_y)
                
                # Display left hand information
                cv2.putText(
                    image, f"{control_type}", (30, 60), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, hand_color, 2, cv2.LINE_AA
                )
            
            # Draw hand landmarks
            mp_drawing.draw_landmarks(
                image, 
                hand_landmarks, 
                mp_hands.HAND_CONNECTIONS,
                mp_drawing.DrawingSpec(color=hand_color, thickness=2, circle_radius=4),
                mp_drawing.DrawingSpec(color=hand_color, thickness=2)
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