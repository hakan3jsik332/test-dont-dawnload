# -*- coding: utf-8 -*-
"""Additive realtime DeepSeek patch for Game-Changing Translator.

The original engines and worker files are preserved.  This module installs
runtime hooks from app_logic.py for latest-frame/latest-text processing.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
import traceback
from types import MethodType

try:
    import urllib.request
    import urllib.error
except Exception:
    urllib = None

try:
    import argostranslate.translate as _argos_translate
    _ARGOS_OK = True
except Exception:
    _ARGOS_OK = False

try:
    from PIL import ImageGrab
except Exception:
    ImageGrab = None

try:
    import pyautogui
except Exception:
    pyautogui = None

try:
    import cv2
    import numpy as np
except Exception:
    cv2 = np = None

from logger import log_debug

DEEPSEEK_ENGINE='deepseek_api'
DEEPSEEK_LABEL='DeepSeek'
DEFAULT_BASE='https://api.deepseek.com/v1'
DEFAULT_MODEL='deepseek-v4-flash'
INSTALL_MARKER='__REALTIME_DEEPSEEK_PS4_INSTALLED__'


def _get(app,name,default=''):
    v=getattr(app,name,None)
    if v is None:
        return default
    try:
        return v.get()
    except Exception:
        return v


def _norm(text):
    return re.sub(r'\s+',' ',str(text or '')).strip()


def _clean_base(url):
    url=(url or DEFAULT_BASE).strip().rstrip('/')
    for suffix in ('/chat/completions','/models'):
        if url.lower().endswith(suffix):
            url=url[:-len(suffix)].rstrip('/')
    return url or DEFAULT_BASE


def _valid_ocr(text):
    text=_norm(text)
    if len(text)<2:
        return False
    if text.lower() in {'source text','translation','loading','translating','ocr source'}:
        return False
    letters=sum(c.isalpha() for c in text)
    digits=sum(c.isdigit() for c in text)
    if letters==0 and digits<2:
        return False
    if len(text)>=8:
        punctuation=sum(not c.isalnum() and not c.isspace() for c in text)
        if punctuation>len(text)*0.65:
            return False
    return True


def _argos_draft(text,src,tgt):
    if not _ARGOS_OK:
        return ''
    try:
        langs=_argos_translate.get_installed_languages()
        sl=next((x for x in langs if getattr(x,'code','').lower()==str(src).lower()),None)
        tl=next((x for x in langs if getattr(x,'code','').lower()==str(tgt).lower()),None)
        if not sl or not tl:
            return ''
        tr=sl.get_translation(tl)
        if not tr:
            return ''
        out=tr.translate(text)
        return str(out).strip() if out else ''
    except Exception as exc:
        log_debug(f'REALTIME Argos draft skipped: {type(exc).__name__}: {exc}')
        return ''


def _strip_prefix(text):
    out=str(text or '').strip()
    for prefix in ('FA:','PERSIAN:','Persian:','Translation:','TRANSLATION:'):
        if out.startswith(prefix):
            return out[len(prefix):].strip()
    return out


def _deepseek_translate(app,text,generation=None):
    """Call current DeepSeek Chat Completions API and stream deltas to the box."""
    key=str(_get(app,'deepseek_api_key_var','') or '').strip()
    if not key:
        return 'DeepSeek API error: API key is empty'
    base=_clean_base(str(_get(app,'deepseek_base_url_var',DEFAULT_BASE)))
    model=str(_get(app,'deepseek_model_var',DEFAULT_MODEL) or DEFAULT_MODEL).strip()
    src=str(_get(app,'deepseek_source_lang_var','en') or 'en').strip()
    tgt=str(_get(app,'deepseek_target_lang_var','fa') or 'fa').strip()
    system=(f'Translate game dialogue from {src} to {tgt}. '
            'Return ONLY the translation. Preserve names, numbers, punctuation, variables, '
            'HTML tags, placeholders, and line breaks. Do not explain anything.')
    body={
        'model':model,
        'messages':[{'role':'system','content':system},{'role':'user','content':str(text)}],
        'temperature':0.0,
        'max_tokens':256,
        'stream':True,
    }
    req=urllib.request.Request(
        base+'/chat/completions',
        data=json.dumps(body,ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type':'application/json','Authorization':f'Bearer {key}',
                 'User-Agent':'Game-Changing-Translator-Realtime/1.1'},
        method='POST')
    try:
        with urllib.request.urlopen(req,timeout=8.0) as resp:
            accumulated=''
            for raw_line in resp:
                line=raw_line.decode('utf-8','replace').strip()
                if not line or not line.startswith('data:'):
                    continue
                payload=line[5:].strip()
                if payload=='[DONE]':
                    break
                try:data=json.loads(payload)
                except Exception:continue
                choices=data.get('choices') or []
                if not choices:continue
                delta=(choices[0].get('delta') or {})
                piece=delta.get('content') or ''
                if isinstance(piece,str) and piece:
                    accumulated += piece
                    current=_strip_prefix(accumulated)
                    if generation is None or generation==getattr(app,'_rt_text_generation',generation):
                        _display(app,current)
            result=_strip_prefix(accumulated)
        return result if result else 'DeepSeek API error: empty response'
    except urllib.error.HTTPError as exc:
        try: detail=exc.read().decode('utf-8','replace')[:500]
        except Exception: detail=str(exc)
        return f'DeepSeek API error: HTTP {exc.code} {detail}'
    except Exception as exc:
        return f'DeepSeek API error: {type(exc).__name__}: {exc}'


def _source_target(app):
    engine=str(_get(app,'translation_model_var','')).strip()
    if engine==DEEPSEEK_ENGINE:
        return (str(_get(app,'deepseek_source_lang_var','en') or 'en'),
                str(_get(app,'deepseek_target_lang_var','fa') or 'fa'))
    if engine=='gemini_api':
        return getattr(app,'gemini_source_lang','en'),getattr(app,'gemini_target_lang','fa')
    try:
        if app.is_openai_model(engine):
            return getattr(app,'openai_source_lang','en'),getattr(app,'openai_target_lang','fa')
    except Exception:
        pass
    return str(_get(app,'source_lang_var','en') or 'en'),str(_get(app,'target_lang_var','fa') or 'fa')


def _display(app,text):
    try:
        if app.root.winfo_exists():
            app.root.after(0,app.update_translation_text,str(text))
    except Exception as exc:
        log_debug(f'REALTIME display error: {type(exc).__name__}: {exc}')


def _queue_latest(q,item):
    try:
        while True:
            q.get_nowait()
            try:q.task_done()
            except Exception:pass
    except Exception:
        pass
    try:
        q.put_nowait(item)
        return True
    except Exception:
        return False


def _capture(app):
    overlay=getattr(app,'source_overlay',None)
    if overlay is None:
        return None
    try:
        x1,y1,x2,y2=map(int,overlay.get_geometry())
        if x2<=x1 or y2<=y1:
            return None
        if ImageGrab is not None:
            return ImageGrab.grab(bbox=(x1,y1,x2,y2),all_screens=True)
        if pyautogui is not None:
            return pyautogui.screenshot(region=(x1,y1,x2-x1,y2-y1))
    except Exception as exc:
        log_debug(f'REALTIME capture error: {type(exc).__name__}: {exc}')
    return None


def run_realtime_capture(app):
    log_debug('REALTIME: latest-frame capture started.')
    last_hash=None
    while getattr(app,'is_running',False):
        try:
            img=_capture(app)
            if img is not None:
                try:
                    small=img.resize((max(1,img.width//4),max(1,img.height//4)))
                    h=hashlib.md5(small.tobytes()).hexdigest()
                except Exception:
                    h=None
                if h!=last_hash:
                    last_hash=h
                    app._rt_frame_seq=getattr(app,'_rt_frame_seq',0)+1
                    app._rt_latest_frame=img
                    app.last_screenshot=img
                    _queue_latest(app.ocr_queue,(app._rt_frame_seq,img))
            interval=int(getattr(app,'current_scan_interval',100) or 100)
            time.sleep(max(0.05,interval/1000.0))
        except Exception as exc:
            log_debug(f'REALTIME capture loop error: {type(exc).__name__}: {exc}\n{traceback.format_exc()}')
            time.sleep(0.08)
    log_debug('REALTIME: latest-frame capture stopped.')


def _tesseract(app,img):
    if cv2 is None or np is None:
        return ''
    from ocr_utils import preprocess_for_ocr,get_tesseract_model_params,ocr_region_with_confidence,post_process_ocr_text_general
    try:
        arr=np.array(img)
        if len(arr.shape)==3 and arr.shape[2]==4:
            bgr=cv2.cvtColor(arr,cv2.COLOR_RGBA2BGR)
        elif len(arr.shape)==3:
            bgr=cv2.cvtColor(arr,cv2.COLOR_RGB2BGR)
        else:
            bgr=cv2.cvtColor(arr,cv2.COLOR_GRAY2BGR)
        mode=str(_get(app,'preprocessing_mode_var','none'))
        block=int(_get(app,'adaptive_block_size_var',41) or 41)
        c=int(_get(app,'adaptive_c_var',-60) or -60)
        processed=preprocess_for_ocr(bgr,mode,block,c)
        app.last_processed_image=processed
        langs=app.get_tesseract_lang_code()
        model=mode if mode in ('gaming','document','subtitle') else 'general'
        params=get_tesseract_model_params(model)
        region=(0,0,processed.shape[1],processed.shape[0])
        raw=ocr_region_with_confidence(processed,region,langs,params,int(_get(app,'confidence_var',60) or 60))
        txt=post_process_ocr_text_general(raw,langs)
        if bool(_get(app,'keep_linebreaks_var',False)):
            txt=txt.replace('\n','<br>')
        else:
            txt=txt.replace('\n',' ')
        return _norm(txt)
    except Exception as exc:
        log_debug(f'REALTIME Tesseract error: {type(exc).__name__}: {exc}')
        return ''


def _start_translation(app,text,frame_seq):
    text=_norm(text)
    if not _valid_ocr(text):
        return
    app._rt_latest_text=text
    app._rt_last_text_at=time.monotonic()
    app._rt_text_generation=getattr(app,'_rt_text_generation',0)+1
    generation=app._rt_text_generation
    app.last_processed_subtitle=text
    if getattr(app,'_rt_translation_inflight',False):
        app._rt_translation_pending=(generation,text,frame_seq)
        return
    app._rt_translation_inflight=True
    app._rt_translation_pending=None
    app.translation_thread_pool.submit(_translate_job,app,text,generation,frame_seq)


def _translate_job(app,text,generation,frame_seq):
    started=time.monotonic()
    try:
        src,tgt=_source_target(app)
        engine=str(_get(app,'translation_model_var','')).strip()
        draft=''
        if engine==DEEPSEEK_ENGINE:
            draft=_argos_draft(text,src,tgt)
            if draft and generation==getattr(app,'_rt_text_generation',generation):
                _display(app,draft)
            result=_deepseek_translate(app,text,generation)
        else:
            result=app.translation_handler.translate_text_with_timeout(text,timeout_seconds=8.0,ocr_batch_number=frame_seq)
        if generation==getattr(app,'_rt_text_generation',generation):
            if result and not str(result).startswith('DeepSeek API error:'):
                try:
                    from translation_utils import post_process_translation_text
                    result=post_process_translation_text(result)
                except Exception:
                    pass
                _display(app,result)
            elif engine==DEEPSEEK_ENGINE and draft:
                _display(app,draft)
            elif result:
                _display(app,result)
        log_debug(f'REALTIME translation generation {generation} finished in {time.monotonic()-started:.3f}s')
    except Exception as exc:
        log_debug(f'REALTIME translation error: {type(exc).__name__}: {exc}')
    finally:
        app._rt_translation_inflight=False
        pending=getattr(app,'_rt_translation_pending',None)
        app._rt_translation_pending=None
        if getattr(app,'is_running',False) and pending:
            gen2,text2,seq2=pending
            if gen2==getattr(app,'_rt_text_generation',gen2):
                app._rt_translation_inflight=True
                app.translation_thread_pool.submit(_translate_job,app,text2,gen2,seq2)


def _api_ocr_job(app,seq,img):
    try:
        data=app.convert_to_webp_for_api(img)
        if not data:return
        src,_=_source_target(app)
        result=app.translation_handler.perform_ocr(data,src)
        if not getattr(app,'is_running',False):return
        txt=_norm(result)
        if txt and txt.upper()!='<EMPTY>' and _valid_ocr(txt):
            app.root.after(0,_start_translation,app,txt,seq)
    except Exception as exc:
        log_debug(f'REALTIME API OCR error: {type(exc).__name__}: {exc}')
    finally:
        app._rt_ocr_inflight=False
        latest=getattr(app,'_rt_frame_seq',0)
        if getattr(app,'is_running',False) and latest>seq:
            latest_img=getattr(app,'_rt_latest_frame',None)
            if latest_img is not None:
                app._rt_ocr_inflight=True
                app.ocr_thread_pool.submit(_api_ocr_job,app,latest,latest_img)


def run_realtime_ocr(app):
    log_debug('REALTIME: latest-only OCR started.')
    last_text=''
    while getattr(app,'is_running',False):
        try:
            try:item=app.ocr_queue.get(timeout=0.15)
            except Exception:continue
            if isinstance(item,tuple) and len(item)==2:
                seq,img=item
            else:
                seq,img=getattr(app,'_rt_frame_seq',0),item
            newest=item
            try:
                while True:newest=app.ocr_queue.get_nowait()
            except Exception:pass
            if isinstance(newest,tuple) and len(newest)==2:
                seq,img=newest
            app.last_screenshot=img
            if app.is_api_based_ocr_model(app.get_ocr_model_setting()):
                if not getattr(app,'_rt_ocr_inflight',False):
                    app._rt_ocr_inflight=True
                    app.ocr_thread_pool.submit(_api_ocr_job,app,seq,img)
                continue
            txt=_tesseract(app,img)
            if not txt or app.is_placeholder_text(txt):
                continue
            if txt!=last_text:
                last_text=txt
                app.root.after(0,_start_translation,app,txt,seq)
        except Exception as exc:
            log_debug(f'REALTIME OCR loop error: {type(exc).__name__}: {exc}\n{traceback.format_exc()}')
            time.sleep(0.06)
    log_debug('REALTIME: latest-only OCR stopped.')


def run_realtime_maintenance(app):
    while getattr(app,'is_running',False):
        try:
            time.sleep(0.15)
        except Exception:
            time.sleep(0.15)


def _save_ds(app,name,key):
    try:
        app.config['Settings'][key]=str(getattr(app,name).get())
        try:
            from config_manager import save_app_config
            save_app_config(app.config)
        except Exception:
            if getattr(app,'_fully_initialized',False):app.save_settings()
    except Exception as exc:
        log_debug(f'REALTIME setting save error: {type(exc).__name__}: {exc}')


def _install_ds_vars(app):
    import tkinter as tk
    try:cfg=app.config['Settings']
    except Exception:cfg={}
    def val(k,d):
        try:return cfg.get(k,d)
        except Exception:return d
    specs=(
        ('deepseek_api_key_var','deepseek_api_key',''),
        ('deepseek_base_url_var','deepseek_base_url',DEFAULT_BASE),
        ('deepseek_model_var','deepseek_model',DEFAULT_MODEL),
        ('deepseek_source_lang_var','deepseek_source_lang','en'),
        ('deepseek_target_lang_var','deepseek_target_lang','fa'),
    )
    for name,key,default in specs:
        if not hasattr(app,name):
            setattr(app,name,tk.StringVar(value=val(key,default)))
        try:getattr(app,name).trace_add('write',lambda *_a,_n=name,_k=key:_save_ds(app,_n,_k))
        except Exception:pass


def _deepseek_selection(app,event=None):
    try:
        if str(app.translation_model_display_var.get()).strip()!=DEEPSEEK_LABEL:return
        app.translation_model_var.set(DEEPSEEK_ENGINE)
        app.source_lang_var.set(app.deepseek_source_lang_var.get())
        app.target_lang_var.set(app.deepseek_target_lang_var.get())
        app.last_successful_translation_time=0.0
        app._rt_latest_text=''
        try:app.save_settings()
        except Exception:pass
    except Exception as exc:
        log_debug(f'REALTIME DeepSeek selection error: {type(exc).__name__}: {exc}')


def _install_ds_model_ui(app):
    try:
        app.translation_model_names.setdefault(DEEPSEEK_ENGINE,DEEPSEEK_LABEL)
        app.translation_model_values={v:k for k,v in app.translation_model_names.items()}
        combo=getattr(app,'translation_model_combobox',None)
        if combo is None:return
        vals=list(combo.cget('values'))
        if DEEPSEEK_LABEL not in vals:
            vals.append(DEEPSEEK_LABEL)
            combo.configure(values=vals)
        if app.translation_model_var.get()==DEEPSEEK_ENGINE:
            app.translation_model_display_var.set(DEEPSEEK_LABEL)
        combo.bind('<<ComboboxSelected>>',lambda e:_deepseek_selection(app,e),add='+')
    except Exception as exc:
        log_debug(f'REALTIME DeepSeek model UI error: {type(exc).__name__}: {exc}')


def _test_ds(app):
    def job():
        result=_deepseek_translate(app,'Hello')
        def done():
            try:
                from tkinter import messagebox
                if result.startswith('DeepSeek API error:'):
                    messagebox.showerror('DeepSeek Test',result,parent=app.root)
                else:
                    messagebox.showinfo('DeepSeek Test','Connection OK\n\n'+result,parent=app.root)
            except Exception as exc:log_debug(f'REALTIME test dialog error: {exc}')
        try:app.root.after(0,done)
        except Exception:done()
    threading.Thread(target=job,name='DeepSeekTest',daemon=True).start()


def _install_ds_settings_ui(app):
    from tkinter import ttk
    try:
        parent=getattr(app,'tab_settings',None)
        if parent is None:return
        if getattr(app,'_rt_ds_frame',None) is not None and app._rt_ds_frame.winfo_exists():return
        frame=ttk.LabelFrame(parent,text='DeepSeek / Realtime Translation')
        frame.pack(fill='x',padx=10,pady=(4,12))
        frame.columnconfigure(1,weight=1)
        app._rt_ds_frame=frame
        ttk.Label(frame,text='API Key').grid(row=0,column=0,sticky='w',padx=6,pady=4)
        ttk.Entry(frame,textvariable=app.deepseek_api_key_var,show='*').grid(row=0,column=1,columnspan=2,sticky='ew',padx=6,pady=4)
        ttk.Label(frame,text='Base URL').grid(row=1,column=0,sticky='w',padx=6,pady=4)
        ttk.Entry(frame,textvariable=app.deepseek_base_url_var).grid(row=1,column=1,columnspan=2,sticky='ew',padx=6,pady=4)
        ttk.Label(frame,text='Model').grid(row=2,column=0,sticky='w',padx=6,pady=4)
        ttk.Entry(frame,textvariable=app.deepseek_model_var).grid(row=2,column=1,columnspan=2,sticky='ew',padx=6,pady=4)
        ttk.Label(frame,text='Source → Target').grid(row=3,column=0,sticky='w',padx=6,pady=4)
        pair=ttk.Frame(frame);pair.grid(row=3,column=1,sticky='w',padx=6,pady=4)
        ttk.Entry(pair,textvariable=app.deepseek_source_lang_var,width=8).pack(side='left')
        ttk.Label(pair,text='  →  ').pack(side='left')
        ttk.Entry(pair,textvariable=app.deepseek_target_lang_var,width=8).pack(side='left')
        ttk.Button(frame,text='Test',command=lambda:_test_ds(app)).grid(row=3,column=2,padx=6,pady=4)
        ttk.Label(frame,text='Latest-only realtime • Argos draft first when en→fa is installed').grid(row=4,column=0,columnspan=3,sticky='w',padx=6,pady=(2,6))
    except Exception as exc:
        log_debug(f'REALTIME settings UI error: {type(exc).__name__}: {exc}')


def _install_ps4_header(app):
    import tkinter as tk
    try:
        root=app.root
        if getattr(app,'_rt_ps4_header',None) is not None and app._rt_ps4_header.winfo_exists():return
        root.configure(bg='#07142f')
        try:
            root.geometry('760x620');root.minsize(620,520)
        except Exception:pass
        nb=getattr(app,'tab_control',None)
        if nb is None:return
        try:nb.pack_forget()
        except Exception:pass
        header=tk.Canvas(root,height=64,bg='#0b1d46',highlightthickness=0,bd=0)
        header.pack(fill='x',side='top')
        app._rt_ps4_header=header
        header.create_text(18,21,anchor='w',text='GAME-CHANGING TRANSLATOR',fill='#ffffff',font=('Segoe UI',13,'bold'))
        header.create_text(18,43,anchor='w',text='REALTIME  •  DEEPSEEK  •  LATEST TEXT',fill='#79a8ff',font=('Segoe UI',8,'bold'))
        w=max(760,root.winfo_width())
        p1=[];p2=[]
        for x in range(0,w+100,18):
            p1.extend((x,58-10*(1+math.sin(x/88))))
            p2.extend((x,60-6*(1+math.sin(x/120+1.2))))
        header.create_line(*p1,fill='#18366f',width=2,smooth=True)
        header.create_line(*p2,fill='#2358a5',width=1,smooth=True)
        nb.pack(expand=True,fill='both',padx=5,pady=5)
    except Exception as exc:
        log_debug(f'REALTIME PS4 header error: {type(exc).__name__}: {exc}')


def _install_ui_rebuild_hook(app):
    """Re-add DeepSeek controls after the app's existing language/UI rebuild."""
    original=getattr(app,'update_ui_language',None)
    if original is None or getattr(app,'_rt_ui_rebuild_wrapped',False):
        return
    def wrapped(self,*args,**kwargs):
        result=original(*args,**kwargs)
        try:
            self.root.after_idle(lambda: (_install_ds_model_ui(self),_install_ds_settings_ui(self)))
        except Exception:
            pass
        return result
    app.update_ui_language=MethodType(wrapped,app)
    app._rt_ui_rebuild_wrapped=True


def _install_workers(app):
    import app_logic
    app._rt_frame_seq=0
    app._rt_latest_frame=None
    app._rt_latest_text=''
    app._rt_last_text_at=time.monotonic()
    app._rt_text_generation=0
    app._rt_translation_inflight=False
    app._rt_translation_pending=None
    app._rt_ocr_inflight=False
    app_logic.run_capture_thread=run_realtime_capture
    app_logic.run_ocr_thread=run_realtime_ocr
    app_logic.run_translation_thread=run_realtime_maintenance


def install_realtime_deepseek(app):
    if getattr(app,INSTALL_MARKER,False):return
    setattr(app,INSTALL_MARKER,True)
    try:
        _install_ds_vars(app)
        app.deepseek_translate=MethodType(lambda self,text:_deepseek_translate(self,text),app)
        _install_ds_model_ui(app)
        _install_ds_settings_ui(app)
        _install_ui_rebuild_hook(app)
        _install_ps4_header(app)
        _install_workers(app)
        log_debug('REALTIME DEEPSEEK PS4 installed; existing features preserved.')
    except Exception as exc:
        log_debug(f'REALTIME DEEPSEEK PS4 install error: {type(exc).__name__}: {exc}\n{traceback.format_exc()}')
