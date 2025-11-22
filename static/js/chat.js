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

// 全局变量 - 需要从页面数据获取
var currentUsername = '用户';
var currentNickname = '用户';
var currentUserColor = '#000000';
var currentUserBadge = '';
var currentUserId = 0;

// 等待渲染系统就绪
function waitForRenderReady(callback) {
    if (typeof window.renderContent === 'function') {
        callback();
        return;
    }
    
    if (renderRetryCount >= MAX_RENDER_RETRY) {
        console.error('渲染系统初始化失败，使用降级方案');
        window.renderContent = function(content) {
            return '<pre class="plaintext-render">' + 
                   content.replace(/[<>&]/g, function(c) {
                       return {'<': '<', '>': '>', '&': '&amp;'}[c];
                   }) + 
                   '</pre>';
        };
        callback();
        return;
    }
    
    renderRetryCount++;
    setTimeout(function() {
        waitForRenderReady(callback);
    }, 1000);
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
            chatSocket.emit('join', {room: roomId});
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
            addMessageToUI(data);
        });
        
        chatSocket.on('status', (data) => {
            addStatusMessage(data.msg);
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
    
    // 清空输入框
    messageInput.value = '';
    
    // 通过WebSocket发送
    if (chatSocket && chatSocket.connected) {
        // 本地预览
        const localMessage = {
            id: 'temp-' + Date.now(),
            content: message,
            timestamp: new Date().toISOString(),
            user_id: currentUserId,
            username: currentUsername,
            nickname: currentNickname,
            color: currentUserColor,
            badge: currentUserBadge
        };
        
        addMessageToUI(localMessage, true);
        
        chatSocket.emit('send_message', {
            room_id: roomId,
            message: message
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
    
    // 检查是否已经处理过这个消息（避免重复显示）
    if (msg.id && processedMessageIds.has(msg.id)) {
        return;
    }
    
    // 添加到已处理集合
    if (msg.id) {
        processedMessageIds.add(msg.id);
    }
    
    // 创建消息元素
    const messageElement = createMessageElement(msg, isLocal);
    
    // 添加到容器
    messagesContainer.appendChild(messageElement);
    
    // 滚动到底部
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// 添加状态消息
function addStatusMessage(msg) {
    const messagesContainer = document.getElementById('chat-messages');
    if (!messagesContainer) return;
    
    const statusElement = document.createElement('div');
    statusElement.className = 'chat-status';
    statusElement.textContent = msg;
    
    messagesContainer.appendChild(statusElement);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// 创建消息元素
function createMessageElement(msg, isLocal = false) {
    const messageElement = document.createElement('div');
    messageElement.className = `chat-message ${isLocal ? 'local-message' : ''}`;
    
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
    const date = new Date(msg.timestamp);
    timeElement.textContent = date.toLocaleTimeString();
    userElement.appendChild(timeElement);
    
    // 消息内容
    const contentElement = document.createElement('div');
    contentElement.className = 'message-content';
    
    // 等待渲染系统就绪
    if (isRenderingReady) {
        try {
            contentElement.innerHTML = window.renderContent(msg.content);
        } catch (e) {
            console.error('消息渲染失败:', e);
            contentElement.innerHTML = `<div class="render-error">${escapeHtml(msg.content)}</div>`;
        }
    } else {
        // 渲染系统未就绪，加入队列
        messageQueue.push({element: contentElement, content: msg.content});
    }
    
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

// HTML转义
function escapeHtml(unsafe) {
    if (!unsafe) return '';
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "<")
        .replace(/>/g, ">")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
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
        
        // 设置在线人数
        const onlineCountElement = document.getElementById('online-count');
        if (onlineCountElement) {
            onlineCountElement.textContent = '加载中...';
        }
        
        // 设置模态框
        setupModal();
        
        // 加载历史消息
        loadChatHistory();
        
        // 连接WebSocket
        setupWebSocket();
        
        // 设置发送按钮事件
        setupMessageInput();
        
        // 监听渲染就绪事件
        document.addEventListener('renderReady', function() {
            isRenderingReady = true;
            processMessageQueue();
        });
        
        // 检查是否已经就绪
        if (typeof window.renderContent === 'function') {
            isRenderingReady = true;
        }
        
        console.log('聊天系统初始化完成');
    } catch (e) {
        console.error('聊天室初始化失败:', e);
    }
};

// 全局错误处理
window.addEventListener('error', function(e) {
    console.error('全局错误:', e.message, 'at', e.filename, e.lineno);
});

window.addEventListener('unhandledrejection', function(e) {
    console.error('未处理的Promise拒绝:', e.reason);
    e.preventDefault();
});

// 页面加载完成后自动初始化
document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('chat-messages')) {
        waitForRenderReady(function() {
            if (typeof window.initChat === 'function') {
                window.initChat();
            } else {
                console.error('initChat 函数未定义');
            }
        });
    }
});