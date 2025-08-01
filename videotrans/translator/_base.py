import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

import requests

from videotrans.configure import config
from videotrans.configure._base import BaseCon
from videotrans.util import tools


@dataclass
class BaseTrans(BaseCon):
    text_list: Union[List, str] = ""
    target_language_name: str = ""
    inst: Optional[Any] = None  # Use Optional and Any for unknown types
    source_code: str = ""
    uuid: Optional[str] = None
    is_test: bool = False
    target_code: str = ""

    api_url: str = field(default="", init=False)
    error: str = field(default="", init=False)
    error_code: int = field(default=0, init=False)
    iter_num: int = field(default=0, init=False)
    model_name: str = field(default="", init=False)
    proxies: Optional[Dict] = field(default=None, init=False)

    target_list: List = field(default_factory=list, init=False)
    split_source_text: List = field(default_factory=list, init=False)

    trans_thread: int = field(init=False)
    retry: int = field(init=False)
    wait_sec: float = field(init=False)
    is_srt: bool = field(init=False)
    aisendsrt: bool = field(init=False)

    def __post_init__(self):
        super().__init__()

        self.trans_thread = int(config.settings.get('trans_thread', 5))
        self.retry = int(config.settings.get('retries', 2))
        self.wait_sec = float(config.settings.get('translation_wait', 0))
        self.aisendsrt = config.settings.get('aisendsrt', False)

        self.is_srt = not isinstance(self.text_list, str)

    # 发出请求获取内容 data=[text1,text2,text] | text
    def _item_task(self, data: Union[List[str], str]) -> str:
        pass

    def _exit(self):
        if config.exit_soft or (config.current_status != 'ing' and config.box_trans != 'ing' and not self.is_test):
            return True
        return False

    # 实际操作 # 出错时发送停止信号
    def run(self) -> Union[List, str, None]:
        # 开始对分割后的每一组进行处理
        Path(config.TEMP_HOME).mkdir(parents=True, exist_ok=True)
        self._signal(text="")
        if self.is_srt:
            source_text = [t['text'] for t in self.text_list] if not self.aisendsrt else self.text_list
            self.split_source_text = [source_text[i:i + self.trans_thread] for i in
                                      range(0, len(self.text_list), self.trans_thread)]
        else:
            source_text = self.text_list.strip().split("\n")
            self.split_source_text = [source_text[i:i + self.trans_thread] for i in
                                      range(0, len(source_text), self.trans_thread)]

        if self.is_srt and self.aisendsrt:
            return self.runsrt()

        for i, it in enumerate(self.split_source_text):
            # 失败后重试 self.retry 次
            while 1:
                if self._exit():
                    return
                if self.iter_num > self.retry:
                    msg = f'{"字幕翻译失败" if config.defaulelang == "zh" else " Translation Subtitles error"},{self.error}'
                    self._signal(text=msg, type="error")
                    raise Exception(msg)

                self.iter_num += 1
                try:
                    result = self._get_cache(it)
                    if not result:
                        result = tools.cleartext(self._item_task(it))
                        self._set_cache(it, result)
                    if self.inst and self.inst.precent < 75:
                        self.inst.precent += 0.01
                    # 非srt直接break
                    if not self.is_srt:
                        self.target_list.append(result)
                        self.iter_num = 0
                        self.error = ''
                        break
                    sep_res = result.split("\n")

                    for x, result_item in enumerate(sep_res):
                        if x < len(it):
                            self.target_list.append(result_item.strip())
                            self._signal(
                                text=result_item + "\n",
                                type='subtitle')
                            self._signal(
                                text=config.transobj['starttrans'] + f' {i * self.trans_thread + x + 1} ')
                    # 行数不匹配填充空行
                    if len(sep_res) < len(it):
                        tmp = ["" for x in range(len(it) - len(sep_res))]
                        self.target_list += tmp
                except (requests.exceptions.ProxyError, requests.ConnectionError, requests.exceptions.RetryError,
                        requests.Timeout) as e:
                    msg = ''
                    if self.api_url:
                        msg = f'无法连接当前API:{self.api_url} ' if config.defaulelang == 'zh' else f'Check API:{self.api_url} '
                    raise RuntimeError(msg)
                except Exception as e:
                    self.error = f'{e}'
                    config.logger.exception(e, exc_info=True)
                    self._signal(
                        text=f"出错，10s后重试," if config.defaulelang == 'zh' else f'{self.iter_num} retries occurs, 10s later retry')
                    time.sleep(10)
                else:
                    # 成功 未出错
                    self.error = ''
                    self.error_code = 0
                    self.iter_num = 0
                    if self.inst and self.inst.status_text:
                        self.inst.status_text = '字幕翻译中' if config.defaulelang == 'zh' else 'Translation of subtitles'
                    time.sleep(self.wait_sec)
                    break

        # 恢复原代理设置
        if self.shound_del:
            self._set_proxy(type='del')
        # text_list是字符串
        if not self.is_srt:
            return "\n".join(self.target_list)

        max_i = len(self.target_list)

        for i, it in enumerate(self.text_list):
            if i < max_i:
                self.text_list[i]['text'] = self.target_list[i]
            else:
                self.text_list[i]['text'] = ""
        return self.text_list

    # 发送完整字幕格式内容进行翻译
    def runsrt(self):
        result_srt_str_list = []
        for i, it in enumerate(self.split_source_text):
            while 1:
                if self._exit():
                    return
                if self.iter_num > self.retry:
                    msg = f'{"字幕翻译阶段失败" if config.defaulelang == "zh" else " Translate subtitles error "},{self.error}'
                    self._signal(text=msg, type="error")
                    raise Exception(msg)

                self.iter_num += 1

                try:
                    for j, srt in enumerate(it):
                        srt['text'] = srt['text'].strip().replace("\n", " ")
                        it[j] = srt
                    srt_str = "\n\n".join(
                        [f"{srtinfo['line']}\n{srtinfo['time']}\n{srtinfo['text'].strip()}" for srtinfo in it])
                    result = self._get_cache(srt_str)
                    if not result:
                        result = tools.cleartext(self._item_task(srt_str))
                        if not result.strip():
                            raise Exception('无返回翻译结果' if config.defaulelang == 'zh' else 'Translate result is empty')
                        self._set_cache(it, result)

                    if self.inst and self.inst.precent < 75:
                        self.inst.precent += 0.1

                    self._signal(text=result, type='subtitle')
                    result_srt_str_list.append(result)
                except (requests.exceptions.ProxyError, requests.ConnectionError, requests.Timeout,
                        requests.exceptions.RetryError) as e:
                    msg = ''
                    if self.api_url:
                        msg = f'无法连接当前API:{self.api_url} ' if config.defaulelang == 'zh' else f'Check API:{self.api_url} '
                    raise RuntimeError(msg)
                except Exception as e:
                    self.error = f'{e}'
                    config.logger.exception(e, exc_info=True)
                    self._signal(
                        text=f"出错，10s后重试," if config.defaulelang == 'zh' else f'retries occurs, 10s later retry')
                    time.sleep(10)
                else:
                    # 成功 未出错
                    self.error = ''
                    self.error_code = 0
                    self.iter_num = 0
                    if self.inst and self.inst.status_text:
                        self.inst.status_text = '字幕翻译中' if config.defaulelang == 'zh' else 'Translation of subtitles'
                    time.sleep(self.wait_sec)
                    break

        # 恢复原代理设置
        if self.shound_del:
            self._set_proxy(type='del')
        raws_list = tools.get_subtitle_from_srt("\n\n".join(result_srt_str_list), is_file=False)
        ## new 

        # 双语翻译结果，只取最后一行
        config.logger.info(f'{raws_list=}\n{result_srt_str_list=}\n')
        for i, it in enumerate(raws_list):
            it['text'] = it['text'].strip().split("\n")
            if it['text']:
                it['text'] = it['text'][-1]
            raws_list[i] = it
        return raws_list

    def _set_cache(self, it, res_str):
        if not res_str.strip():
            return
        key_cache = self._get_key(it)

        file_cache = config.TEMP_DIR + f'/translate_cache/{key_cache}.txt'
        if not Path(config.TEMP_DIR + f'/translate_cache').is_dir():
            Path(config.TEMP_DIR + f'/translate_cache').mkdir(parents=True, exist_ok=True)
        Path(file_cache).write_text(res_str, encoding='utf-8')

    def _get_cache(self, it):
        if self.is_test:
            return None
        key_cache = self._get_key(it)
        file_cache = config.TEMP_DIR + f'/translate_cache/{key_cache}.txt'
        if Path(file_cache).exists():
            return Path(file_cache).read_text(encoding='utf-8')
        return None

    def _get_key(self, it):
        Path(config.TEMP_DIR + '/translate_cache').mkdir(parents=True, exist_ok=True)
        return tools.get_md5(
            f'{self.__class__.__name__}-{self.api_url}-{self.trans_thread}-{self.retry}-{self.wait_sec}-{self.iter_num}-{self.is_srt}-{self.aisendsrt}-{self.proxies}-{self.model_name}-{self.source_code}-{self.target_code}-{it if isinstance(it, str) else json.dumps(it)}')
