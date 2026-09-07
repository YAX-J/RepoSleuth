# RepoSleuth 报告 · pdf-inspector

## 综合评分

- 架构（Cartographer）：**8/10**
- 可读性（Reader）：**8/10**
- 安全（Auditor）：**8/10**

## 架构图

```mermaid
graph TD
```

## 新人上手路线

1. 阅读README
2. 浏览代码结构
3. 运行示例
4. 调试问题
5. 提交贡献

## 风险清单

- [ ] src/lib.rs: 缺少输入验证
- [ ] src/extractor/content_stream.rs: 字符串操作未使用安全函数
- [ ] src/markdown/convert.rs: Markdown渲染未处理特殊字符
- [ ] src/vision/image_analysis.rs: 缺少图像质量检测
- [ ] src/bin/detect_pdf.rs: 代码风格不一致

## 附录 · 仓库画像

- 模块数：8；内部依赖边：0；外部依赖：5；总行数：2146
