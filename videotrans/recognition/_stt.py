# stt项目识别接口
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, ClassVar,Union
import requests

from videotrans.configure import config
from videotrans.util import tools
from videotrans.recognition._base import BaseRecogn

"""
            请求发送：以二进制形式发送键名为 audio 的wav格式音频数据，采样率为16k、通道为1
            requests.post(api_url, files={"file": open(audio_file, 'rb')},data={language:2位语言代码,model:模型名})

            失败时返回
            res={
                "code":1,
                "msg":"错误原因"
            }

            成功时返回
            res={
                "code":0,
                "data":srt格式字符串
            }
"""


@dataclass
class SttAPIRecogn(BaseRecogn):
    raws: List = field(default_factory=list, init=False)

    def __post_init__(self):
        super().__post_init__()
        api_url = config.params.get('stt_url', '').strip().rstrip('/').lower()
        if not api_url:
            raise Exception('必须填写自定义api地址' if config.defaulelang == 'zh' else 'Custom api address must be filled in')

        if not api_url.startswith('http'):
            api_url = f'http://{api_url}'
        self.api_url = f'{api_url}/api' if not api_url.endswith('/api') else api_url


    def _exec(self) -> Union[List[Dict], None]:
        if self._exit():
            return
        with open(self.audio_file, 'rb') as f:
            chunk=f.read()
        files = {"file": (os.path.basename(self.audio_file),chunk)}
        self._signal(
            text=f"识别可能较久，请耐心等待" if config.defaulelang == 'zh' else 'Recognition may take a while, please be patient')
        try:
            data={"language":self.detect_language[:2],"model":config.params.get('stt_model','tiny'),"response_format":"srt"}
            res = requests.post(f"{self.api_url}", files=files,data=data, proxies={"http": "", "https": ""}, timeout=7200)
            config.logger.info(f'STT_API:{res=}')
            res = res.json()
            if "code" not in res or res['code'] != 0:
                raise Exception(f'{res["msg"]}')
            if "data" not in res or len(res['data']) < 1:
                raise Exception(f'识别出错{res=}')
            self._signal(
                text=res['data'],
                type='replace_subtitle'
            )
            return tools.get_subtitle_from_srt(res['data'], is_file=False)
        except Exception as e:
            raise
