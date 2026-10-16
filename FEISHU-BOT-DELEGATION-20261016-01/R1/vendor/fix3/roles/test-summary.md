只处理当前工作目录 synthetic.json 的合成测试结果。实际读取文件后统计总数、通过、失败、阻塞和百分比通过率；不要预设数值。将文件中的 source_marker 原样放入统计结果。source 必须定位为 synthetic.json:tests，统计结果字段为 source_marker/source/total/passed/failed/blocked/pass_rate_percent。
外层输出遵守受控 runner 的 marker/summary/missing/question 契约。marker 使用控制器给定的会话标记；summary 是上述统计结果的 JSON 字符串；missing 为 []，question 为 ""。不得读取其他目录、调用外部工具、执行嵌套模型或决定回复目标。
