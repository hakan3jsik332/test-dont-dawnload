REALTIME DEEPSEEK + PS4-STYLE PATCH

This is an additive patch. It does not delete the existing engines, provider files, worker_threads.py, gui_builder.py, or main.py.

Changes:
- Latest frame only: old OCR frames are dropped instead of queued.
- Latest text only: only the newest subtitle is translated; stale results cannot overwrite newer text.
- Translation box updates immediately when a result arrives.
- Optional Argos en→fa draft appears first when the pair is installed, then DeepSeek replaces it.
- Adds DeepSeek to the existing Translation Model dropdown.
- Adds DeepSeek API Key / Base URL / Model / Source→Target controls to Settings.
- Adds a dark-blue PS4-inspired header with wave lines (no PlayStation logo/assets).
- Creates a timestamped backup before modifying app_logic.py.

Install:
1. Put INSTALL_REALTIME_DEEPSEEK_PS4_PATCH.py and realtime_deepseek_ps4.py beside app_logic.py.
2. Run: python INSTALL_REALTIME_DEEPSEEK_PS4_PATCH.py
3. Start the normal application.
4. In Settings, set DeepSeek API key/model and use en -> fa by default.
5. Select DeepSeek in Translation Model.

Testing note:
The patcher, modified app_logic.py, and helper syntax were compiled here. A real Windows game/OCR capture cannot be launched in this environment, so Windows screen-capture behavior still needs your machine to verify.
