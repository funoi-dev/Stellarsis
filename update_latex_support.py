#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re

def update_render_function():
    # 读取文件
    with open('/workspace/templates/base.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 原始函数的正则表达式模式（匹配整个renderContent函数）
    # 匹配从window.renderContent = function(content) { 到 }; 的内容
    pattern = r'(// 全局渲染函数\s*\n\s*window\.renderContent = function\(content\) \{)([\s\S]*?)(\n\s*return html;\s*\}\s*catch\s*\([^)]*\)\s*\{[\s\S]*?\n\s*\};)'
    
    # 新的函数内容
    new_function_content = '''        // 全局渲染函数
        window.renderContent = function(content) {
            try {
                // 1. 先用marked渲染Markdown
                let html = marked.parse(content);
                
                // 2. 处理块级LaTeX: $${}$$
                html = html.replace(/\\$\\$\\{([^}]+)\\}\\$\\$/g, function(match, p1) {
                    try {
                        return '<div class="katex-block">' +
                               katex.renderToString(p1, {
                                   throwOnError: false,
                                   displayMode: true
                               }) +
                               '</div>';
                    } catch (e) {
                        console.warn('KaTeX块级渲染失败:', e.message);
                        return '<div class="katex-block katex-error">$${' + escapeHtml(p1) + '}$$</div>';
                    }
                });
                
                // 3. 处理行内LaTeX: ${}$
                html = html.replace(/\\$\\{([^}]+)\\}\\$/g, function(match, p1) {
                    try {
                        return katex.renderToString(p1, {
                            throwOnError: false,
                            displayMode: false
                        });
                    } catch (e) {
                        console.warn('KaTeX渲染失败:', e.message);
                        return '<span class="katex-error">${' + escapeHtml(p1) + '}$</span>';
                    }
                });
                
                // 4. 处理行内LaTeX: $...$
                html = html.replace(/\\$([^\\$]+)\\$/g, function(match, p1) {
                    try {
                        // 避免与${}$格式冲突，检查是否是${}$格式
                        if(/^\\{.*\\}$/.test(p1)) {
                            return '${' + escapeHtml(p1.slice(1, -1)) + '}$';
                        }
                        return katex.renderToString(p1, {
                            throwOnError: false,
                            displayMode: false
                        });
                    } catch (e) {
                        console.warn('KaTeX渲染失败:', e.message);
                        return '<span class="katex-error">$' + escapeHtml(p1) + '$</span>';
                    }
                });
                
                // 5. 处理块级LaTeX: $$...$$
                html = html.replace(/\\$\\$([^\\$]+)\\$\\$/g, function(match, p1) {
                    try {
                        // 避免与$${}$$格式冲突，检查是否是$${}$$格式
                        if(/^\\{.*\\}$/.test(p1)) {
                            return '<div class="katex-block katex-error">$${' + escapeHtml(p1.slice(1, -1)) + '}$$</div>';
                        }
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
                
                // 6. 处理行内LaTeX: \\(...\\)
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
                
                // 7. 处理块级LaTeX: \\[...\\]
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
    
    # 替换函数
    updated_content = re.sub(pattern, lambda m: m.group(1) + new_function_content[len(m.group(1)):], content)
    
    # 如果上面的正则没有匹配到，尝试更简单的匹配
    if updated_content == content:
        # 直接替换整个函数体部分
        start_marker = 'window.renderContent = function(content) {'
        end_marker = '        };'
        
        start_pos = content.find(start_marker)
        if start_pos != -1:
            # 找到函数结束位置
            pos = start_pos
            brace_count = 0
            while pos < len(content):
                if content[pos] == '{':
                    brace_count += 1
                elif content[pos] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        # 找到匹配的结束括号，继续查找分号
                        semicolon_pos = content.find(';', pos)
                        if semicolon_pos != -1:
                            # 找到函数的完整结束位置
                            end_pos = semicolon_pos + 1
                            while end_pos < len(content) and content[end_pos] in [' ', '\t', '\n', '\r']:
                                end_pos += 1
                            if content[end_pos:end_pos+1] == '}':
                                # 找到完整的结束
                                end_pos = content.find('        };', pos)
                                if end_pos != -1:
                                    # 查找下一个分号作为结束
                                    end_pos = content.find(';', end_pos)
                                    if end_pos != -1:
                                        end_pos += 1
                                break
                        else:
                            break
                pos += 1
            
            if pos < len(content):
                # 找到结束 } 的位置
                while pos < len(content) and content[pos] != '}':
                    pos += 1
                if pos < len(content):
                    # 查找分号
                    semicolon_pos = content.find(';', pos)
                    if semicolon_pos != -1:
                        end_pos = semicolon_pos + 1
                        original_function = content[start_pos:end_pos]
                        updated_content = content.replace(original_function, new_function_content)
    
    # 写回文件
    with open('/workspace/templates/base.html', 'w', encoding='utf-8') as f:
        f.write(updated_content)
    
    print("renderContent函数已更新")

if __name__ == "__main__":
    update_render_function()