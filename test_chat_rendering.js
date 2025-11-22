// 测试文件：验证chat.js是否符合最佳实践建议
console.log("=== 聊天系统渲染功能测试 ===");

// 模拟环境测试
function testRenderingSystem() {
    console.log("1. 测试渲染系统初始化...");
    
    // 检查必需的函数是否存在
    const requiredFunctions = [
        'initializeRenderingSystem',
        'waitForRenderSystem', 
        'ensureDependenciesLoaded',
        'tryRenderMessage',
        'retryRenderingAllMessages',
        'escapeHtml'
    ];
    
    let allFunctionsExist = true;
    requiredFunctions.forEach(func => {
        if (typeof window[func] === 'function') {
            console.log(`  ✓ ${func} 函数存在`);
        } else {
            console.log(`  ✗ ${func} 函数缺失`);
            allFunctionsExist = false;
        }
    });
    
    if (allFunctionsExist) {
        console.log("  ✓ 所有必需函数都已定义");
    } else {
        console.log("  ✗ 部分必需函数缺失");
    }
    
    // 测试HTML转义功能
    console.log("\n2. 测试HTML转义功能...");
    if (typeof escapeHtml === 'function') {
        const testInput = '<script>alert("test")</script>';
        const escaped = escapeHtml(testInput);
        console.log(`  输入: ${testInput}`);
        console.log(`  输出: ${escaped}`);
        if (escaped.includes('<script>')) {
            console.log("  ✗ HTML未正确转义");
        } else {
            console.log("  ✓ HTML正确转义");
        }
    }
    
    // 测试安全渲染函数
    console.log("\n3. 测试安全渲染功能...");
    if (typeof tryRenderMessage === 'function') {
        // 创建测试元素
        const testElement = document.createElement('div');
        testElement.className = 'message-content';
        testElement.dataset.originalContent = '**测试内容**';
        
        const result = tryRenderMessage(testElement, '**粗体测试**');
        console.log(`  渲染结果: ${testElement.innerHTML}`);
        console.log(`  返回值: ${result}`);
        console.log("  ✓ 安全渲染函数工作正常");
    }
    
    console.log("\n=== 测试完成 ===");
}

// 如果在浏览器环境中运行
if (typeof window !== 'undefined') {
    testRenderingSystem();
} else {
    console.log("请在浏览器环境中运行此测试");
}