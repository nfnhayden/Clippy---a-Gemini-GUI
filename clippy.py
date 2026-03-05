import sys
import os
import shutil
import threading
import subprocess
import re
import random
import time
from collections import deque
from typing import Optional, List, Tuple, Any, cast, TYPE_CHECKING, IO

from PyQt6.QtWidgets import ( # type: ignore
    QApplication, QWidget, QLabel, QVBoxLayout, 
    QMenu, QSystemTrayIcon, QTextEdit, QLineEdit,
    QSizePolicy, QPushButton, QHBoxLayout, QFrame,
    QScrollBar, QTabWidget, QPlainTextEdit
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QSize, QThread, pyqtSignal, QObject, QEvent, QSettings # type: ignore
from PyQt6.QtGui import QPixmap, QPainter, QRegion, QBitmap, QColor, QFont, QAction, QCursor, QIcon, QTextCursor # type: ignore

if TYPE_CHECKING:
    from clippy_input import GlobalKeyHook # type: ignore
    from animation_loader import load_animations # type: ignore

# Import our animation loader and key hook
try:
    from animation_loader import load_animations # type: ignore
    from clippy_input import GlobalKeyHook # type: ignore
except ImportError:
    # If run directly or from venv
    try:
        from clippy.animation_loader import load_animations # type: ignore
        from clippy.clippy_input import GlobalKeyHook # type: ignore
    except ImportError:
        # Fallback for when running inside the directory
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        from animation_loader import load_animations # type: ignore
        from clippy_input import GlobalKeyHook # type: ignore

class DebugConsole(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Clippy's Brain (Gemini CLI Terminal)")
        self.resize(800, 500)
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Dual View Tabs
        self.tabs = QTabWidget()
        
        # Tab 1: Live Terminal (Clean redraws)
        self.live_edit = QTextEdit()
        self.live_edit.setReadOnly(True)
        self.live_edit.setStyleSheet("background-color: black; color: #e6e6e6; font-family: 'Consolas', monospace; font-size: 11pt;")
        self.tabs.addTab(self.live_edit, "Live Terminal")
        
        # Tab 2: Raw History (Full scrollback context)
        self.history_edit = QPlainTextEdit()
        self.history_edit.setReadOnly(True)
        self.history_edit.setStyleSheet("background-color: #1a1a1a; color: #b0b0b0; font-family: 'Consolas', monospace; font-size: 10pt;")
        self.tabs.addTab(self.history_edit, "Raw History")
        
        # Compat: alias self.text_edit to self.live_edit for rest of code
        self.text_edit = self.live_edit
        
        self.layout.addWidget(self.tabs)
        self.setLayout(self.layout)
        
        # State
        self.current_buffer: str = ""
        self.log_queue: List[str] = []
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._process_queue)
        self.refresh_timer.start(50)

    def _ansi_to_html(self, text):
        """Converts ANSI escape codes to HTML for colors."""
        
        # Escape HTML entities
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        # Handle RGB Foreground: \x1b[38;2;R;G;Bm
        text = re.sub(r'\x1b\[38;2;(\d+);(\d+);(\d+)m', r'<span style="color:rgb(\1,\2,\3);">', text)
        
        # Handle RGB Background: \x1b[48;2;R;G;Bm
        text = re.sub(r'\x1b\[48;2;(\d+);(\d+);(\d+)m', r'<span style="background-color:rgb(\1,\2,\3);">', text)
        
        # Handle standard 16 colors
        color_map = {
            "30": "black", "31": "#ff5555", "32": "#50fa7b", "33": "#f1fa8c",
            "34": "#bd93f9", "35": "#ff79c6", "36": "#8be9fd", "37": "#f8f8f2",
            "90": "#6272a4"
        }
        for code, color in color_map.items():
            text = text.replace(f'\x1b[{code}m', f'<span style="color:{color};">')

        # Handle Reset and Bold
        text = re.sub(r'\x1b\[1m', '<b>', text)
        # 39=fg reset, 48=bg reset, 0=all reset
        # Handle both 49 (bg reset) and 48;.. (bg set) resets
        text = re.sub(r'\x1b\[[034]9m|\x1b\[0m', '</span>', text)
        text = text.replace("\x1b[22m", "</b>")
        
        # Strip remaining CSI/OSC/Query sequences (Aggressive)
        text = re.sub(r'\x1b\[[<=>?0-9;]*[a-zA-Z]', '', text)
        text = re.sub(r'\x1b\][0-9;]*.*?(?:\x07|\x1b\\)', '', text) # OSC with ST or BEL
        text = re.sub(r'\x1b[=>][0-9;?]*', '', text) # Misc terminal keys
        
        # Convert newlines to breaks
        text = text.replace("\n", "<br>")
        return text

    def log(self, text):
        """Adds text to queue for batch processing."""
        self.log_queue.append(text)

    def _process_queue(self):
        """Processes buffered logs sequentially to ensure correct rendering order."""
        if not self.log_queue:
            return
            
        data = "".join(self.log_queue)
        self.log_queue.clear()
        
        # Append to Raw History (strip ANSI but keep all lines)
        clean_hist = re.sub(r'\x1b\[[<=>?0-9;]*[a-zA-Z]', '', data)
        self.history_edit.appendPlainText(clean_hist)
        
        self.current_buffer += data
        
        if not self.current_buffer:
            return

        # 1. Handle "Hard" global clears immediately
        if "\x1b[2J" in self.current_buffer or "\x1b[1;1H" in self.current_buffer:
            self.text_edit.clear()
            self.current_buffer = re.sub(r'\x1b\[2J|\x1b\[1;1H', '', self.current_buffer)

        # 2. Protect partial trailing sequences
        safe_buffer = self.current_buffer
        trailing_partial = ""
        m_partial = re.search(r'\x1b\[[0-9;?]*$', safe_buffer)
        if not m_partial:
            m_partial = re.search(r'\x1b$', safe_buffer)
            
        if m_partial:
            raw_full = str(self.current_buffer)
            part_text = str(m_partial.group(0))
            parts = raw_full.rsplit(part_text, 1)
            safe_buffer = parts[0]
            trailing_partial = part_text
        
        if not safe_buffer:
            return

        # 3. Sequential Token Processing
        # Split by: \x1b[...A (Move Up), \r (CR), \x1b[G (Pos), \x1b[2K (Clear Line), \n (LF)
        # We use capturing groups to keep the delimiters
        tokens = re.split(r'(\x1b\[\d+A|\r|\x1b\[G|\x1b\[2K|\n)', safe_buffer)
        
        cursor = self.text_edit.textCursor()
        for token in tokens:
            if not token: continue
            
            # Action: Move Up (\x1b[nA)
            m_up = re.match(r'\x1b\[(\d+)A', token)
            if m_up:
                n = int(m_up.group(1))
                for _ in range(n):
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    if cursor.blockNumber() > 0 or cursor.columnNumber() > 0:
                        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
                        cursor.removeSelectedText()
                        if cursor.blockNumber() > 0:
                            cursor.deletePreviousChar()
                continue
            
            # Action: CR / Horizontal Absolute / Clear Line
            if token in ['\r', '\x1b[G', '\x1b[2K']:
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                cursor.removeSelectedText()
                continue
            
            # Action: Newline
            if token == '\n':
                cursor.movePosition(QTextCursor.MoveOperation.End)
                # Ensure we don't insert excessive breaks if last was empty
                self.text_edit.append("")
                continue
                
            # Text Chunk
            html = self._ansi_to_html(token)
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.text_edit.insertHtml(html)
            
        self.current_buffer = trailing_partial
        sb = self.text_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

class GeminiSession(QObject):
    chunk_received = pyqtSignal(str) 
    log_message = pyqtSignal(str)
    session_ready = pyqtSignal() # When CLI is ready for input
    
    CLEVER_COMMENTS = [
        "Analyzing your query with paperclip precision...",
        "Consulting the desktop gods...",
        "Tidying up my wireframe for a better answer...",
        "Sifting through the digital office bin...",
        "Polishing my metal curves...",
        "Rethinking the concept of a spreadsheet...",
        "Calculating the optimal staples-to-paper ratio...",
        "Scanning for potential document errors...",
        "Searching my legacy database (Office '97)...",
        "Converting paperclip thoughts to human words..."
    ]
    
    def __init__(self):
        super().__init__()
        self.process = None
        self.current_model = "gemini-3-flash-preview" # Default working model
        self.running = False
        self.reader_thread = None
        self._start_process()

    def _start_process(self):
        """Starts the persistent Gemini CLI process using mock_tty.mjs."""
        self.stop()

        base_dir = os.path.dirname(os.path.abspath(__file__))
        mock_tty = os.path.join(base_dir, "mock_tty.mjs")
        gemini_index = os.path.join(base_dir, "node_modules", "@google", "gemini-cli", "dist", "index.js")
        
        if not os.path.exists(mock_tty):
            self.log_message.emit(f"❌ Error: {mock_tty} not found.")
            return
            
        # Command: node mock_tty.mjs <gemini_index> -m <model>
        cmd = ["node", mock_tty, gemini_index, "-m", self.current_model]
        
        self.log_message.emit(f"🚀 Starting Persistent Gemini (Mock TTY): {' '.join(cmd)}")
        
        creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creation_flags,
                encoding='utf-8',
                errors='replace'
            )
            
            self.running = True
            self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
            self.reader_thread.start()
        except Exception as e:
            self.log_message.emit(f"❌ Failed to start Gemini: {e}")

    def strip_ansi(self, text):
        """Removes ANSI escape sequences from text."""
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def _read_output(self):
        """Background thread to read from the process stdout."""
        buffer = ""
        while self.running and self.process and self.process.poll() is None:
            try:
                char = self.process.stdout.read(1)
                if not char:
                    break
                
                buffer += char
                
                # Check for prompt signal (stripped of ANSI)
                clean_buffer = self.strip_ansi(buffer)
                
                # The prompt usually ends with "> "
                if clean_buffer.endswith("> ") or clean_buffer.endswith("! > "):
                    if "Connecting to" not in clean_buffer:
                         self.session_ready.emit()
                    
                    # Log the full clean line/prompt to debug
                    self.log_message.emit(f"CLI: {clean_buffer.strip()}")
                    
                    # If there was text before the prompt, send it to bubble
                    # but usually, we want to clear the buffer here
                    buffer = ""
                    continue

                # Handle full lines
                if "\n" in buffer:
                    line = buffer
                    clean_line = self.strip_ansi(line).strip()
                    
                    # Log raw but stripped to debug console
                    if clean_line:
                        self.log_message.emit(clean_line)
                    
                    # Filter CLI Noise and Status Lines
                    noise_patterns = [
                        "Loaded cached", "DeprecationWarning", "Hook registry", 
                        "Mock TTY started", "Ready (", "Working… (", "Initializing...",
                        "Type your message", "for shortcuts", "no sandbox", "/model"
                    ]
                    
                    if any(x in clean_line for x in noise_patterns):
                        buffer = ""
                        continue
                    
                    # Emit clean content to speech bubble
                    if clean_line:
                        # If it looks like a tool call or AI response, send it
                        self.chunk_received.emit(clean_line + "\n")
                    
                    buffer = ""

            except Exception as e:
                self.log_message.emit(f"Read error: {e}")
                break
            
        self.log_message.emit("🛑 Gemini process terminated.")

    def send_query(self, user_input):
        """Writes the query to the persistent process stdin."""
        if not self.process or self.process.poll() is not None:
            self.log_message.emit("⚠️ Process died. Restarting...")
            self._start_process()
            
        if self.process and self.process.stdin:
            try:
                self.process.stdin.write(user_input + "\n")
                self.process.stdin.flush()
            except Exception as e:
                self.log_message.emit(f"❌ Failed to write to process: {e}")

    def set_model(self, model_name):
        self.current_model = model_name
        self.log_message.emit(f"🔄 Restarting Gemini with model: {model_name}")
        self._start_process()
        
        # Save choice
        settings = QSettings("Clippy", "ClippyApp")
        settings.setValue("last_model", model_name)

    def stop(self):
        self.running = False
        p = self.process
        if p is not None:
            try:
                p.terminate()
                p.wait(timeout=1)
            except:
                try: p.kill()
                except: pass
            self.process = None

    def _direct_write(self, text):
        """Allows direct writing to the process stdin (for persona handshake)."""
        p = self.process
        if p is not None and p.stdin:
            try:
                p.stdin.write(text + "\n")
                p.stdin.flush()
            except Exception as e:
                self.log_message.emit(f"❌ Handshake write failed: {e}")

    def _execute_tool(self, name, args):
        """Tool execution logic."""
        try:
            if name == "list_files":
                return str(os.listdir(os.getcwd()))
            elif name == "read_file":
                fname = args.get("filename", "").strip()
                if not fname: return "Error: Missing filename arg."
                if ".." in fname or ":" in fname: return "Error: Path traversal not allowed."
                if not os.path.exists(fname): return "Error: File not found."
                with open(fname, 'r', encoding='utf-8') as f:
                    return f.read()
            elif name == "write_file":
                fname = args.get("filename", "").strip()
                content = args.get("content", "")
                if not fname: return "Error: Missing filename arg."
                if ".." in fname or ":" in fname: return "Error: Path traversal not allowed."
                with open(fname, 'w', encoding='utf-8') as f:
                    f.write(content)
                return f"Success: Wrote to {fname}"
        except Exception as e:
            return f"Tool Execution Error: {e}"
        return "Error: Unknown tool."

class StartupWorker(QThread):
    startup_finished = pyqtSignal(bool, str)

    def run(self):
        try:
            import shutil
            gemini_cmd = "gemini"
            if os.name == 'nt':
                gemini_cmd_path = shutil.which("gemini.cmd")
                if gemini_cmd_path:
                    gemini_cmd = gemini_cmd_path
            
            # Simple version check to ensure it's responsive
            cmd = [gemini_cmd, "--version"]
            
            process = subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                encoding='utf-8',
                errors='replace',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            ) 
            
            if process.returncode == 0:
                self.startup_finished.emit(True, "Ready!")
            else:
                self.startup_finished.emit(False, f"Error: Exit code {process.returncode}")
                
        except Exception as e:
            self.startup_finished.emit(False, str(e))

class SpeechBubble(QWidget):
    def __init__(self, parent: Optional['ClippyWidget'] = None):
        super().__init__() # Use default init
        self.clippy_ref: Optional['ClippyWidget'] = parent # Keep reference manually
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(400) # Prevents massive geometry spasms
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Bubble styling
        self.frame = QFrame()
        self.frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFE1;
                border: 1px solid #000000;
                border-radius: 10px;
                padding: 10px;
            }
        """)
        frame_layout = QVBoxLayout()
        self.frame.setLayout(frame_layout)
        
        self.output_label = QTextEdit("Loading Gemini...\nPlease wait...")
        self.output_label.setReadOnly(True)
        self.output_label.setAcceptRichText(True)
        self.output_label.setStyleSheet("""
            QTextEdit {
                font-family: Tahoma; 
                font-size: 12px; 
                color: black; 
                background-color: transparent;
                border: none;
            }
        """)
        self.output_label.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.output_label.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.output_label.setMaximumHeight(400) # BUOYANCY FIX: Stop the float!
        
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Type here...")
        self.input_box.returnPressed.connect(self.process_input)
        self.input_box.installEventFilter(self) # Install filter for arrows/ctrl+c
        # Disable input while loading
        self.input_box.setEnabled(False)
        
        self.frame_layout = frame_layout
        frame_layout.addWidget(self.output_label)
        frame_layout.addWidget(self.input_box)
        
        layout.addWidget(self.frame)
        
        self.is_generating = False
        self.clever_timer = QTimer(self)
        self.clever_timer.timeout.connect(self._show_clever_comment)
        
        # History
        self.history = []
        self.history_index = -1
        
        # Start startup check
        self.startup_worker = StartupWorker()
        self.startup_worker.startup_finished.connect(self.on_startup_finished)
        self.startup_worker.start()

    def on_startup_finished(self, success, message):
        if success:
            self.output_label.setText("Connecting to Gemini...")
        else:
            self.input_box.setEnabled(True)
            self.output_label.setText(f"CLI Error:\n{message}")
            ref = self.clippy_ref
            if ref:
                ref.play_animation("Idle")

    def on_session_ready(self):
        """Called when GeminiSession is actually interactive but not yet persona-aware."""
        self.input_box.setEnabled(False) # Keep disabled until persona handshake
        self.output_label.setText("Clippy is waking up...") # Transition text
        ref = self.clippy_ref
        if ref:
            ref.play_animation("Idle1_1")

    def on_persona_ready(self):
        """Called when the persona handshake is complete."""
        self.input_box.setEnabled(True)
        # Clear the "Waking up..." text so the first AI response has a clean slate
        self.output_label.clear()
        self.adjust_size_and_pos()

    def on_status_update(self, msg):
        """Update bubble with intermediate CLI status without wiping AI response."""
        # Only show tech status if we aren't currently rendering an AI response chunk
        # or if the bubble is mostly empty/init.
        if self.is_generating and len(self.output_label.toPlainText()) < 50:
             self.output_label.setPlainText(msg)
             self.adjust_size_and_pos()
        
        # Always log to clippy's internal log for debugging
        ref = self.clippy_ref
        if ref:
            # We could show status in a smaller separate label later
            pass
        # ref.play_animation("Checking") # Suggests background activity

    def update_bubble_pos(self):
        ref = self.clippy_ref
        if not ref:
            return
            
        screen = self.screen()
        if not screen:
            screen = QApplication.primaryScreen()
        
        available_geom = screen.availableGeometry()
        
        # Clippy Geometry
        cx = ref.x()
        cy = ref.y()
        cw = ref.width()
        ch = ref.height()
        
        # Bubble Geometry
        bw = self.width()
        bh = self.height()
        
        # Determine Horizontal placement (Left vs Right of Clippy)
        # If Clippy is far enough right, put bubble on left.
        # Threshold: if cx > bw + 20, we can fit on left.
        place_on_left = (cx > bw + 20)
        
        if place_on_left:
            # Right edge of bubble touches Left edge of Clippy (- padding)
            target_x = cx - bw + 20 
        else:
            # Place on Right
            target_x = cx + cw - 30
            
        # Determine Vertical placement (Top vs Bottom of Clippy)
        place_on_top = (cy > bh + 20)
        
        if place_on_top:
            target_y = cy - bh + 40 
        else:
            target_y = cy + ch - 50

        # Clamp to screen
        if target_x < available_geom.x():
            target_x = available_geom.x()
        elif target_x + bw > available_geom.right():
            target_x = available_geom.right() - bw
            
        if target_y < available_geom.y():
            target_y = available_geom.y()
        elif target_y + bh > available_geom.bottom():
            target_y = available_geom.bottom() - bh
            
        self.move(int(target_x), int(target_y))

    def eventFilter(self, obj, event):
        if obj == self.input_box and event.type() == QEvent.Type.KeyPress:
            # History navigation
            if event.key() == Qt.Key.Key_Up:
                if self.history:
                    self.history_index = max(0, self.history_index - 1)
                    if self.history_index == -1: 
                        self.history_index = len(self.history) - 1
                    
                    if self.input_box.text() == "" and self.history_index == 0 and len(self.history) > 0:
                         pass # weird logic fix from before, just keep simple
                    
                    # If empty or at -1, wrap to end? Logic a bit fuzzy but workable
                    if self.history_index == -1:
                         self.history_index = len(self.history) - 1
                    
                    self.input_box.setText(self.history[self.history_index])
                return True
            
            elif event.key() == Qt.Key.Key_Down:
                if self.history:
                    if self.history_index != -1:
                        self.history_index = min(len(self.history), self.history_index + 1)
                        if self.history_index >= len(self.history):
                            self.input_box.clear()
                            self.history_index = -1
                        else:
                            self.input_box.setText(self.history[self.history_index])
                return True
                
            # Ctrl+C to stop
            elif event.key() == Qt.Key.Key_C and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                if self.worker and self.worker.isRunning():
                    self.stop_generation()
                    return True

        return super().eventFilter(obj, event)

    def stop_generation(self):
        self.is_generating = False
        self.clever_timer.stop()
        ref = self.clippy_ref
        if ref:
            # Clippy can't easily "cancel" a persistent stream without killing session
            # but we can at least stop UI updates.
            self.output_label.append("\n[Stream Stopped]")
            self.adjust_size_and_pos()
            ref.play_animation("Idle")

    def process_input(self):
        text = self.input_box.text().strip()
        ref = self.clippy_ref
        if text and ref:
            # Add to local input history
            self.history.append(text)
            self.history_index = -1
            
            # Show in bubble immediately as "User: ..." (optional, or just wait for AI)
            # Actually, standard CLI behavior is just to show the result.
            # But users expect to see what they typed if it's a bubble conversation.
            # For now, let's NOT append it to the label ourselves, 
            # because the CLI might echo it back (which we are now trying to filter).
            # If we filter the CLI echo, we should probably show it ourselves here if we want chat-style.
            # Let's stick to "Output Only" bubble for now to keep it clean, 
            # OR we can append it with a > prefix.
            
            # Store for echo filtering
            # We store it exactly as typed, but also need to consider CLI reflowing.
            if hasattr(ref, 'gemini_session'):
                ref.gemini_session.last_user_input = text

            # Clear input
            self.input_box.clear()

            # Send to Gemini
            # Send to Gemini
            if ref.gemini_session:
                ref.gemini_session.send_query(text)
                
            # UI State
            self.is_generating = True
            # Do NOT clear yet, wait for first chunk or show comment
            self.clever_timer.start(3000) # Start quips
            ref.play_animation("SendMail")

            self.history_index = len(self.history)
            
            # self.output_label.setPlainText(f"> {text}\n") # Don't show user input to avoid duplication
            self.input_box.clear()
            self.adjust_size_and_pos()
            
            # Start UX latency masking immediately
            self.is_generating = True
            self._show_clever_comment() # Show first one immediately
            self.clever_timer.start(8000) # Slower rhythm for reading: 8s
            
            if ref.current_anim_name != "Processing":
                ref.play_animation("Processing")

    def update_thinking(self, text):
        if self.is_generating:
            # First chunk of actual response received (likely AI text)
            # Re-enable input so user can type while streaming
            self.input_box.setEnabled(True)
            self.input_box.setFocus()
            
            # Check if this looks like status text or real text
            is_status = any(x in text for x in ["Initializing", "Analyzing", "Assessing", "Working"])
            
            if is_status:
                # Replace the bubble text with the new status
                self.output_label.setPlainText(text.strip())
                self.adjust_size_and_pos()
                return
            else:
                # Real response chunk received!
                self.is_generating = False
                self.clever_timer.stop()
                
                # If we were showing a status or clever comment, clear it before response
                current_text = self.output_label.toPlainText()
                if len(current_text) < 200: # Only clear small status messages
                     self.output_label.clear()

                ref = self.clippy_ref
                if ref:
                    ref.play_animation("Idle1_1")
        
        # Once we are out of "generating" (status) mode, insert response chunks normally
        self.output_label.insertPlainText(text)
        
        self.adjust_size_and_pos()
        sb = self.output_label.verticalScrollBar()
        sb.setValue(sb.maximum())

    def finalize_response(self):
        # Persistence: CLI manages its own history, but we can store locally if needed
        ref = self.clippy_ref
        if ref:
            ref.play_animation("Idle1_1")

    def _show_clever_comment(self):
        ref = self.clippy_ref
        if not self.is_generating or not ref:
            return
        
        # Cast to Any or use a local session ref to avoid attribute errors on ref
        session: Any = getattr(ref, 'gemini_session', None)
        if not session:
            return
            
        comment = random.choice(session.CLEVER_COMMENTS)
        # Keep user input (line 0) and append the quip
        text = self.output_label.toPlainText()
        lines = text.split("\n")
        if lines:
            self.output_label.setPlainText(lines[0] + f"\n_{comment}_")
        self.adjust_size_and_pos()

    def adjust_size_and_pos(self):
        self.adjustSize()
        self.update_bubble_pos()

class ClippyWidget(QWidget):
    def __init__(self):
        super().__init__()
        
        # Window setup
        # Removed Qt.WindowType.Tool so it shows in taskbar
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Load assets
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.animations = load_animations(os.path.join(self.script_dir, "agent.js"))
        self.sprite_sheet = QPixmap(os.path.join(self.script_dir, "map.png"))
        
        if self.sprite_sheet.isNull():
            print(f"Error: Could not load map.png from {self.script_dir}")
            sys.exit(1)

        # Animation state
        self.current_anim_name = "Show"
        if "animations" in self.animations and self.current_anim_name in self.animations["animations"]:
            self.current_anim_data = self.animations["animations"][self.current_anim_name]
        else:
            # Fallback
            self.current_anim_data = {"frames": []}
            
        self.frame_index = 0
        
        # Set Window Icon from first frame of Idle animation
        try:
             idle_data = self.animations["animations"].get("Idle1_1") or self.animations["animations"].get("Idle")
             if idle_data and "frames" in idle_data:
                 first_frame = idle_data["frames"][0]
                 if "images" in first_frame and first_frame["images"]:
                     x, y = first_frame["images"][0]
                     icon_pixmap = self.sprite_sheet.copy(x, y, 124, 93)
                     self.setWindowIcon(QIcon(icon_pixmap))
        except Exception as e:
             print(f"Failed to set icon: {e}")
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(100) # Default
        
        # Dragging state
        self.dragging = False
        self.offset = QPoint()
        self.old_pos = None

        # Speech Bubble
        self.bubble = SpeechBubble(self)
        self.bubble.move(self.x() - 200, self.y() - 150)
        self.bubble.hide()
        self.bubble_visible = False
        
        # Debug Console
        self.debug_console = DebugConsole()
        
        # Initial geometry
        self.frame_width = 124
        self.frame_height = 93
        self.resize(self.frame_width, self.frame_height)
        
        # Position bottom right
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 200, screen.height() - 200)

        # Persistent Gemini Session
        self.gemini_session = GeminiSession()
        self.gemini_session.log_message.connect(self.debug_console.log)
        self.gemini_session.chunk_received.connect(self.bubble.update_thinking)
        self.gemini_session.session_ready.connect(self.inject_persona)

        self._persona_injected = False

        # Start Global Key Hook
        hook_win = "--override-win-key" in sys.argv
        self.key_hook = GlobalKeyHook(hook_win_key=hook_win)
        self.key_hook.activated.connect(self.toggle_bubble)
        self.key_hook.start()

    def inject_persona(self):
        """Injects the Clippy persona once the session is ready."""
        if self._persona_injected:
            return
        self._persona_injected = True

        # Compact Handshake for One-Shot Mode
        # We just want to prime the history with the persona
        prompt = (
            "You are Clippy, a witty paperclip assistant. "
            "You have access to the following tools to help the user:\n"
            "1. list_files() -> Returns a list of files in the current directory.\n"
            "2. read_file(\"filename\") -> Returns the content of the file.\n"
            "3. write_file(\"filename\", \"content\") -> Writes content to a file.\n\n"
            "To use a tool, you MUST output an XML block like this:\n"
            "<tool code=\"read_file\">\n"
            "  <arg name=\"filename\">test.txt</arg>\n"
            "</tool>\n\n"
            "For writing files:\n"
            "<tool code=\"write_file\">\n"
            "  <arg name=\"filename\">hello.py</arg>\n"
            "  <arg name=\"content\">print('Hello')</arg>\n"
            "</tool>\n\n"
            "Do not simulate the tool output. Wait for the system to provide it.\n"
            "Be concise. "
            "Introduce yourself briefly."
        )
        # Trigger first response
        self.gemini_session.send_query(prompt)
        
        # Show 'Thinking' for this session-init message
        self.bubble.is_generating = True 
        self.bubble.output_label.setText("Waking up...")
        self.bubble._show_clever_comment()

    def closeEvent(self, event):
        self.key_hook.stop()
        self.key_hook.wait()
        self.gemini_session.close() # Was stop()
        self.bubble.close()
        self.debug_console.close()
        super().closeEvent(event)

    def changeEvent(self, event):
        # Handle minimize/restore to sync bubble
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                self.bubble.hide()
                self.debug_console.hide()
            elif self.isVisible() and self.bubble_visible:
                self.bubble.show()
                self.bubble.update_bubble_pos()
        super().changeEvent(event)

    def start_animation(self, name):
        if "animations" not in self.animations or name not in self.animations["animations"]:
            # Try to find any idle
            idles = [k for k in self.animations.get("animations", {}).keys() if "Idle" in k]
            if idles:
                name = idles[0]
            else:
                return # Can't start anything
            
        self.current_anim_name = name
        self.current_anim_data = self.animations["animations"][name]
        self.frame_index = 0
        self.update_frame()

    def update_frame(self):
        frames = self.current_anim_data.get("frames", [])
        if not frames:
            return

        if self.frame_index >= len(frames):
            # Animation finished
            self.start_animation(self.get_next_random_anim())
            return

        frame_data = frames[self.frame_index]
        duration = frame_data.get("duration", 100)
        
        # Update sprite view
        self.update()
        
        # Setup next frame
        self.frame_index += 1
        self.timer.start(duration)

    def get_next_random_anim(self):
        if "animations" not in self.animations:
            return None
        # Weighted random choice? Just pick an Idle one
        idles = [k for k in self.animations["animations"].keys() if "Idle" in k]
        if not idles:
            return "Show" # Fallback
        return random.choice(idles)
    
    def play_animation(self, name):
        self.start_animation(name)

    def paintEvent(self, event):
        painter = QPainter(self)
        if not self.sprite_sheet or not self.current_anim_data:
            return

        frames = self.current_anim_data.get("frames", [])
        if not frames:
            return

        # Handle index out of bounds safety
        idx = min(self.frame_index, len(frames) - 1)
        frame_data = frames[idx]
        
        # frames['images'] is a list of [x, y] coordinates. Usually just one.
        if "images" in frame_data and frame_data["images"]:
            # Coordinate in sprite sheet
            src_pos = frame_data["images"][0]
            if isinstance(src_pos, list) and len(src_pos) >= 2:
                x, y = src_pos[0], src_pos[1]
                
        # Draw the portion of the sprite sheet
                painter.drawPixmap(0, 0, self.sprite_sheet, x, y, self.frame_width, self.frame_height)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = event.globalPosition().toPoint()
            self.drag_start_pos = event.globalPosition().toPoint() # Record start
            self.play_animation("GetAttention")
        elif event.button() == Qt.MouseButton.RightButton:
            # Show context menu
            menu = QMenu(self)
            menu.setStyleSheet("QMenu { background-color: #FFFFE1; border: 1px solid black; } QMenu::item:selected { background-color: #000080; color: white; }")
            
            # Model Selection Submenu
            model_menu = menu.addMenu("Change Model")
            
            # (Label, Model ID)
            # Reverted to 2.0/1.5 because 2.5 Preview IDs were rejected by API (404)
            models = [
                ("Gemini 3 Flash Preview (Recommended)", "gemini-3-flash-preview"),
                ("Gemini 1.5 Flash", "gemini-1.5-flash"), 
                ("Gemini 2.0 Flash", "gemini-2.0-flash"),
                ("Gemini 2.0 Pro Exp", "gemini-2.0-pro-exp-02-05"),
                ("Gemini 1.5 Pro", "gemini-1.5-pro"),
            ]
            
            for label, model_id in models:
                action = QAction(label, self)
                action.setCheckable(True)
                if model_id == self.gemini_session.current_model:
                    action.setChecked(True)
                # Use a closure to capture the model ID correctly
                action.triggered.connect(lambda checked, m=model_id: self.set_model(m))
                model_menu.addAction(action)

            menu.addSeparator()
            
            setup_action = QAction("Open Debug Console", self)
            setup_action.triggered.connect(self.debug_console.show)
            menu.addAction(setup_action)
            
            exit_action = QAction("Exit", self)
            exit_action.triggered.connect(self.close)
            menu.addAction(exit_action)
            
            menu.exec(QCursor.pos())

    def set_model(self, model_name):
        self.gemini_session.set_model(model_name)
        if self.bubble.isVisible():
            self.bubble.output_label.setText(f"Model switched to {model_name}!")

    def mouseMoveEvent(self, event):
        if self.old_pos:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPosition().toPoint()
            if self.bubble_visible:
                 self.bubble.update_bubble_pos()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and hasattr(self, 'drag_start_pos') and self.drag_start_pos:
            # Check if it was a click or a drag
            current_pos = event.globalPosition().toPoint()
            dist = (current_pos - self.drag_start_pos).manhattanLength()
            
            if dist < 5: # Threshold for "click"
                self.toggle_bubble()
            
            self.drag_start_pos = None
        self.old_pos = None
        self.play_animation("Idle1_1")

    def toggle_bubble(self):
        if self.bubble.isVisible():
            self.bubble.hide()
        else:
            # Position bubble above and left of clippy
            self.bubble.adjust_size_and_pos()
            self.bubble.show()
            self.bubble.activateWindow()
            self.bubble.raise_()
            self.bubble.input_box.setFocus()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    clippy = ClippyWidget()
    clippy.show()
    sys.exit(app.exec())