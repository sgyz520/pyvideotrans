from PySide6 import QtWidgets

from videotrans import translator
from videotrans.configure import config
# set baidu
from videotrans.util.TestSrtTrans import TestSrtTrans


def openwin():
    def feed(d):
        if not d.startswith("ok"):
            QtWidgets.QMessageBox.critical(winobj, config.transobj['anerror'], d)
        else:
            QtWidgets.QMessageBox.information(winobj, "OK", d[3:])
        winobj.test.setText('测试' if config.defaulelang == 'zh' else 'Test')

    def save_baidu():
        appid = winobj.baidu_appid.text()
        miyue = winobj.baidu_miyue.text()
        config.params["baidu_appid"] = appid
        config.params["baidu_miyue"] = miyue
        config.getset_params(config.params)
        winobj.close()

    def test():
        appid = winobj.baidu_appid.text()
        miyue = winobj.baidu_miyue.text()
        if not appid or not miyue:
            return QtWidgets.QMessageBox.critical(winobj, config.transobj['anerror'],
                                                  '必须填写 appid 和 密钥 等信息' if config.defaulelang == 'zh' else 'Please input appid and Secret')
        config.params["baidu_appid"] = appid
        config.params["baidu_miyue"] = miyue

        winobj.test.setText('测试中请稍等...' if config.defaulelang == 'zh' else 'Testing...')
        task = TestSrtTrans(parent=winobj, translator_type=translator.BAIDU_INDEX)
        task.uito.connect(feed)
        task.start()

    from videotrans.component import BaiduForm
    winobj = config.child_forms.get('baiduw')
    if winobj is not None:
        winobj.show()
        winobj.raise_()
        winobj.activateWindow()
        return
    winobj = BaiduForm()
    config.child_forms['baiduw'] = winobj
    if config.params["baidu_appid"]:
        winobj.baidu_appid.setText(config.params["baidu_appid"])
    if config.params["baidu_miyue"]:
        winobj.baidu_miyue.setText(config.params["baidu_miyue"])
    winobj.set_badiu.clicked.connect(save_baidu)
    winobj.test.clicked.connect(test)
    winobj.show()
