# -*- coding: utf-8 -*-
"""Install the additive realtime DeepSeek + PS4-inspired UI patch."""
from pathlib import Path
from datetime import datetime
import shutil
import py_compile

ROOT=Path(__file__).resolve().parent
APP=ROOT/'app_logic.py'
HELPER=ROOT/'realtime_deepseek_ps4.py'
STAMP=datetime.now().strftime('%Y%m%d_%H%M%S')
BACKUP=ROOT/f'BACKUP_REALTIME_DEEPSEEK_PS4_{STAMP}'
MARKER='__REALTIME_DEEPSEEK_PS4_INSTALLED__'


def check(text,name):
    tmp=ROOT/f'__rt_syntax_{name}'
    tmp.write_text(text,encoding='utf-8',newline='\n')
    try: py_compile.compile(str(tmp),doraise=True)
    finally:
        try:tmp.unlink()
        except OSError:pass


def main():
    if not APP.exists():
        print('PATCH FAILED: app_logic.py not found in this folder.')
        return 2
    source=APP.read_text(encoding='utf-8')
    if MARKER in source:
        print('Already patched.')
        return 0
    anchor='        # Ensure OCR model UI is correctly set up on initial load\n'
    call=("        # __REALTIME_DEEPSEEK_PS4_INSTALLED__ -- additive runtime patch\n"
          "        try:\n"
          "            from realtime_deepseek_ps4 import install_realtime_deepseek\n"
          "            install_realtime_deepseek(self)\n"
          "        except Exception as realtime_patch_error:\n"
          "            log_debug(f'Realtime patch install error: {type(realtime_patch_error).__name__}: {realtime_patch_error}')\n")
    if anchor not in source:
        anchor='        self._fully_initialized = True\n'
        if anchor not in source:
            print('PATCH FAILED: initialization anchor not found.')
            return 3
        source=source.replace(anchor,anchor+call,1)
    else:
        source=source.replace(anchor,call+anchor,1)
    BACKUP.mkdir(parents=True,exist_ok=True)
    shutil.copy2(APP,BACKUP/APP.name)
    if HELPER.exists():shutil.copy2(HELPER,BACKUP/HELPER.name)
    try:
        check(source,'app_logic.py')
        check(HELPER.read_text(encoding='utf-8'),'realtime_deepseek_ps4.py')
    except Exception as exc:
        print('PATCH CANCELLED BEFORE WRITING:',type(exc).__name__,exc)
        print('Backup:',BACKUP)
        return 4
    APP.write_text(source,encoding='utf-8',newline='\n')
    py_compile.compile(str(APP),doraise=True)
    print('SUCCESS')
    print('Latest-only capture/OCR/translation is active at runtime.')
    print('DeepSeek chat/completions: temperature=0.0, top_p=0.1, max_tokens=256')
    print('Argos draft is used first when an installed pair is available.')
    print('No existing engine/provider file is deleted.')
    print('Backup:',BACKUP)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
