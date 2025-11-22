#!/usr/bin/env python3
"""更新base.html以支持 $...$ 和 $$...$$ LaTeX语法"""

def update_base_html():
    # 读取文件
    with open('/workspace/templates/base.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 原始代码段
    old_code = '''                        window.renderContent = function(content) {
                            try {
                                // 1. 先用marked渲染Markdown
                                let html = marked.parse(content);
                                
                                // 2. 处理行内LaTeX: \\(...\\)
                                html = html.replace(/\\\\\\((.*?)\\\\\\)/g, function(match, p1) {
                                    try {
                                        return katex.renderToString(p1, {
                                            throwOnError: false,
                                            displayMode: false
                                        });
                                    } catch (e) {
                                        console.warn('KaTeX渲染失败:', e.message);
                                        return '<span class="katex-error">\\\\(' + escapeHtml(p1) + '\\\\)</span>';
                                    }
                                });
                                
                                // 3. 处理块级LaTeX: \\[...\\]
                                html = html.replace(/\\\\\\[(.*?)\\\\\\]/g, function(match, p1) {
                                    try {
                                        return '<div class="katex-block">' +
                                               katex.renderToString(p1, {
                                                   throwOnError: false,
                                                   displayMode: true
                                               }) +
                                               '</div>';
                                    } catch (e) {
                                        console.warn('KaTeX块级渲染失败:', e.message);
                                        return '<div class="katex-block katex-error">\\\\[' + escapeHtml(p1) + '\\\\]</div>';
                                    }
                                });
                                
                                return html;
                            } catch (e) {
                                console.error('内容渲染失败:', e);
                                // 降级：显示原始内容，但进行HTML转义
                                return '<div class="render-error">' +
                                       escapeHtml(content) +
                                       '</div>';
                            }
                        };'''
    
    # 新代码段
    new_code = '''                        window.renderContent = function(content) {
                            try {
                                // 1. 先用marked渲染Markdown
                                let html = marked.parse(content);
                                
                                // 2. 处理行内LaTeX: $(...)$
                                html = html.replace(/\$([^\$]+)\$/g, function(match, p1) {
                                    try {
                                        return katex.renderToString(p1, {
                                            throwOnError: false,
                                            displayMode: false
                                        });
                                    } catch (e) {
                                        console.warn('KaTeX渲染失败:', e.message);
                                        return '<span class="katex-error">$' + escapeHtml(p1) + '$</span>';
                                    }
                                });
                                
                                // 3. 处理块级LaTeX: $$(...)$$
                                html = html.replace(/\$\$([^\$]+)\$\$/g, function(match, p1) {
                                    try {
                                        return '<div class="katex-block">' +
                                               katex.renderToString(p1, {
                                                   throwOnError: false,
                                                   displayMode: true
                                               }) +
                                               '</div>';
                                    } catch (e) {
                                        console.warn('KaTeX块级渲染失败:', e.message);
                                        return '<div class="katex-block katex-error">$$' + escapeHtml(p1) + '$$</div>';
                                    }
                                });
                                
                                // 4. 处理行内LaTeX: \\(...\\)
                                html = html.replace(/\\\\\\((.*?)\\\\\\)/g, function(match, p1) {
                                    try {
                                        return katex.renderToString(p1, {
                                            throwOnError: false,
                                            displayMode: false
                                        });
                                    } catch (e) {
                                        console.warn('KaTeX渲染失败:', e.message);
                                        return '<span class="katex-error">\\\\(' + escapeHtml(p1) + '\\\\)</span>';
                                    }
                                });
                                
                                // 5. 处理块级LaTeX: \\[...\\]
                                html = html.replace(/\\\\\\[(.*?)\\\\\\]/g, function(match, p1) {
                                    try {
                                        return '<div class="katex-block">' +
                                               katex.renderToString(p1, {
                                                   throwOnError: false,
                                                   displayMode: true
                                               }) +
                                               '</div>';
                                    } catch (e) {
                                        console.warn('KaTeX块级渲染失败:', e.message);
                                        return '<div class="katex-block katex-error">\\\\[' + escapeHtml(p1) + '\\\\]</div>';
                                    }
                                });
                                
                                return html;
                            } catch (e) {
                                console.error('内容渲染失败:', e);
                                // 降级：显示原始内容，但进行HTML转义
                                return '<div class="render-error">' +
                                       escapeHtml(content) +
                                       '</div>';
                            }
                        };'''
    
    # 替换内容
    if old_code in content:
        content = content.replace(old_code, new_code)
        
        # 写回文件
        with open('/workspace/templates/base.html', 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("成功更新 LaTeX 支持代码")
    else:
        print("未找到要替换的代码段")

if __name__ == "__main__":
    update_base_html()