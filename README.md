```markdown
# GestureFlow: Intuitive Hand Gesture Control for Linux 🖐️💻

[
https://img.shields.io/badge/OS-Linux%20Only-blue.svg?style=for-the-badge&logo=linux
](https://www.linux.org/)
[
https://img.shields.io/badge/Python-3.8%2B-blueviolet.svg?style=for-the-badge&logo=python
](https://www.python.org/)
[
https://img.shields.io/badge/Powered%20By-MediaPipe%20Hands-orange.svg?style=for-the-badge&logo=google
](https://developers.google.com/mediapipe/solutions/vision/hand_landmarker)
[
https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge
](LICENSE)

## ✨ Overview

GestureFlow transforms your webcam into a powerful input device, allowing you to control aspects of your Linux desktop using natural hand gestures. Built with MediaPipe for robust hand tracking and OpenCV for real-time video processing, this application offers an intuitive and engaging way to interact with your system. Adjust volume, display custom icons, and even launch URLs—all with simple hand movements!

Please note: This application is designed exclusively for Linux systems due to its reliance on PulseAudio for system volume control.

## 🎥 Demo

Watch GestureFlow in action! This video demonstrates the main functionalities including volume control, custom icon display, and the URL-opening clap gesture.

<details>
<summary>Click to view demo video</summary>

*For the best experience, download the video or view it on a platform that supports inline MP4 playback.*
*(GitHub's markdown might render MP4s as a download link rather than an embedded player. For guaranteed inline playback, consider converting a short demo to a .gif or hosting it on a service like YouTube and embedding it.)*

Here's how to link an MP4 directly:
*Make sure your demo.mp4 file is in your repository, for example, in an assets folder.*
markdown

copy

</details>

## 🚀 Features

•   **Volume Control (Right Hand 🟢):** Adjust your system's master volume by varying the distance between your thumb and index finger.
•   **Volume Toggle (Right Hand "V" Gesture):** Activate or deactivate volume control by performing a "Victory" gesture with your right hand.
•   **Custom Icon Display (Left Hand "Gun" Gesture 🔴):** Make a "Gun" gesture with your left hand to display a customizable icon (icon.png) on the screen, centered at your wrist.
•   **URL Launcher (Clap Gesture 🟡):** Bring both hands together in a "Clap" gesture to automatically open a predefined URL in your web browser.
•   **Real-time Visual Feedback:** See your hand landmarks and gesture statuses overlayed directly on your webcam feed.
•   **Dynamic Calibration:** Volume control automatically calibrates to your hand's range of motion.
•   **Customizable Icon:** Easily replace icon.png with your own image.
•   **Linux-Exclusive:** Seamless integration with PulseAudio for system-level volume control.

## ⚠️ Linux Only!

This application utilizes the pactl command-line utility for PulseAudio to control system volume. **Therefore, it will only function correctly on Linux distributions that use PulseAudio (which is most modern desktop Linux systems).** Attempting to run this on Windows or macOS will result in errors regarding volume control.

## 📋 Prerequisites

Before you begin, ensure you have the following installed on your **Linux system**:

•   **Python 3.8+**:

bash
  sudo apt update
  sudo apt install python3 python3-pip
```
•  Webcam: A functional webcam is required.
•  PulseAudio Utilities: These provide the pactl command.
  
```
bash
  sudo apt install pulseaudio-utils
```

▌🛠️ Installation

Follow these steps to get GestureFlow up and running:

1. Clone the repository:
  
```
bash
  git clone https://github.com/d0x0day/Hand-Tracking-by-d0x0day.git
  cd Hand-Tracking-by-d0x0day
```

2. Create a virtual environment (recommended):
  
```
bash
  python3 -m venv venv
  source venv/bin/activate
```

3. Install the required Python packages:
  Create a requirements.txt file in your project root with the following content:
  
```
mediapipe
  opencv-python
  numpy
  matplotlib
```
  Then install them:
  
```
bash
  pip install -r requirements.txt
```

4. Optional: Add a custom icon.
  Place your desired .png image named icon.png in the root directory of the project. If icon.png is not found, a default red "GUN" icon will be generated.

5. Place your demo video.
  If you want to use the inline video linking feature above, make sure your video file (e.g., demo.mp4) is located in the assets/ directory (create it if it doesn't exist).

▌🚀 Usage

Once installed, running GestureFlow is straightforward:

1. Activate your virtual environment (if you created one):
  
```
bash
  source venv/bin/activate
```

2. Run the application:
  
```
bash
  python your_main_script_name.py 
  # (Assuming your code is in a file like main.py or app.py)
```

3. Interact with gestures:

  •  Right Hand (Green Landmarks):
    *  Volume Control: Extend your thumb and index finger. The distance between them directly controls the system volume.
    *  Toggle Volume Control: Make a "V" (Victory) gesture. This will activate or deactivate the volume control feature.
  •  Left Hand (Red Landmarks):
    *  Display Icon: Form a "Gun" gesture (thumb and index finger extended, others bent) to make the icon.png appear near your hand.
  •  Both Hands (Yellow/Cyan Status):
    *  Open URL: Bring both hands together in a "Clap" motion to trigger the opening of the configured URL in your default web browser.

4. Exit the application:
  Press the 'q' key while the OpenCV window is focused.

▌⚙️ Configuration

You can customize some behaviors directly in the your_main_script_name.py file:

•  Clap Gesture URL:
  Change the URL that opens when you perform the clap gesture:
  
```
python
  CLAP_GESTURE_URL = "https://github.com/d0x0day/Hand-Tracking-by-d0x0day" # Change this!
```

•  Custom Icon:
  Replace the icon.png file in the root directory with your own 200x200 pixel image for the left-hand gesture. If your image has different dimensions, it will be resized.

▌💡 Troubleshooting

•  "Error loading image: [Errno 2] No such file or directory: 'icon.png'": This is normal if you haven't provided a custom icon.png. A default icon will be used instead.
•  Webcam not detected / cv2.VideoCapture(0) issues:
  •  Ensure your webcam is plugged in and recognized by your system.
  •  Check if other applications can access your webcam.
  •  You might need to adjust the cv2.VideoCapture(0) index if you have multiple cameras (try 1, 2, etc.).
•  Volume control not working:
  •  Confirm you are on Linux and have pulseaudio-utils installed.
  •  Verify pactl commands work from your terminal (e.g., pactl set-sink-volume @DEFAULT_SINK@ 50%).
  •  Ensure your user has permissions to control PulseAudio.
•  Gestures not recognized consistently:
  •  Lighting: Ensure good, even lighting on your hands. Avoid strong backlighting.
  •  Background: A plain, uncluttered background helps MediaPipe track hands more accurately.
  •  Camera Angle: Position your camera so your entire hands are clearly visible within the frame.
  •  Hand Position: Keep your hands distinct and well-separated from your body if possible.
  •  Confidence Thresholds: You can experiment with min_detection_confidence and min_tracking_confidence values in the code for better recognition, but be aware that lower values can lead to false positives.

▌🤝 Contributing

Contributions are welcome! If you have ideas for new gestures, performance improvements, or bug fixes, feel free to:

1. Fork the repository.
2. Create a new branch (git checkout -b feature/AmazingFeature).
3. Make your changes and commit them (git commit -m 'Add some AmazingFeature').
4. Push to the branch (git push origin feature/AmazingFeature).
5. Open a Pull Request.

▌📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

▌🙏 Acknowledgments

•  Google MediaPipe for the powerful hand tracking solution.
•  OpenCV for robust computer vision functionalities.

---
Made with ❤️ by d0x0day

```