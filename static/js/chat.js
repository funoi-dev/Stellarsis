// 全局变量
let chatSocket = null;
let chatHistoryLoaded = false;
let lastMessageId = 0;
let onlineUsers = [];
let roomId = null;
let userId = null;
let messageQueue = [];
let isRenderingReady = false;
let renderRetryCount = 0;
const MAX_RENDER_RETRY = 3;
let processedMessageIds = new Set();
const processedContentHashes = new Set();
const pendingMessages = new Map();
// 扩展已处理消息集合，区分不同类型
const processedSystemEvents = new Map(); // {eventType_userId_timestamp: true}
const recentSystemMessages = new Map(); // 防止重复系统消息

// 初始化渲染系统
function initializeRenderingSystem() {
    // 如果renderContent函数已经存在，直接使用它
    if (typeof window.renderContent !== 'function') {
        // 定义渲染函数，包含完整的降级方案
        window.renderContent = function(content) {
            try {
                // 安全检查：确保marked可用
                if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
                    return marked.parse(content);
                }
                // 降级到简单HTML渲染
                return simpleHtmlRender(content);
            } catch (e) {
                console.warn('高级渲染失败，使用降级方案:', e);
                return simpleHtmlRender(content);
            }
        };
        
        // 简单HTML渲染作为备选方案
        function simpleHtmlRender(content) {
            // 基本的Markdown行内元素支持
            let html = escapeHtml(content)
                .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.*?)\*/g, '<em>$1</em>')
                .replace(/`(.*?)`/g, '<code>$1</code>')
                .replace(/\n/g, '<br>');
            
            return `<div class="plaintext-render">${html}</div>`;
        }
    }
    
    // 触发渲染就绪事件
    document.dispatchEvent(new Event('renderReady'));
    isRenderingReady = true;
    console.log('渲染系统已初始化');
}

// 安全的HTML转义
function escapeHtml(unsafe) {
    if (!unsafe) return '';
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// 生成内容哈希
function generateContentHash(content, timestamp) {
    // 简单哈希：截取内容前50字符 + 时间戳（精确到秒）
    const contentSnippet = content.substring(0, 50);
    const timeKey = new Date(timestamp).getTime() / 1000 | 0;  // 精确到秒
    return btoa(encodeURIComponent(`${contentSnippet}|${timeKey}`)).substring(0, 16);
}

// 统一时间格式化函数（UTC+8时区）
function formatTimeDisplay(timestamp) {
    // 将UTC时间转换为UTC+8（北京时间）
    const date = new Date(timestamp);
    const beijingTime = new Date(date.getTime() + 8 * 60 * 60 * 1000);
    
    // 格式化时间
    const hours = beijingTime.getHours().toString().padStart(2, '0');
    const minutes = beijingTime.getMinutes().toString().padStart(2, '0');
    return `${hours}:${minutes}`;
}

// 全局变量 - 需要从页面数据获取
var currentUsername = '用户';
var currentNickname = '用户';
var currentUserColor = '#000000';
var currentUserBadge = '';
var currentUserId = 0;

// 更健壮的渲染就绪检测
function waitForRenderSystem(callback) {
    const checkInterval = setInterval(() => {
        try {
            // 检查渲染系统是否真正可用
            if (typeof window.renderContent === 'function') {
                // 尝试渲染测试内容
                window.renderContent('**test**');
                clearInterval(checkInterval);
                callback();
                return;
            }
        } catch (e) {
            console.debug('渲染系统尚未完全就绪:', e);
        }
    }, 200);
    
    // 超时处理
    setTimeout(() => {
        clearInterval(checkInterval);
        if (!isRenderingReady) {
            console.warn('渲染系统加载超时，强制初始化降级方案');
            initializeRenderingSystem(); // 使用降级方案
            callback();
        }
    }, 3000);
}

// 设置模态框
function setupModal() {
    const modal = document.getElementById('online-list-modal');
    const showModalBtn = document.getElementById('show-online-list');
    const closeBtn = modal ? modal.querySelector('.close') : null;
    
    if (!showModalBtn || !modal) return;
    
    showModalBtn.onclick = function() {
        modal.style.display = 'block';
        updateOnlineUsersList();
    };
    
    if (closeBtn) {
        closeBtn.onclick = function() {
            modal.style.display = 'none';
        };
    }
    
    window.onclick = function(event) {
        if (event.target == modal) {
            modal.style.display = 'none';
        }
    };
}

// 加载聊天历史
function loadChatHistory() {
    if (chatHistoryLoaded) return;
    
    fetch(`/api/chat/${roomId}/history`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP错误! 状态: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            const messagesContainer = document.getElementById('chat-messages');
            if (!messagesContainer) return;
            
            data.messages.forEach(msg => {
                addMessageToUI(msg);
            });
            
            // 更新最后一条消息ID
            if (data.messages.length > 0) {
                lastMessageId = data.messages[data.messages.length - 1].id;
            }
            
            // 滚动到底部
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
            chatHistoryLoaded = true;
        })
        .catch(error => {
            console.error('加载历史消息失败:', error);
            const messagesContainer = document.getElementById('chat-messages');
            if (messagesContainer) {
                messagesContainer.innerHTML += 
                    `<div class="chat-error">加载历史消息失败: ${error.message}</div>`;
            }
        });
}

// 设置轮询（老旧浏览器降级方案）
function setupPolling() {
    console.log('使用轮询作为WebSocket的降级方案');
    
    // 每5秒检查一次新消息
    setInterval(() => {
        if (lastMessageId > 0) {
            fetch(`/api/chat/${roomId}/history?offset=0&limit=50`)
                .then(response => response.json())
                .then(data => {
                    const messagesContainer = document.getElementById('chat-messages');
                    if (!messagesContainer) return;
                    
                    let hasNewMessages = false;
                    
                    data.messages.forEach(msg => {
                        if (msg.id > lastMessageId) {
                            addMessageToUI(msg);
                            hasNewMessages = true;
                            
                            // 更新最后一条消息ID
                            if (msg.id > lastMessageId) {
                                lastMessageId = msg.id;
                            }
                        }
                    });
                    
                    if (hasNewMessages) {
                        messagesContainer.scrollTop = messagesContainer.scrollHeight;
                    }
                })
                .catch(error => {
                    console.error('轮询获取消息失败:', error);
                });
        }
    }, 5000);
    
    // 每30秒更新在线状态
    setInterval(updateOnlineStatus, 30000);
}

// 设置WebSocket
function setupWebSocket() {
    // 检查WebSocket支持
    if (typeof io === 'undefined') {
        console.log('socket.io 未加载，使用轮询代替');
        setupPolling();
        return;
    }
    
    try {
        chatSocket = io('/', {
            path: '/socket.io',
            reconnection: true,
            reconnectionAttempts: 5,
            reconnectionDelay: 1000,
            timeout: 20000,
            transports: ['websocket', 'polling']
        });
        
        chatSocket.on('connect', () => {
            console.log('WebSocket连接已建立');
            
            // 关键修改：仅在首次连接时发送join事件
            if (!chatSocket.hasJoinedRoom) {
                chatSocket.emit('join', {room: roomId});
                chatSocket.hasJoinedRoom = true; // 标记已加入房间
            }
            
            updateOnlineStatus();
        });
        
        chatSocket.on('disconnect', (reason) => {
            console.log('WebSocket断开连接:', reason);
            const onlineCountElement = document.getElementById('online-count');
            if (onlineCountElement) {
                onlineCountElement.textContent = '连接中...';
            }
            
            // 尝试重新连接
            if (reason !== 'io server disconnect') {
                setTimeout(() => {
                    if (chatSocket && !chatSocket.connected) {
                        setupWebSocket();
                    }
                }, 5000);
            }
        });
        
        chatSocket.on('connect_error', (error) => {
            console.error('WebSocket连接错误:', error);
            const onlineCountElement = document.getElementById('online-count');
            if (onlineCountElement) {
                onlineCountElement.textContent = '连接错误';
            }
            
            // 尝试轮询作为后备
            setTimeout(setupPolling, 3000);
        });
        
        chatSocket.on('message', (data) => {
            // 检查是否是对本地消息的确认
            if (data.client_id && pendingMessages.has(data.client_id)) {
                // 更新现有消息，而不是添加新消息
                updateExistingMessage(data.client_id, data);
                pendingMessages.delete(data.client_id);
            } else {
                // 新消息
                addMessageToUI(data);
            }
        });
        
        chatSocket.on('online_users', (data) => {
            onlineUsers = data.users || [];
            updateOnlineCount();
        });
    } catch (e) {
        console.error('WebSocket初始化失败:', e);
        setupPolling();
    }
}

// 更新在线状态
function updateOnlineStatus() {
    if (chatSocket) {
        chatSocket.emit('get_online_users', {room_id: roomId});
    } else {
        // 轮询模式下，简单更新在线人数
        fetch('/api/online_count')
            .then(response => response.json())
            .then(data => {
                const onlineCountElement = document.getElementById('online-count');
                if (onlineCountElement) {
                    onlineCountElement.textContent = data.count || '未知';
                }
            })
            .catch(error => {
                console.error('更新在线状态失败:', error);
            });
    }
}

// 更新在线用户列表
function updateOnlineUsersList() {
    const list = document.getElementById('online-users-list');
    if (!list) return;
    
    list.innerHTML = '';
    
    if (!onlineUsers || onlineUsers.length === 0) {
        const li = document.createElement('li');
        li.textContent = '没有在线用户';
        list.appendChild(li);
        return;
    }
    
    onlineUsers.forEach(user => {
        const li = document.createElement('li');
        li.className = 'online-user-item';
        
        // 构建用户显示
        let userDisplay = '';
        if (user.badge) {
            userDisplay += `<span class="user-badge" style="background-color:${user.color}">${user.badge}</span> `;
        }
        userDisplay += `<span class="user-name" style="color:${user.color}">${user.nickname || user.username}</span>`;
        
        li.innerHTML = userDisplay;
        list.appendChild(li);
    });
}

// 更新在线人数显示
function updateOnlineCount() {
    const onlineCountElement = document.getElementById('online-count');
    if (onlineCountElement) {
        onlineCountElement.textContent = onlineUsers.length;
    }
}

// 发送消息
function sendMessage() {
    const messageInput = document.getElementById('message-text');
    if (!messageInput) return;
    
    const message = messageInput.value.trim();
    if (!message) return;
    
    // 生成唯一客户端ID
    const clientId = 'client-' + Date.now() + '-' + Math.random().toString(36).substr(2, 5);
    
    // 保存到待确认消息集合
    pendingMessages.set(clientId, {
        content: message,
        timestamp: new Date().toISOString(),
        sentTime: Date.now()
    });
    
    // 清空输入框
    messageInput.value = '';
    
    // 通过WebSocket发送
    if (chatSocket && chatSocket.connected) {
        // 本地预览
        const localMessage = {
            id: clientId,
            content: message,
            timestamp: new Date().toISOString(),
            user_id: currentUserId,
            username: currentUsername,
            nickname: currentNickname,
            color: currentUserColor,
            badge: currentUserBadge,
            isPending: true  // 标记为待确认
        };
        
        addMessageToUI(localMessage, true);
        
        chatSocket.emit('send_message', {
            room_id: roomId,
            message: message,
            client_id: clientId  // 发送客户端ID
        });
    } else {
        // WebSocket不可用，使用AJAX
        fetch('/api/chat/send', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                room_id: roomId,
                message: message
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('发送消息失败');
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                // 消息发送成功后，添加到UI
                const sentMessage = {
                    id: 'sent-' + Date.now(),
                    content: message,
                    timestamp: new Date().toISOString(),
                    user_id: currentUserId,
                    username: currentUsername,
                    nickname: currentNickname,
                    color: currentUserColor,
                    badge: currentUserBadge
                };
                
                addMessageToUI(sentMessage, true);
            }
        })
        .catch(error => {
            console.error('发送消息失败:', error);
            // 显示错误
            const errorElement = document.createElement('div');
            errorElement.className = 'chat-error';
            errorElement.textContent = '消息发送失败，请检查网络连接';
            document.getElementById('chat-messages').appendChild(errorElement);
        });
    }
}

// 设置消息输入
function setupMessageInput() {
    const sendButton = document.getElementById('send-button');
    const messageInput = document.getElementById('message-text');
    
    if (sendButton) {
        sendButton.addEventListener('click', sendMessage);
    }
    
    if (messageInput) {
        messageInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }
}


// 添加消息到UI
function addMessageToUI(msg, isLocal = false) {
    const messagesContainer = document.getElementById('chat-messages');
    if (!messagesContainer) return;
    
    // 1. 检查重复消息ID
    if (msg.id && processedMessageIds.has(msg.id)) {
        return;
    }
    
    // 2. 特殊处理系统消息
    if (msg.type === 'system' || msg.type === 'join' || msg.type === 'leave') {
        const eventKey = `${msg.type}_${msg.user_id}_${Math.floor(new Date(msg.timestamp).getTime() / 60000)}`;
        if (processedSystemEvents.has(eventKey)) {
            return;
        }
        processedSystemEvents.set(eventKey, true);
        
        // 限制系统事件缓存大小，避免内存泄漏
        if (processedSystemEvents.size > 100) {
            const keys = Array.from(processedSystemEvents.keys());
            for (let i = 0; i < 20; i++) {
                processedSystemEvents.delete(keys[i]);
            }
        }
    }
    
    // 3. 高级重复消息检测：不仅检查ID，还检查内容+时间的组合
    const contentHash = generateContentHash(msg.content, msg.timestamp);
    if (processedContentHashes.has(contentHash)) {
        return;
    }
    
    // 4. 添加到已处理集合
    if (msg.id) {
        processedMessageIds.add(msg.id);
    }
    processedContentHashes.add(contentHash);
    
    // 创建并添加消息元素
    const messageElement = createMessageElement(msg, isLocal);
    messageElement.dataset.contentHash = contentHash;  // 存储内容哈希以便后续匹配
    
    // 添加到容器
    messagesContainer.appendChild(messageElement);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// 添加状态消息
function addStatusMessage(msg) {
    const messagesContainer = document.getElementById('chat-messages');
    if (!messagesContainer) return;
    
    // 生成消息指纹
    const messageFingerprint = msg.substring(0, 50); // 取前50个字符
    const now = Date.now();
    
    // 检查是否最近已显示相同消息
    if (recentSystemMessages.has(messageFingerprint)) {
        const lastShown = recentSystemMessages.get(messageFingerprint);
        if (now - lastShown < 5000) { // 5秒内不重复显示
            return;
        }
    }
    
    recentSystemMessages.set(messageFingerprint, now);
    
    // 清理旧记录
    setTimeout(() => {
        if (recentSystemMessages.get(messageFingerprint) === now) {
            recentSystemMessages.delete(messageFingerprint);
        }
    }, 10000);
    
    const statusElement = document.createElement('div');
    statusElement.className = 'chat-status';
    statusElement.textContent = msg;
    
    messagesContainer.appendChild(statusElement);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// 更新现有消息
function updateExistingMessage(clientId, serverMessage) {
    // 查找对应的消息元素
    const existingMessage = document.querySelector(`[data-message-id="${clientId}"]`);
    if (!existingMessage) return;
    
    // 更新ID（从临时ID到服务器ID）
    existingMessage.dataset.messageId = serverMessage.id;
    
    // 更新时间戳
    const timeElement = existingMessage.querySelector('.message-time');
    if (timeElement) {
        timeElement.textContent = formatTimeDisplay(serverMessage.timestamp);
    }
    
    // 清除pending状态
    existingMessage.classList.remove('pending-message');
    
    // 重新渲染内容（如有需要）
    const contentElement = existingMessage.querySelector('.message-content');
    if (contentElement && typeof window.renderContent === 'function') {
        try {
            contentElement.innerHTML = window.renderContent(serverMessage.content);
        } catch (e) {
            console.error('更新消息内容失败:', e);
        }
    }
    
    // 更新processed集合
    processedMessageIds.delete(clientId);
    processedMessageIds.add(serverMessage.id);
}

// 创建消息元素
function createMessageElement(msg, isLocal = false) {
    const messageElement = document.createElement('div');
    
    // 区分消息类型
    if (msg.type === 'system' || msg.type === 'join' || msg.type === 'leave') {
        messageElement.className = 'chat-system-message';
    } else {
        messageElement.className = `chat-message ${isLocal ? 'local-message' : ''} ${msg.isPending ? 'pending-message' : ''}`;
    }
    
    // 系统消息特殊处理
    if (msg.type === 'system' || msg.type === 'join' || msg.type === 'leave') {
        const contentElement = document.createElement('div');
        contentElement.className = 'system-message-content';
        
        // 格式化系统消息
        let messageText = msg.content;
        if (msg.type === 'join') {
            messageText = `${msg.nickname || msg.username} 加入了聊天室`;
        } else if (msg.type === 'leave') {
            messageText = `${msg.nickname || msg.username} 离开了聊天室`;
        }
        
        contentElement.textContent = messageText;
        
        // 系统消息时间
        const timeElement = document.createElement('span');
        timeElement.className = 'system-message-time';
        const date = new Date(msg.timestamp);
        timeElement.textContent = formatTimeDisplay(date);
        
        messageElement.appendChild(contentElement);
        messageElement.appendChild(timeElement);
        return messageElement;
    }
    
    // 用户消息处理
    // 用户信息
    const userElement = document.createElement('div');
    userElement.className = 'message-user';
    
    // 用户徽章（如果有）
    if (msg.badge) {
        const badgeElement = document.createElement('span');
        badgeElement.className = 'message-badge';
        badgeElement.style.backgroundColor = msg.color;
        badgeElement.textContent = msg.badge;
        userElement.appendChild(badgeElement);
    }
    
    // 用户名
    const nameElement = document.createElement('span');
    nameElement.className = 'message-username';
    nameElement.style.color = msg.color;
    nameElement.textContent = msg.nickname || msg.username;
    userElement.appendChild(nameElement);
    
    // 时间
    const timeElement = document.createElement('span');
    timeElement.className = 'message-time';
    timeElement.textContent = formatTimeDisplay(msg.timestamp);
    userElement.appendChild(timeElement);
    
    // 消息内容
    const contentElement = document.createElement('div');
    contentElement.className = 'message-content';
    contentElement.dataset.originalContent = msg.content; // 保存原始内容用于重试

    // 尝试立即渲染
    tryRenderMessage(contentElement, msg.content);
    
    // 组装
    messageElement.appendChild(userElement);
    messageElement.appendChild(contentElement);
    
    return messageElement;
}

// 处理消息队列
function processMessageQueue() {
    messageQueue.forEach(item => {
        try {
            item.element.innerHTML = window.renderContent(item.content);
        } catch (e) {
            console.error('队列消息渲染失败:', e);
            item.element.innerHTML = `<div class="render-error">${escapeHtml(item.content)}</div>`;
        }
    });
    messageQueue = [];
}

// 安全渲染消息
function tryRenderMessage(element, content) {
    if (typeof window.renderContent === 'function') {
        try {
            element.innerHTML = window.renderContent(content);
            return true;
        } catch (e) {
            console.error('消息渲染失败:', e);
        }
    }
    
    // 降级渲染
    element.innerHTML = `<div class="render-fallback">${escapeHtml(content)}</div>`;
    return false;
}

// 重新尝试渲染所有消息
function retryRenderingAllMessages() {
    document.querySelectorAll('.message-content').forEach(element => {
        const content = element.dataset.originalContent;
        if (content) {
            tryRenderMessage(element, content);
        }
    });
}


// 全局初始化函数
window.initChat = function() {
    // 从页面数据获取房间ID
    const roomElement = document.getElementById('chat-room-data');
    if (!roomElement) {
        console.error('未找到聊天室数据');
        return;
    }
    
    try {
        const roomData = JSON.parse(roomElement.textContent);
        roomId = roomData.room_id;
        userId = roomData.user_id;
        currentUserId = roomData.user_id;
        currentUsername = roomData.username || '用户';
        currentNickname = roomData.nickname || currentUsername;
        currentUserColor = roomData.color || '#000000';
        currentUserBadge = roomData.badge || '';
        
        // 1. 先设置UI元素
        const onlineCountElement = document.getElementById('online-count');
        if (onlineCountElement) {
            onlineCountElement.textContent = '加载中...';
        }
        
        setupModal();
        setupMessageInput();
        
        // 2. 然后连接WebSocket
        setupWebSocket();
        
        // 3. 最后加载历史消息（确保WebSocket已设置好）
        setTimeout(() => {
            loadChatHistory();
        }, 500); // 短暂延迟，确保WebSocket有时间初始化
        
        // 4. 设置渲染就绪处理
        document.addEventListener('renderReady', function() {
            isRenderingReady = true;
            processMessageQueue();
        });
        
        if (typeof window.renderContent === 'function') {
            isRenderingReady = true;
        }
        
        console.log('聊天系统初始化完成');
    } catch (e) {
        console.error('聊天室初始化失败:', e);
    }
};

// 确保所有依赖加载
function ensureDependenciesLoaded(callback) {
    const dependencies = [
        { name: 'socket.io', check: () => typeof io !== 'undefined' },
        { name: 'marked', check: () => typeof marked !== 'undefined' }
    ];
    
    let loadedCount = 0;
    const checkAllLoaded = setInterval(() => {
        dependencies.forEach(dep => {
            if (dep.check()) {
                dependencies = dependencies.filter(d => d !== dep);
                loadedCount++;
                console.log(`${dep.name} 已加载`);
            }
        });
        
        if (dependencies.length === 0 || loadedCount >= dependencies.length) {
            clearInterval(checkAllLoaded);
            callback();
        }
    }, 200);
    
    // 超时处理
    setTimeout(() => {
        clearInterval(checkAllLoaded);
        if (dependencies.length > 0) {
            console.warn('部分依赖加载超时，继续初始化:', 
                dependencies.map(d => d.name));
        }
        callback();
    }, 5000);
}

// 全局错误处理
window.addEventListener('error', function(e) {
    if (e.message.includes('marked is not defined')) {
        console.warn('检测到marked未定义，重新初始化渲染系统');
        initializeRenderingSystem();
        retryRenderingAllMessages();
    }
    // ...其他错误处理
    console.error('全局错误:', e.message, 'at', e.filename, e.lineno);
});

window.addEventListener('unhandledrejection', function(e) {
    console.error('未处理的Promise拒绝:', e.reason);
    e.preventDefault();
});

// 全局在线人数更新 - 用于所有页面
// 注意：此函数现在仅在非聊天页面使用，聊天页面的全局在线人数由base.html处理
function initializeGlobalOnlineCount() {
    // 不执行任何操作，因为全局在线人数现在由base.html统一管理
    // 避免重复更新导致冲突
    console.log('聊天页面的全局在线人数由base.html统一管理');
}

// 页面加载完成后自动初始化
document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('chat-messages')) {
        // 1. 首先确保渲染系统就绪
        waitForRenderSystem(() => {
            // 2. 确保所有依赖库加载
            ensureDependenciesLoaded(() => {
                // 3. 最后初始化聊天系统
                if (typeof window.initChat === 'function') {
                    window.initChat();
                } else {
                    console.error('initChat 函数未定义');
                }
            });
        });
    } else {
        // 如果不是聊天页面，仍然初始化全局在线人数更新
        initializeGlobalOnlineCount();
    }
});