import multiprocessing
import os
import re
import time
from pathlib import Path



from faster_whisper import WhisperModel

from videotrans.util.tools import ms_to_time_string,cleartext

def run(raws, err,detect, *, model_name, is_cuda, detect_language, audio_file,
        q: multiprocessing.Queue, ROOT_DIR, TEMP_DIR, settings, defaulelang,proxy=None):
    os.chdir(ROOT_DIR)
    down_root = ROOT_DIR + "/models"
    settings['whisper_threads']=int(float(settings.get('whisper_threads',1)))
    def write_log(jsondata):
        try:
            q.put_nowait(jsondata)
        except:
            pass


    try:

        msg = f'[{model_name}]若不存在将从 hf-mirror.com 下载到 models 目录内' if defaulelang == 'zh' else f'If [{model_name}] not exists, download model from huggingface'
        write_log({"text": msg, "type": "logs"})
        if model_name.startswith('distil-'):
            com_type = "default"
        elif is_cuda:
            com_type = settings['cuda_com_type']
        else:
            com_type = settings['cuda_com_type']
        try:
            model = WhisperModel(
                model_name,
                device="cuda" if is_cuda else "cpu",
                compute_type=com_type,
                download_root=down_root
            )
        except Exception as e:
            if re.match(r'not support', str(e), re.I):
                # 如果所选数据类型不支持，则使用默认
                model = WhisperModel(
                    model_name,
                    device="cuda" if is_cuda else "cpu",
                    download_root=down_root
                )
            else:
                err['msg'] = str(e)
                return
        write_log({"text": model_name+" Loaded", "type": "logs"})
        prompt = settings.get(f'initial_prompt_{detect_language}') if detect_language!='auto' else None
        segments, info = model.transcribe(
            audio_file,
            beam_size=int(settings['beam_size']),
            best_of=int(settings['best_of']),
            condition_on_previous_text=bool(settings['condition_on_previous_text']),
            temperature=0.0 if float(settings.get('temperature',0)) == 0.0 else [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            vad_filter=bool(settings['vad']),
            vad_parameters=dict(
                threshold=float(settings['threshold']),
                min_speech_duration_ms=int(settings['min_speech_duration_ms']),
                max_speech_duration_s= float(settings['max_speech_duration_s']) if float(settings['max_speech_duration_s'])>0 else float('inf'),
                min_silence_duration_ms=int(settings['min_silence_duration_ms']),
                speech_pad_ms=int(settings['speech_pad_ms'])
            ),
            word_timestamps=True,
            language=detect_language.split('-')[0] if detect_language!='auto' else None,
            initial_prompt=prompt if prompt else None
        )
        if detect_language=='auto' and info.language!=detect['langcode']:
            detect['langcode']='zh-cn' if info.language[:2]=='zh' else info.language
        nums=0
        for segment in segments:
            nums+=1
            if not Path(TEMP_DIR + f'/{os.getpid()}.lock').exists():
                return
            new_seg=[]
            for idx, word in enumerate(segment.words):
                new_seg.append({"start":word.start,"end":word.end,"word":word.word })
            text=cleartext(segment.text,remove_start_end=False)
            raws.append({"words":new_seg,"text":text})

            q.put_nowait({"text": f'{text}\n', "type": "subtitle"})
            q.put_nowait({"text": f' {"字幕" if defaulelang == "zh" else "Subtitles"} {len(raws) + 1} ', "type": "logs"})
    except (LookupError,ValueError,AttributeError,ArithmeticError) as e:
        err['msg']=f'{e}'
        if detect_language=='auto':
            err['msg']+='检测语言失败，请设置发声语言/Failed to detect language, please set the voice language'
    except BaseException as e:
        err['msg'] = '_process:'+str(e)
    finally:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except:
            pass
        time.sleep(2)
