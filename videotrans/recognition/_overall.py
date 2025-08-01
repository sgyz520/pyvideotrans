import multiprocessing
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, ClassVar,Union
import zhconv

from videotrans.configure import config
from videotrans.process._overall import run
from videotrans.recognition._base import BaseRecogn
from videotrans.util import tools


@dataclass
class FasterAll(BaseRecogn):
    raws: List = field(default_factory=list, init=False)
    pidfile: str = field(default="", init=False)

    def __post_init__(self):
        super().__post_init__()

        if self.detect_language and self.detect_language[:2].lower() in ['zh', 'ja', 'ko', 'yu']:
            self.flag.append(" ")
            self.maxlen = int(config.settings.get('cjk_len', 20)) # 使用 .get 更安全
        else:
            self.maxlen = int(config.settings.get('other_len', 60)) # 使用 .get 更安全

    # 获取新进程的结果
    def _get_signal_from_process(self, q: multiprocessing.Queue):
        while not self.has_done:
            try:
                if self._exit() and self.pidfile and Path(self.pidfile).exists():
                    Path(self.pidfile).unlink(missing_ok=True)
                    return
                if not q.empty():
                    data = q.get_nowait()
                    if self.inst and self.inst.precent < 50:
                        self.inst.precent += 0.1

                    if data:
                        if self.inst and self.inst.status_text and data['type']=='log':
                            self.inst.status_text=data['text']
                        self._signal(text=data['text'], type=data['type'])
            except Exception as e:
                print(e)
            time.sleep(0.2)

    def get_srtlist(self,raws):
        jianfan=config.settings.get('zh_hant_s')
        for i in list(raws):
            if len(i['words'])<1:
                continue
            tmp={
                'text':zhconv.convert(i['text'], 'zh-hans') if jianfan and self.detect_language[:2]=='zh' else i['text'],
                'start_time':int(i['words'][0]['start']*1000),
                'end_time':int(i['words'][-1]['end']*1000)
            }
            tmp['startraw']=tools.ms_to_time_string(ms=tmp['start_time'])
            tmp['endraw']=tools.ms_to_time_string(ms=tmp['end_time'])
            tmp['time']=f"{tmp['startraw']} --> {tmp['endraw']}"
            self.raws.append(tmp)

    def _exec(self):
        # 修复CUDA fork问题：强制使用spawn方法
        try:
            multiprocessing.set_start_method('spawn', force=True)
        except RuntimeError:
            pass

        while 1:
            if self._exit() and self.pidfile:
                Path(self.pidfile).unlink(missing_ok=True)
                return
            if config.model_process is not None:
                import glob
                if len(glob.glob(config.TEMP_DIR+'/*.lock'))==0:
                    config.model_process=None
                    break
                self._signal(text="等待另外进程退出")
                time.sleep(1)
                continue
            break

        ctx = multiprocessing.get_context('spawn')
        # 创建队列用于在进程间传递结果
        result_queue = ctx.Queue()
        try:
            self.has_done = False
            threading.Thread(target=self._get_signal_from_process, args=(result_queue,)).start()
            self.error=''
            with ctx.Manager() as manager:
                raws = manager.list([])
                err = manager.dict({"msg": ""})
                detect=manager.dict({"langcode":self.detect_language})
                # 创建并启动新进程
                process = ctx.Process(target=run, args=(raws, err,detect), kwargs={
                    "model_name": self.model_name,
                    "is_cuda": self.is_cuda,
                    "detect_language": self.detect_language,
                    "audio_file": self.audio_file,
                    "q": result_queue,
                    "settings": config.settings,
                    "defaulelang": config.defaulelang,
                    "ROOT_DIR": config.ROOT_DIR,
                    "TEMP_DIR": config.TEMP_DIR,
                    "proxy":tools.set_proxy()
                })
                process.start()
                self.pidfile = config.TEMP_DIR + f'/{process.pid}.lock'
                config.logger.info(f'开始创建 pid:{self.pidfile=}')
                with open(self.pidfile,'w', encoding='utf-8') as f:
                    f.write(f'{process.pid}')
                # 等待进程执行完毕
                process.join()
                if err['msg']:
                    self.error = 'err[msg]='+str(err['msg'])
                elif len(list(raws))<1:
                    self.error = "没有识别到任何说话声" if config.defaulelang=='zh' else "No speech detected"
                else:
                    self.error=''
                    if self.detect_language=='auto' and self.inst and  hasattr(self.inst,'set_source_language'):
                        config.logger.info(f'需要自动检测语言，当前检测出的语言为{detect["langcode"]=}')
                        self.detect_language=detect['langcode']

                    if not config.settings['rephrase']:
                        self.get_srtlist(raws)
                    else:
                        try:
                            words_list=[]
                            for it in list(raws):
                                words_list+=it['words']
                            self._signal(text="正在重新断句..." if config.defaulelang=='zh' else "Re-segmenting...")
                            self.raws=self.re_segment_sentences(words_list,self.detect_language[:2])
                        except Exception as e:
                            self.get_srtlist(raws)
                try:
                    if process.is_alive():
                        process.terminate()
                except:
                    pass
        except (LookupError,ValueError,AttributeError,ArithmeticError) as e:
            config.logger.exception(f'lookup:{e}', exc_info=True)
            self.error=str(e)
        except Exception as e:
            self.error=f"_overall:{e}"
        finally:
            config.model_process = None
            self.has_done = True
            Path(self.pidfile).unlink(missing_ok=True)

        if self.error:
            raise Exception(self.error)
        if len(self.raws)<1:
            raise Exception('未识别到有效文字' if config.defaulelang=='zh' else 'No speech detected')
        return self.raws