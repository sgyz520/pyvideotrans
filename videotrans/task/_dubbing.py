import copy
import json
import re
import shutil
import time

from videotrans.configure import config


from videotrans.task._base import BaseTask
from videotrans.task._rate import SpeedRate
from videotrans import tts
from videotrans.util import tools

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any


"""
仅字幕翻译
"""


@dataclass
class DubbingSrt(BaseTask):
    # ==================================================================
    # 1. 覆盖父类的字段，并定义本类独有的状态属性。
    #    这些属性都将在 __post_init__ 中根据逻辑被赋值，因此设为 init=False。
    # ==================================================================


    # 这两个属性依赖于 cfg，所以它们没有默认值，在 post_init 中设置。
    is_multi_role: bool = field(init=False)
    rename: bool = field(init=False)
    # 在这个子类中，shoud_dubbing 总是 True，所以我们直接覆盖父类的默认值。
    shoud_dubbing: bool = field(default=True, init=False)


    # ==================================================================
    # 2. 将 __init__ 的所有逻辑移到 __post_init__ 方法中。
    # ==================================================================
    def __post_init__(self):
        # 关键第一步：调用父类的 __post_init__。
        # 这会确保 self.cfg 被正确地合并(cfg+obj)并且 self.uuid 被设置。
        super().__post_init__()

        # --- 从这里开始，是您旧 __init__ 的所有剩余逻辑，几乎原封不动 ---

        # 1. 初始化本类的状态属性
        #    此时 self.cfg 已经是完全准备好的了
        self.is_multi_role = self.cfg.get('is_multi_role', False)
        self.rename = self.cfg.get('rename', False)
        # self.shoud_dubbing 已经被上面的 field 定义处理了，无需再写

        # 2. 处理路径和配置
        if 'target_dir' not in self.cfg or not self.cfg['target_dir']:
            self.cfg['target_dir'] = f"{config.HOME_DIR}/tts"

        # 3. 执行副作用（创建文件夹等）
        Path(self.cfg['target_dir']).mkdir(parents=True, exist_ok=True)
        # 假设 self.cfg 中一定有 'cache_folder'，这与您的原始代码行为一致
        if self.cfg.get('cache_folder'):
            Path(self.cfg["cache_folder"]).mkdir(parents=True, exist_ok=True)

        # 4. 计算并更新 self.cfg
        self.cfg['target_sub'] = self.cfg['name']
        # 假设 self.cfg 中有 'noextname' 和 'out_ext'
        self.cfg['target_wav'] = f'{self.cfg["target_dir"]}/{self.cfg["noextname"]}.{self.cfg["out_ext"]}'

        # 5. 调用方法
        self._signal(text='字幕配音处理中' if config.defaulelang == 'zh' else ' Dubbing from subtitles ')


    def prepare(self):
        if self._exit():
            return

    def recogn(self):
        pass

    def trans(self):
        pass

    def dubbing(self):
        try:
            self._signal(text=Path(self.cfg['target_sub']).read_text(encoding='utf-8'), type="replace")
            self._tts()
        except Exception as e:
            self.hasend = True
            tools.send_notification(str(e), f'{self.cfg["basename"]}')
            raise

    # 配音预处理，去掉无效字符，整理开始时间
    def _tts(self) -> None:
        queue_tts = []
        # 获取字幕
        try:
            rate = int(str(self.cfg['voice_rate']).replace('%', ''))
        except:
            rate=0
        if rate >= 0:
            rate = f"+{rate}%"
        else:
            rate = f"{rate}%"
        
        if self.cfg['target_sub'].endswith('.txt') and self.cfg['tts_type']==tts.EDGE_TTS:
            from edge_tts import Communicate
            import asyncio
            pro=self._set_proxy(type='set')
            async def _async_dubb():
                communicate_task = Communicate(
                    text=Path(self.cfg['target_sub']).read_text(encoding='utf-8'), 
                    voice=self.cfg['voice_role'], 
                    rate=rate, 
                    volume=self.cfg['volume'],
                    proxy=pro if pro else None,
                    pitch=self.cfg['pitch']
                )
                tmp_name=self.cfg['target_wav'] if self.cfg["target_wav"].endswith('.mp3') else f"{self.cfg['cache_folder']}/{self.cfg['noextname']}-edgetts-txt-{time.time()}.mp3"
                await communicate_task.save(tmp_name)
                
                if not self.cfg["target_wav"].endswith('.mp3'):
                    tools.runffmpeg(['-y','-i',tmp_name,'-b:a','192k',self.cfg['target_wav']])
                
            asyncio.run(_async_dubb())
            return

        if self.cfg['target_sub'].endswith('.txt'):
            text=Path(self.cfg['target_sub']).read_text(encoding='utf-8').strip()
            text=re.sub(r"(\s*?\r?\n\s*?){2,}","\n",text)
            text=re.sub(r"(\s*?\r?\n\s*?)","\n",text)
            subs=[{
                "line":1,
                "start_time":0,
                "end_time":1000,
                "startraw":"00:00:00,000",
                "endraw":"00:00:01,000",
                "text":text
            }]
        else:
            try:
                subs = tools.get_subtitle_from_srt(self.cfg['target_sub'])
            except Exception as e:
                raise

        # 取出每一条字幕，行号\n开始时间 --> 结束时间\n内容
        for i, it in enumerate(subs):
            if it['end_time'] <= it['start_time']:
                continue
            spec_role=config.dubbing_role.get(int(it['line'])) if self.is_multi_role else  None
            voice_role = spec_role if spec_role else self.cfg['voice_role']
            
            # 要保存到的文件
            filename_md5=tools.get_md5(f"{self.cfg['tts_type']}-{it['start_time']}-{it['end_time']}-{voice_role}-{rate}-{self.cfg['volume']}-{self.cfg['pitch']}-{len(it['text'])}-{i}")
            tmp_dict= {
                        "line":it['line'],
                        "text": it['text'],
                       "role": voice_role,
                       "start_time": it['start_time'],
                       "end_time": it['end_time'],
                       "rate": rate,
                       "startraw": it['startraw'],
                       "endraw": it['endraw'],
                       "volume": self.cfg['volume'],
                       "pitch": self.cfg['pitch'],
                       "tts_type": int(self.cfg['tts_type']),
                       "filename": config.TEMP_DIR + f"/dubbing_cache/{filename_md5}.mp3"}
            queue_tts.append(tmp_dict)
        Path(config.TEMP_DIR + "/dubbing_cache").mkdir(parents=True,exist_ok=True)
        self.queue_tts = queue_tts
        if not self.queue_tts or len(self.queue_tts) < 1:
            raise Exception(f'Queue tts length is 0')
        # 具体配音操作
        tts.run(
            queue_tts=copy.deepcopy(self.queue_tts),
            language=self.cfg['target_language_code'],
            uuid=self.uuid
        )
        if config.settings.get('save_segment_audio',False):
            outname=self.cfg['target_dir']+f'/segment_audio_{self.cfg["noextname"]}'

            Path(outname).mkdir(parents=True, exist_ok=True)
            for it in self.queue_tts:
                if Path(it['filename']).exists():
                    text=re.sub(r'["\'*?\\/\|:<>\r\n\t]+','',it['text'])
                    name= f'{outname}/{it["start_time"]}-{text[:60]}.mp3'
                    shutil.copy2(it['filename'],name)

    def align(self) -> None:
        if self.cfg['target_sub'].endswith('.txt') or len(self.queue_tts)==1:
            if self.cfg['tts_type'] !=tts.EDGE_TTS:
                tools.runffmpeg(['-y','-i',self.queue_tts[0]['filename'],'-b:a','128k',self.cfg['target_wav']])        
            return
            
        if self.cfg['voice_autorate']:
            self._signal(text='变速对齐阶段' if config.defaulelang == 'zh' else 'Sound & video speed alignment stage')
        try:
            target_path=Path(self.cfg['target_wav'])
            if target_path.is_file() and target_path.stat().st_size > 0:
                self.cfg['target_wav']=self.cfg['target_wav'][:-4]+f'-{time.time()}{target_path.suffix}'
            rate_inst = SpeedRate(
                queue_tts=self.queue_tts,
                uuid=self.uuid,
                shoud_audiorate=self.cfg['voice_autorate'],
                raw_total_time=self.queue_tts[-1]['end_time'],
                noextname=self.cfg['noextname'],
                target_audio=self.cfg['target_wav'],
                cache_folder=self.cfg['cache_folder']
            )
            volume=self.cfg['volume'].strip()

            if volume !='+0%':
                try:
                    volume=1+float(volume)/100
                    tmp_name=self.cfg['cache_folder']+f'/volume-{volume}-{Path(self.cfg["target_wav"]).name}'
                    tools.runffmpeg(['-y','-i',self.cfg['target_wav'],'-af',f"volume={volume}",tmp_name])
                except:
                    pass
            self.queue_tts = rate_inst.run()
        except Exception as e:
            self.hasend = True
            tools.send_notification(str(e), f'{self.cfg["basename"]}')
            raise

    def task_done(self):
        if self._exit():
            return
        self.hasend = True
        self.precent = 100
        if Path(self.cfg['target_wav']).is_file():
            if not self.cfg['target_sub'].endswith('.txt'): 
                tools.remove_silence_from_end(self.cfg['target_wav'],is_start=False)
            
            self._signal(text=f"{self.cfg['name']}", type='succeed')
            tools.send_notification(config.transobj['Succeed'], f"{self.cfg['basename']}")
        if 'shound_del_name' in self.cfg:
            Path(self.cfg['shound_del_name']).unlink(missing_ok=True)

    def _exit(self):
        if config.exit_soft or config.box_tts!='ing':
            return True
        return False
