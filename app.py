# App.py
import os
import time
import json
import sys
import shutil
import threading
from datetime import datetime
from pathlib import Path
import sqlite3
import logging
from flask import (
    Flask, render_template, request, redirect, url_for, 
    flash, session, send_from_directory, jsonify, abort,
    make_response
)
from flask_login import (
    LoginManager, UserMixin, login_user, 
    logout_user, current_user, login_required
)
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired, Length, EqualTo, Regexp
from flask_socketio import SocketIO, emit, join_room, leave_room
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session, relationship
from markupsafe import escape, Markup
import re
import html
from flask_cors import CORS
import logging
from logging.handlers import RotatingFileHandler
# 配置
from config import Config

# 初始化应用
app = Flask(__name__)
app.config.from_object(Config)

# 创建logs目录
log_dir = Path(app.root_path) / 'logs'
log_dir.mkdir(exist_ok=True)

# 配置日志
try:
    log_file = log_dir / 'system.log'
    
    # 确保新日志使用UTF-8
    handler = RotatingFileHandler(
        log_file, 
        maxBytes=10*1024*1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'  # 关键：强制使用UTF-8编码
    )
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    logger = logging.getLogger('social_platform')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    
    # 记录一条UTF-8编码的初始化日志
    logger.info("应用启动成功 - 使用UTF-8编码日志")
except Exception as e:
    print(f"配置日志失败: {str(e)}")
    # 备用方案
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('social_platform')

# 初始化数据库
engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])
Base = declarative_base()
db_session = scoped_session(sessionmaker(autocommit=False,
                                         autoflush=False,
                                         bind=engine))
app.teardown_appcontext(lambda exc: db_session.remove())

# 初始化Socket.IO
socketio = SocketIO(app, async_mode=app.config['SOCKETIO_ASYNC_MODE'], cors_allowed_origins='*')

# 初始化登录管理
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# 模型定义
class User(UserMixin, Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, index=True)
    password_hash = Column(String(128))
    nickname = Column(String(64), default='')
    color = Column(String(7), default='#000000')
    badge = Column(String(32), default='')
    last_seen = Column(DateTime, default=datetime.utcnow)
    role = Column(String(20), default='user')  # 新增权限字段：user, admin
    
    def is_admin(self):
        """检查用户是否为管理员"""
        return self.role == 'admin'
    
    def set_password(self, password):
        # 实际应用中应使用安全的哈希算法
        # 这里仅演示，实际应使用werkzeug.security.generate_password_hash
        self.password_hash = password
    
    def check_password(self, password):
        return self.password_hash == password

class ChatRoom(Base):
    __tablename__ = 'chat_rooms'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True)
    description = Column(Text)

class ChatMessage(Base):
    __tablename__ = 'chat_messages'
    
    id = Column(Integer, primary_key=True)
    content = Column(Text)  # 只存储原始Markdown
    timestamp = Column(DateTime, index=True, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey('users.id'))
    room_id = Column(Integer, ForeignKey('chat_rooms.id'))
    
    user = relationship('User', backref='chat_messages')
    room = relationship('ChatRoom', backref='messages')

class ForumSection(Base):
    __tablename__ = 'forum_sections'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True)
    description = Column(Text)

class ForumThread(Base):
    __tablename__ = 'forum_threads'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(128))
    content = Column(Text)  # 只存储原始Markdown
    timestamp = Column(DateTime, index=True, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey('users.id'))
    section_id = Column(Integer, ForeignKey('forum_sections.id'))
    
    user = relationship('User', backref='forum_threads')
    section = relationship('ForumSection', backref='threads')
    replies = relationship('ForumReply', backref='thread', lazy='dynamic')

class ForumReply(Base):
    __tablename__ = 'forum_replies'
    
    id = Column(Integer, primary_key=True)
    content = Column(Text)  # 只存储原始Markdown
    timestamp = Column(DateTime, index=True, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey('users.id'))
    thread_id = Column(Integer, ForeignKey('forum_threads.id'))
    
    user = relationship('User', backref='forum_replies')

# 创建表
Base.metadata.create_all(bind=engine)

# 检查并更新数据库结构
def update_database_schema():
    """检查并更新数据库结构，添加缺失的列"""
    try:
        conn = sqlite3.connect(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', ''))
        cursor = conn.cursor()
        
        # 检查用户表是否已有role列
        cursor.execute("PRAGMA table_info(users);")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'role' not in columns:
            # 添加role列，默认为'user'
            cursor.execute("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'user';")
            conn.commit()
            logger.info("已添加role列到users表")
        
        conn.close()
        logger.info("数据库结构更新完成")
    except Exception as e:
        logger.error(f"数据库结构更新失败: {str(e)}")

# 应用启动时更新数据库结构
update_database_schema()

# 用户加载函数
@login_manager.user_loader
def load_user(user_id):
    return db_session.query(User).get(int(user_id))
@app.context_processor
def inject_app_info():
    """将应用信息注入到所有模板中"""
    return {
        'app_info': {
            'debug': app.debug,
            'name': app.name,
            'config': app.config
        }
    }
# 表单定义
class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[
        DataRequired(message="用户名不能为空"),
        Length(min=3, max=64, message="用户名长度需在3-64字符之间")
    ])
    password = PasswordField('密码', validators=[
        DataRequired(message="密码不能为空")
    ])
    submit = SubmitField('登录')

class ChangePasswordForm(FlaskForm):
    old_password = PasswordField('当前密码', validators=[
        DataRequired(message="请输入当前密码")
    ])
    new_password = PasswordField('新密码', validators=[
        DataRequired(message="新密码不能为空"),
        Length(min=6, message="密码至少6个字符"),
        EqualTo('confirm_password', message='两次输入的密码必须一致')
    ])
    confirm_password = PasswordField('确认新密码', validators=[
        DataRequired(message="请确认新密码")
    ])
    submit = SubmitField('修改密码')

class ProfileForm(FlaskForm):
    nickname = StringField('昵称', validators=[
        Length(max=64, message="昵称不能超过64个字符")
    ])
    color = StringField('名字颜色', validators=[
        Regexp(r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$', message="颜色格式必须是#RGB或#RRGGBB")
    ])
    badge = StringField('徽章', validators=[
        Length(max=32, message="徽章不能超过32个字符")
    ])
    submit = SubmitField('保存设置')

# 全局工具函数
def sanitize_content(content):
    """基础XSS防护 - 仅允许安全的HTML标签"""
    if not content:
        return ""
    
    # 先HTML转义
    content = html.escape(content)
    
    # 允许的简单标签（Markdown会生成这些）
    allowed_tags = ['b', 'i', 'em', 'strong', 'code', 'pre', 'a', 'ul', 'ol', 'li', 'blockquote', 'br', 'hr']
    
    # 处理链接（仅允许http/https）
    content = re.sub(r'<a href=&quot;(https?://[^&quot;]+)&quot;>', 
                    lambda m: f'<a href="{escape(m.group(1))}" target="_blank" rel="noopener noreferrer">', 
                    content)
    
    return content

def get_online_users(room_id):
    """获取指定房间的在线用户（简化版）"""
    # 实际应用中应查询数据库中最近5分钟有活动的用户
    # 这里返回一个示例
    return [{
        'id': current_user.id,
        'username': current_user.username,
        'nickname': current_user.nickname or current_user.username,
        'color': current_user.color,
        'badge': current_user.badge
    }]

def get_recent_logs(limit=10):
    """获取最近的系统日志"""
    logs = []
    log_file = Path(app.root_path) / 'logs' / 'system.log'
    
    if log_file.exists():
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-limit:]
            for line in lines:
                try:
                    # 简化解析
                    parts = line.split(' ', 3)
                    if len(parts) >= 4:
                        timestamp_str = f"{parts[0]} {parts[1]}"
                        message = parts[3].strip()
                        # 移除日志级别和模块名
                        message = message.split(' - ', 2)[-1] if ' - ' in message else message
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')
                        logs.append(type('Log', (), {'timestamp': timestamp, 'message': message})())
                except Exception as e:
                    continue
    
    # 如果没有日志文件，创建一些模拟数据
    if not logs:
        for i in range(limit):
            logs.append(type('Log', (), {
                'timestamp': datetime.now(),
                'message': f"系统启动正常 - 模拟日志条目 {i+1}"
            })())
    
    return logs[:limit]

def log_admin_action(action):
    """记录管理员操作 - 安全版本"""
    try:
        log_dir = Path(app.root_path) / 'logs'
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / 'admin.log'
        
        with open(log_file, 'a', encoding='utf-8') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            # 安全检查：确保用户已认证
            if current_user and hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
                username = current_user.username
            else:
                username = 'system'  # 系统操作
            f.write(f"[{timestamp}] [管理员: {username}] {action}\n")
        
        # 同时记录到系统日志
        logger.info(f"管理员操作: {action}")
    except Exception as e:
        # 避免在错误处理中再次出错
        try:
            logger.error(f"记录管理员操作失败: {str(e)}")
        except Exception as e2:
            print(f"记录管理员操作失败(二次错误): {str(e2)}")

# 路由定义
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('chat_index'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('chat_index'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = db_session.query(User).filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('无效的用户名或密码', 'danger')
            return redirect(url_for('login'))
        
        login_user(user)
        user.last_seen = datetime.utcnow()
        db_session.commit()
        log_admin_action(f"用户登录: {user.username}")
        return redirect(url_for('chat_index'))
    
    return render_template('login.html', form=form)

@app.route('/logout')
def logout():
    username = current_user.username if current_user.is_authenticated else '未知用户'
    logout_user()
    log_admin_action(f"用户登出: {username}")
    flash('您已成功登出', 'success')
    return redirect(url_for('login'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.old_password.data):
            flash('当前密码错误', 'danger')
            return redirect(url_for('change_password'))
        
        current_user.set_password(form.new_password.data)
        db_session.commit()
        log_admin_action(f"用户修改密码: {current_user.username}")
        flash('密码已成功修改', 'success')
        return redirect(url_for('chat_index'))
    
    return render_template('change_password.html', form=form)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm()
    if form.validate_on_submit():
        current_user.nickname = form.nickname.data
        current_user.color = form.color.data or '#000000'
        current_user.badge = form.badge.data
        db_session.commit()
        log_admin_action(f"用户更新个人资料: {current_user.username}")
        flash('个人资料已更新', 'success')
        return redirect(url_for('profile'))
    elif request.method == 'GET':
        form.nickname.data = current_user.nickname
        form.color.data = current_user.color
        form.badge.data = current_user.badge
    
    return render_template('profile.html', form=form)

# 聊天相关路由
@app.route('/chat')
@login_required
def chat_index():
    rooms = db_session.query(ChatRoom).all()
    return render_template('chat/index.html', rooms=rooms)

@app.route('/chat/<int:room_id>')
@login_required
def chat_room(room_id):
    room = db_session.query(ChatRoom).get(room_id)
    if room is None:
        abort(404)
    return render_template('chat/room.html', room=room)

@app.route('/api/chat/<int:room_id>/history')
@login_required
def chat_history(room_id):
    """获取聊天历史消息 - 只返回原始Markdown内容"""
    limit = min(request.args.get('limit', 50, type=int), 100)
    offset = request.args.get('offset', 0, type=int)
    
    messages = db_session.query(ChatMessage).filter_by(room_id=room_id)\
        .order_by(ChatMessage.timestamp.desc()).limit(limit).offset(offset).all()
    
    # 转换为字典列表（只返回原始内容）
    messages_data = [{
        'id': msg.id,
        'content': msg.content,  # 原始Markdown内容
        'timestamp': msg.timestamp.isoformat(),
        'user_id': msg.user_id,
        'username': msg.user.username,
        'nickname': msg.user.nickname or msg.user.username,
        'color': msg.user.color,
        'badge': msg.user.badge
    } for msg in reversed(messages)]  # 反转以保持时间顺序
    
    return jsonify(messages=messages_data)

@app.route('/api/chat/send', methods=['POST'])
@login_required
def send_chat_message():
    room_id = request.form.get('room_id')
    message = request.form.get('message', '').strip()
    
    if not room_id or not message:
        return jsonify(success=False, message="参数错误"), 400
    
    # 保存到数据库
    message_obj = ChatMessage(
        content=message,
        user_id=current_user.id,
        room_id=room_id
    )
    db_session.add(message_obj)
    db_session.commit()
    
    # 返回成功响应
    return jsonify(success=True)

# 贴吧相关路由
@app.route('/forum')
@login_required
def forum_index():
    sections = db_session.query(ForumSection).all()
    return render_template('forum/index.html', sections=sections)

@app.route('/forum/section/<int:section_id>')
@login_required
def forum_section(section_id):
    section = db_session.query(ForumSection).get(section_id)
    if section is None:
        abort(404)
    threads = db_session.query(ForumThread).filter_by(section_id=section_id)\
        .order_by(ForumThread.timestamp.desc()).all()
    return render_template('forum/section.html', section=section, threads=threads)

@app.route('/forum/thread/<int:thread_id>')
@login_required
def forum_thread(thread_id):
    thread = db_session.query(ForumThread).get(thread_id)
    if thread is None:
        abort(404)
    replies = thread.replies.order_by(ForumReply.timestamp.asc()).all()
    return render_template('forum/thread.html', thread=thread, replies=replies)

@app.route('/forum/new/<int:section_id>', methods=['GET', 'POST'])
@login_required
def new_post(section_id):
    section = db_session.query(ForumSection).get(section_id)
    if section is None:
        abort(404)
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        
        # 基础验证
        if not title or len(title) > 128:
            return jsonify(success=False, message="标题不能为空且不超过128字符"), 400
        
        # 内容长度限制
        if not content or len(content) > 10000:
            return jsonify(success=False, message="内容不能为空且不超过10000字符"), 400
        
        # XSS基础防护
        content = sanitize_content(content)
        
        thread = ForumThread(
            title=title,
            content=content,  # 存储原始Markdown
            user_id=current_user.id,
            section_id=section_id
        )
        db_session.add(thread)
        db_session.commit()
        
        log_admin_action(f"用户创建新帖: {current_user.username} - {title}")
        return redirect(url_for('forum_thread', thread_id=thread.id))
    
    return render_template('forum/new_post.html', section=section)

@app.route('/api/forum/reply', methods=['POST'])
@login_required
def reply_post():
    thread_id = request.form.get('thread_id', type=int)
    content = request.form.get('content', '').strip()
    
    # 验证
    if not thread_id:
        return jsonify(success=False, message="参数错误"), 400
    
    if not content or len(content) > 5000:
        return jsonify(success=False, message="内容不能为空且不超过5000字符"), 400
    
    # XSS基础防护
    content = sanitize_content(content)
    
    thread = db_session.query(ForumThread).get(thread_id)
    if not thread:
        return jsonify(success=False, message="帖子不存在"), 404
    
    reply = ForumReply(
        content=content,  # 存储原始Markdown
        user_id=current_user.id,
        thread_id=thread_id
    )
    db_session.add(reply)
    db_session.commit()
    
    log_admin_action(f"用户回复帖子: {current_user.username} - 帖子ID: {thread_id}")
    # 只返回原始内容，前端负责渲染
    return jsonify(
        success=True,
        reply_id=reply.id,
        user_id=current_user.id,
        username=current_user.username,
        nickname=current_user.nickname or current_user.username,
        color=current_user.color,
        badge=current_user.badge,
        timestamp=reply.timestamp.isoformat(),
        content=reply.content  # 原始Markdown
    )

# 管理相关路由
@app.route('/admin')
@login_required
def admin_index():
    if not current_user.is_admin():  # 只有管理员才能访问
        abort(403)
    
    # 获取统计信息
    user_count = db_session.query(User).count()
    online_count = 1  # 简化实现，实际应查询最近活动的用户
    chat_messages_count = db_session.query(ChatMessage).count()
    forum_posts_count = db_session.query(ForumThread).count() + db_session.query(ForumReply).count()
    
    # 获取系统信息
    python_version = sys.version.split()[0]
    flask_version = '2.3.2'  # 实际应导入flask.__version__
    database_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
    
    # 获取最近日志
    recent_logs = get_recent_logs(10)
    
    return render_template('admin/index.html',
                         user_count=user_count,
                         online_count=online_count,
                         chat_messages_count=chat_messages_count,
                         forum_posts_count=forum_posts_count,
                         python_version=python_version,
                         flask_version=flask_version,
                         database_path=database_path,
                         recent_logs=recent_logs)

@app.route('/admin/users')
@login_required
def user_management():
    if not current_user.is_admin():
        abort(403)
    
    users = db_session.query(User).all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/chat')
@login_required
def chat_management():
    if not current_user.is_admin():
        abort(403)
    
    rooms = db_session.query(ChatRoom).all()
    return render_template('admin/chat.html', rooms=rooms)

@app.route('/admin/forum')
@login_required
def forum_management():
    if not current_user.is_admin():
        abort(403)
    
    sections = db_session.query(ForumSection).all()
    return render_template('admin/forum.html', sections=sections)

@app.route('/admin/file_manager')
@login_required
def file_manager_view():
    if not current_user.is_admin():
        abort(403)
    
    path = request.args.get('path', '')
    try:
        items = list_directory(path)
        return render_template('admin/file_manager.html', 
                              items=items, 
                              current_path=path)
    except Exception as e:
        flash(f'错误: {str(e)}', 'danger')
        return redirect(url_for('admin_index'))

@app.route('/admin/file_manager/read')
@login_required
def read_file_view():
    if not current_user.is_admin():
        abort(403)
    
    path = request.args.get('path', '')
    try:
        root = Path(__file__).parent
        full_path = (root / path).resolve()
        
        # 安全检查
        if not str(full_path).startswith(str(root)):
            raise ValueError("非法路径访问")
        
        if not full_path.exists() or full_path.is_dir():
            raise ValueError("文件不存在或为目录")
        
        # 限制文件大小
        if full_path.stat().st_size > 1024 * 1024:  # 1MB
            return jsonify(success=False, message="文件过大，无法在浏览器中编辑"), 400
        
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        log_admin_action(f"读取文件: {path}")
        return jsonify(success=True, content=content)
    except Exception as e:
        log_admin_action(f"读取文件失败: {path} - {str(e)}")
        return jsonify(success=False, message=str(e)), 400

@app.route('/admin/file_manager/write', methods=['POST'])
@login_required
def write_file_view():
    if not current_user.is_admin():
        abort(403)
    
    path = request.form.get('path', '')
    content = request.form.get('content', '')
    
    try:
        root = Path(__file__).parent
        full_path = (root / path).resolve()
        
        # 安全检查
        if not str(full_path).startswith(str(root)):
            raise ValueError("非法路径访问")
        
        # 限制文件类型
        disallowed_extensions = ['.pyc', '.db', '.sqlite', '.exe', '.bat', '.sh']
        if any(full_path.name.lower().endswith(ext) for ext in disallowed_extensions):
            raise ValueError(f"禁止修改此类文件: {full_path.name}")
        
        # 备份原文件
        backup_path = None
        if full_path.exists():
            backup_path = full_path.with_suffix(full_path.suffix + '.bak')
            shutil.copy2(full_path, backup_path)
        
        # 确保目录存在
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        log_admin_action(f"修改文件: {path}" + (f", 备份已创建: {backup_path}" if backup_path else ""))
        return jsonify(success=True, message="文件已保存")
    except Exception as e:
        log_admin_action(f"修改文件失败: {path} - {str(e)}")
        return jsonify(success=False, message=str(e)), 400

# API端点
@app.route('/api/admin/system-info')
@login_required
def get_system_info():
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        # 获取内存使用情况
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            memory_usage = f"{memory_info.rss / 1024 / 1024:.2f} MB"
        except ImportError:
            memory_usage = "psutil未安装"
        
        return jsonify({
            'success': True,
            'memory_usage': memory_usage,
            'server_time': datetime.now().isoformat(),
            'python_version': sys.version,
            'flask_version': '2.3.2'
        })
    except Exception as e:
        log_admin_action(f"获取系统信息失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': '获取系统信息失败',
            'error': str(e)
        }), 500

@app.route('/api/admin/clear-cache', methods=['POST'])
@login_required
def clear_cache():
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        # 清除数据库查询缓存
        db_session.expire_all()
        
        log_admin_action("管理员清除了系统缓存")
        return jsonify(success=True, message="缓存清除成功")
    except Exception as e:
        log_admin_action(f"清除缓存失败: {str(e)}")
        return jsonify(success=False, message=f"清除缓存失败: {str(e)}"), 500

@app.route('/api/admin/restart', methods=['POST'])
@login_required
def restart_server():
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        log_admin_action("管理员请求重启服务器")
        
        # 在新线程中重启服务器，给客户端响应
        def restart():
            time.sleep(2)  # 等待响应发送
            os._exit(0)  # 强制退出，由调试模式自动重启
        
        threading.Thread(target=restart).start()
        
        return jsonify(success=True, message="服务器正在重启")
    except Exception as e:
        log_admin_action(f"重启服务器失败: {str(e)}")
        return jsonify(success=False, message=f"重启服务器失败: {str(e)}"), 500

@app.route('/api/admin/backup-database', methods=['POST'])
@login_required
def backup_database():
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        db_path = Path(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', ''))
        backup_dir = Path(app.root_path) / 'backups'
        backup_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"backup_{timestamp}.db"
        backup_path = backup_dir / backup_name
        
        shutil.copy2(db_path, backup_path)
        
        log_admin_action(f"数据库备份成功: {backup_path}")
        return jsonify(success=True, message="数据库备份成功", backup_path=str(backup_path))
    except Exception as e:
        log_admin_action(f"数据库备份失败: {str(e)}")
        return jsonify(success=False, message=f"数据库备份失败: {str(e)}"), 500

@app.route('/api/admin/system-log')
@login_required
def get_system_log():
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        logs = get_recent_logs(50)
        return jsonify({
            'success': True,
            'logs': [{
                'timestamp': log.timestamp.isoformat(),
                'message': log.message
            } for log in logs]
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f"获取系统日志失败: {str(e)}"
        }), 500

@app.route('/api/admin/optimize-database', methods=['POST'])
@login_required
def optimize_database():
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("VACUUM")
        conn.commit()
        conn.close()
        
        log_admin_action("数据库优化成功")
        return jsonify(success=True, message="数据库优化成功")
    except Exception as e:
        log_admin_action(f"数据库优化失败: {str(e)}")
        return jsonify(success=False, message=f"数据库优化失败: {str(e)}"), 500

@app.route('/api/admin/shutdown', methods=['POST'])
@login_required
def shutdown_server():
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        data = request.get_json()
        reason = data.get('reason', '未指定原因')
        
        log_admin_action(f"服务器关停，原因: {reason}")
        
        # 在新线程中关闭服务器
        def shutdown():
            time.sleep(2)
            os._exit(0)
        
        threading.Thread(target=shutdown).start()
        
        return jsonify(success=True, message="服务器正在关停", reason=reason)
    except Exception as e:
        log_admin_action(f"关停服务器失败: {str(e)}")
        return jsonify(success=False, message=f"关停服务器失败: {str(e)}"), 500

# 用户管理相关路由
@app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@login_required
def update_user(user_id):
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        user = db_session.query(User).get(user_id)
        if not user:
            return jsonify(success=False, message="用户不存在"), 404
        
        data = request.get_json()
        if 'username' in data and data['username']:
            user.username = data['username']
        if 'nickname' in data and data['nickname']:
            user.nickname = data['nickname']
        if 'color' in data and data['color']:
            user.color = data['color']
        if 'badge' in data and data['badge']:
            user.badge = data['badge']
        
        db_session.commit()
        log_admin_action(f"更新了用户 {user.username} 的信息")
        return jsonify(success=True, message="用户信息更新成功")
    except Exception as e:
        return jsonify(success=False, message=f"更新用户失败: {str(e)}"), 500

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        user = db_session.query(User).get(user_id)
        if not user:
            return jsonify(success=False, message="用户不存在"), 404
        
        if user.id == 1:
            return jsonify(success=False, message="不能删除超级管理员"), 400
        
        # 删除用户相关数据
        db_session.query(ChatMessage).filter_by(user_id=user_id).delete()
        db_session.query(ForumThread).filter_by(user_id=user_id).delete()
        db_session.query(ForumReply).filter_by(user_id=user_id).delete()
        
        db_session.delete(user)
        db_session.commit()
        
        log_admin_action(f"删除了用户 {user.username}")
        return jsonify(success=True, message="用户删除成功")
    except Exception as e:
        return jsonify(success=False, message=f"删除用户失败: {str(e)}"), 500

# 聊天管理相关路由
@app.route('/api/admin/chat/rooms/<int:room_id>', methods=['PUT'])
@login_required
def update_chat_room(room_id):
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        room = db_session.query(ChatRoom).get(room_id)
        if not room:
            return jsonify(success=False, message="聊天室不存在"), 404
        
        data = request.get_json()
        if 'name' in data and data['name']:
            room.name = data['name']
        if 'description' in data:
            room.description = data['description']
        
        db_session.commit()
        log_admin_action(f"更新了聊天室 {room.name} 的信息")
        return jsonify(success=True, message="聊天室信息更新成功")
    except Exception as e:
        return jsonify(success=False, message=f"更新聊天室失败: {str(e)}"), 500

@app.route('/api/admin/chat/rooms/<int:room_id>', methods=['DELETE'])
@login_required
def delete_chat_room(room_id):
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        room = db_session.query(ChatRoom).get(room_id)
        if not room:
            return jsonify(success=False, message="聊天室不存在"), 404
        
        if room.id == 1:  # 保护默认聊天室
            return jsonify(success=False, message="不能删除默认聊天室"), 400
        
        # 删除聊天室消息
        db_session.query(ChatMessage).filter_by(room_id=room_id).delete()
        
        db_session.delete(room)
        db_session.commit()
        
        log_admin_action(f"删除了聊天室 {room.name}")
        return jsonify(success=True, message="聊天室删除成功")
    except Exception as e:
        return jsonify(success=False, message=f"删除聊天室失败: {str(e)}"), 500

@app.route('/api/admin/chat/messages', methods=['DELETE'])
@login_required
def clear_chat_messages():
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        room_id = request.args.get('room_id', type=int)
        before_date = request.args.get('before')
        
        query = db_session.query(ChatMessage)
        
        if room_id:
            query = query.filter_by(room_id=room_id)
        
        if before_date:
            try:
                before_dt = datetime.fromisoformat(before_date)
                query = query.filter(ChatMessage.timestamp < before_dt)
            except:
                pass
        
        count = query.delete()
        db_session.commit()
        
        log_admin_action(f"清除了 {count} 条聊天消息")
        return jsonify(success=True, message=f"成功清除了 {count} 条聊天消息", count=count)
    except Exception as e:
        return jsonify(success=False, message=f"清除聊天消息失败: {str(e)}"), 500

@app.route('/api/admin/users/<int:user_id>/role', methods=['PUT'])
@login_required
def update_user_role(user_id):
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        user = db_session.query(User).get(user_id)
        if not user:
            return jsonify(success=False, message="用户不存在"), 404
        
        data = request.get_json()
        new_role = data.get('role', '').lower()
        
        if new_role not in ['user', 'admin']:
            return jsonify(success=False, message="角色必须是 'user' 或 'admin'"), 400
        
        # 防止降级超级管理员（ID为1的用户）
        if user.id == 1 and new_role != 'admin':
            return jsonify(success=False, message="不能修改超级管理员的角色"), 400
        
        old_role = user.role
        user.role = new_role
        db_session.commit()
        
        log_admin_action(f"修改用户 {user.username} 的角色: {old_role} -> {new_role}")
        return jsonify(success=True, message=f"用户 {user.username} 的角色已更新为 {new_role}")
    except Exception as e:
        logger.error(f"更新用户角色失败: {str(e)}")
        return jsonify(success=False, message=f"更新用户角色失败: {str(e)}"), 500

# 贴吧管理相关路由
@app.route('/api/admin/forum/sections/<int:section_id>', methods=['PUT'])
@login_required
def update_forum_section(section_id):
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
        section = db_session.query(ForumSection).get(section_id)
        if not section:
            return jsonify(success=False, message="贴吧分区不存在"), 404
        
        data = request.get_json()
        if 'name' in data and data['name']:
            section.name = data['name']
        if 'description' in data and data['description']:
            section.description = data['description']
        
        db_session.commit()
        log_admin_action(f"更新了贴吧分区 {section.name} 的信息")
        return jsonify(success=True, message="贴吧分区信息更新成功")
    except Exception as e:
        return jsonify(success=False, message=f"更新贴吧分区失败: {str(e)}"), 500

@app.route('/api/admin/forum/sections/<int:section_id>', methods=['DELETE'])
@login_required
def delete_forum_section(section_id):
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        section = db_session.query(ForumSection).get(section_id)
        if not section:
            return jsonify(success=False, message="贴吧分区不存在"), 404
        
        if section.id == 1:  # 保护默认分区
            return jsonify(success=False, message="不能删除默认贴吧分区"), 400
        
        # 删除分区下的帖子和回复
        threads = db_session.query(ForumThread).filter_by(section_id=section_id).all()
        for thread in threads:
            db_session.query(ForumReply).filter_by(thread_id=thread.id).delete()
        
        db_session.query(ForumThread).filter_by(section_id=section_id).delete()
        db_session.delete(section)
        db_session.commit()
        
        log_admin_action(f"删除了贴吧分区 {section.name}")
        return jsonify(success=True, message="贴吧分区删除成功")
    except Exception as e:
        return jsonify(success=False, message=f"删除贴吧分区失败: {str(e)}"), 500

@app.route('/api/admin/forum/posts/<int:post_id>', methods=['DELETE'])
@login_required
def delete_forum_post(post_id):
    if not current_user.is_admin():
        return jsonify(success=False, message="权限不足"), 403
    
    try:
        # 检查是主题帖还是回复
        thread = db_session.query(ForumThread).get(post_id)
        if thread:
            # 删除主题帖及其所有回复
            db_session.query(ForumReply).filter_by(thread_id=thread.id).delete()
            db_session.delete(thread)
            message = f"删除了贴吧主题帖: {thread.title}"
        else:
            reply = db_session.query(ForumReply).get(post_id)
            if not reply:
                return jsonify(success=False, message="帖子或回复不存在"), 404
            db_session.delete(reply)
            message = "删除了贴吧回复"
        
        db_session.commit()
        log_admin_action(message)
        return jsonify(success=True, message="删除成功")
    except Exception as e:
        return jsonify(success=False, message=f"删除失败: {str(e)}"), 500

# 文件管理工具函数
def list_directory(path):
    """列出目录内容（安全版）"""
    root = Path(__file__).parent
    full_path = (root / path).resolve()
    
    # 安全检查
    if not str(full_path).startswith(str(root)):
        raise ValueError("非法路径访问")
    
    if not full_path.exists() or not full_path.is_dir():
        raise ValueError("目录不存在")
    
    items = []
    for item in full_path.iterdir():
        # 跳过隐藏文件和特定目录
        if item.name.startswith('.') or item.name in ['__pycache__', 'logs', 'backups']:
            continue
        
        rel_path = item.relative_to(root)
        items.append({
            'name': item.name,
            'is_dir': item.is_dir(),
            'path': str(rel_path),
            'size': item.stat().st_size if item.is_file() else 0
        })
    
    return items

# Socket.IO 事件处理
@socketio.on('connect')
def handle_connect():
    """用户连接"""
    if not current_user.is_authenticated:
        return False  # 拒绝未认证用户
    
    if current_user.is_authenticated:
        current_user.last_seen = datetime.utcnow()
        db_session.commit()
    
    session['receive_count'] = session.get('receive_count', 0) + 1
    emit('my_response', {'count': session['receive_count']})

@socketio.on('join')
def on_join(data):
    """加入聊天室"""
    if not current_user.is_authenticated:
        return
    
    room_id = data.get('room')
    if not room_id:
        return
    
    room_name = f"room_{room_id}"
    join_room(room_name)
    
    # 更新在线状态
    current_user.last_seen = datetime.utcnow()
    db_session.commit()
    
    # 广播用户加入
    emit('status', {
        'msg': f'{current_user.nickname or current_user.username} 加入了聊天室',
        'user_id': current_user.id
    }, room=room_name)

@socketio.on('leave')
def on_leave(data):
    """离开聊天室"""
    if not current_user.is_authenticated:
        return
    
    room_id = data.get('room')
    if not room_id:
        return
    
    room_name = f"room_{room_id}"
    leave_room(room_name)
    
    # 广播用户离开
    emit('status', {
        'msg': f'{current_user.nickname or current_user.username} 离开了聊天室',
        'user_id': current_user.id
    }, room=room_name)

@socketio.on('send_message')
def handle_message(data):
    """处理发送消息"""
    if not current_user.is_authenticated:
        return
    
    room_id = data.get('room_id')
    content = data.get('message', '').strip()
    
    # 验证
    if not room_id or not content:
        emit('error', {'message': '参数错误'})
        return
    
    # 内容长度限制
    if len(content) > 2000:
        emit('error', {'message': '消息过长'})
        return
    
    # XSS基础防护
    content = sanitize_content(content)
    
    # 保存到数据库
    message = ChatMessage(
        content=content,  # 存储原始Markdown
        user_id=current_user.id,
        room_id=room_id
    )
    db_session.add(message)
    db_session.commit()
    
    # 发送消息给房间内所有人
    room_name = f"room_{room_id}"
    emit('message', {
        'id': message.id,
        'content': message.content,  # 原始Markdown
        'timestamp': message.timestamp.isoformat(),
        'user_id': current_user.id,
        'username': current_user.username,
        'nickname': current_user.nickname or current_user.username,
        'color': current_user.color,
        'badge': current_user.badge
    }, room=room_name)

@socketio.on('get_online_users')
def handle_get_online_users(data):
    """获取在线用户列表"""
    if not current_user.is_authenticated:
        return
    
    room_id = data.get('room_id')
    if not room_id:
        return
    
    # 获取在线用户（简化版）
    online_users = get_online_users(room_id)
    
    emit('online_users', {'users': online_users})

# 全局上下文处理器
@app.context_processor
def inject_user():
    """注入当前用户信息到模板"""
    return dict(current_user=current_user)

@app.context_processor
def inject_online_count():
    """注入在线用户数到模板"""
    # 实际应用中应该查询数据库
    return dict(online_count=1)  # 仅示例

# 错误处理
@app.errorhandler(403)
def forbidden(error):
    return render_template('errors/403.html'), 403

@app.errorhandler(404)
def not_found(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def server_error(error):
    return render_template('errors/500.html'), 500

# 初始化数据
def init_db():
    """初始化数据库"""
    # 创建默认用户（ID=1）
    admin = db_session.query(User).filter_by(id=1).first()
    if not admin:
        admin = User(
            id=1,
            username='admin',
            nickname='WTX',
            color='#ff0000',
            badge='ADMIN'
        )
        admin.set_password('admin')
        db_session.add(admin)
    
    # 创建默认聊天室
    if not db_session.query(ChatRoom).filter_by(name='公共聊天室').first():
        room = ChatRoom(
            name='公共聊天室',
            description='欢迎来到公共聊天室'
        )
        db_session.add(room)
    
    # 创建默认贴吧分区
    if not db_session.query(ForumSection).filter_by(name='公告区').first():
        section = ForumSection(
            name='公告区',
            description='系统公告和重要通知'
        )
        db_session.add(section)
    
    db_session.commit()
    log_admin_action("数据库初始化完成")

# 主程序
if __name__ == '__main__':
    init_db()
    CORS(app, resources={r"/socket.io/*": {"origins": "*"}})
    logger.info("应用启动成功")
    socketio.run(app, debug=app.config['DEBUG'])