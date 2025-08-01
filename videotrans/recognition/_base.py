import copy
import json
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, ClassVar,Union



from videotrans.configure import config
from videotrans.configure._base import BaseCon

from videotrans.util import tools


@dataclass
class BaseRecogn(BaseCon):

    detect_language: Optional[str] = None
    audio_file: Optional[str] = None
    cache_folder: Optional[str] = None
    model_name: Optional[str] = None
    inst: Optional[Any] = None
    uuid: Optional[str] = None
    is_cuda: Optional[bool] = None
    target_code: Optional[str] = None
    subtitle_type: int = 0


    has_done: bool = field(default=False, init=False)
    error: str = field(default='', init=False)
    api_url: str = field(default='', init=False)
    proxies: Optional = field(default=None, init=False)


    device: str = field(init=False)
    flag: List[str] = field(init=False)
    join_word_flag: str = field(init=False)
    jianfan: bool = field(init=False)
    maxlen: int = field(init=False)



    def __post_init__(self):
        super().__init__()
        self.device = 'cuda' if self.is_cuda else 'cpu'

        self.flag = [
            ",", ".", "?", "!", ";",
            "，", "。", "？", "；", "！"
        ]
        self.join_word_flag = " "


        if self.detect_language and self.detect_language[:2].lower() in ['zh', 'ja', 'ko']:
            self.maxlen = int(float(config.settings.get('cjk_len', 20)))
            self.jianfan = True if self.detect_language[:2] == 'zh' and config.settings.get('zh_hant_s') else False
        else:
            self.maxlen = int(float(config.settings.get('other_len', 60)))
            self.jianfan = False # 确保在所有分支中都初始化

        if not tools.vail_file(self.audio_file):
            raise Exception(f'[error]not exists {self.audio_file}')

    # 出错时发送停止信号
    def run(self) -> Union[List[Dict], None]:
        Path(config.TEMP_HOME).mkdir(parents=True, exist_ok=True)
        self._signal(text="")
        try:
            if self.detect_language[:2].lower() in ['zh', 'ja', 'ko']:
                self.flag.append(" ")
                self.join_word_flag = ""
            return self._exec()
        except Exception as e:
            config.logger.exception(e, exc_info=True)
            self._signal(text=str(e), type="error")
            raise
        finally:
            if self.shound_del:
                self._set_proxy(type='del')

    def _exec(self) -> Union[List[Dict], None]:
        pass

    def re_segment_sentences(self,words,langcode=None):
        
        try:
            from videotrans.translator._chatgpt import ChatGPT
            ob=ChatGPT()
            if self.inst and self.inst.status_text:
                self.inst.status_text="正在重新断句..." if config.defaulelang=='zh' else "Re-segmenting..."
            return ob.llm_segment(words,self.inst,config.settings.get('llm_ai_type','openai'))
        except json.decoder.JSONDecodeError as e:
            self.inst.status_text="使用LLM重新断句失败" if config.defaulelang=='zh' else "Re-segmenting Error"
            config.logger.error(f"使用ChatGPT重新断句失败[JSONDecodeError]，已恢复原样 {e}")
            raise
        except Exception as e:
            self.inst.status_text="使用LLM重新断句失败" if config.defaulelang=='zh' else "Re-segmenting Error"
            config.logger.error(f"使用ChatGPT重新断句失败[except]，已恢复原样 {e}")
            raise

    # True 退出
    def _exit(self) -> bool:
        if config.exit_soft or (config.current_status != 'ing' and config.box_recogn != 'ing'):
            return True
        return False
