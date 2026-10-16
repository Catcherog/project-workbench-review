只处理当前工作目录 synthetic.json 的合成纪要。实际读取文件后提取任务、责任人及纪要中明确约定的截止日期；没有期限必须为 null，不自行推算。将文件中的 source_marker 原样放入结果。source 必须定位为 synthetic.json:minutes；结果字段为 source_marker/source/tasks，tasks 每项字段为 task/owner/deadline。
外层输出遵守受控 runner 的 marker/summary/missing/question 契约。marker 使用控制器给定的会话标记；summary 是上述提取结果的 JSON 字符串；missing 为 []，question 为 ""。不得读取其他目录、调用外部工具、执行嵌套模型或决定回复目标。
