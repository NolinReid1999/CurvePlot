# 更新检测

数据来源：`https://api.github.com/repos/NolinReid1999/CurvePlot/releases/latest`。

自动检查每24小时最多一次，失败也计入；手动检查可立即触发。同一版本选择稍后提醒后7天内不自动重复弹出，新版或手动检查不受影响。网络传输超时8秒，总请求上限10秒。更新按钮只打开仓库的HTTPS Release页面。

发布者只需修改 `src/tailor/version.py`，GitHub使用 `v1.0.2` 等正式标签，取消预发布/草稿并设为Latest。若新版本是草稿或预发布，当前正式版本检测不会把它当作更新。

对比采用packaging.version数字版本及build序号，不使用字符串字典序。更新检测不上传数据表、工程文件或访问令牌。
