#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import logging
import socket
import random
import string
import shutil
import json
from datetime import datetime
from flask import Flask, request, render_template, send_file, jsonify, session, Response
from werkzeug.utils import secure_filename
import pymysql
from pymysql.cursors import DictCursor
from functools import wraps
from urllib.parse import quote
# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('flask_upload.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 创建 Flask 应用
app = Flask(__name__)
app.secret_key = os.urandom(24)

# 配置文件上传参数
BASE_UPLOAD_FOLDER = '/root/flask_file_upload/uploads'
EXTERNAL_UPLOAD_FOLDER = '/mnt/uploads'

app.config['UPLOAD_FOLDER'] = BASE_UPLOAD_FOLDER
app.config['EXTERNAL_UPLOAD_FOLDER'] = EXTERNAL_UPLOAD_FOLDER


# 大文件下载优化配置
class LargeFileConfig:
    CHUNK_SIZE = 64 * 1024  # 64KB 块大小，减少内存使用
    STREAM_BUFFER_SIZE = 8192
    MAX_MEMORY_USAGE = 500 * 1024 * 1024  # 500MB 最大内存使用
    DOWNLOAD_TIMEOUT = 3600  # 1小时超时


# 存储配置
app.config['DUAL_STORAGE_THRESHOLD'] = 100 * 1024 * 1024  # 100MB
app.config['IMPORTANT_EXTENSIONS'] = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt']
app.config['MIN_FREE_SPACE'] = 1 * 1024 * 1024 * 1024  # 最小剩余空间1GB

# 子分类配置
app.config['SUBCATEGORIES'] = {
    'mirror': '镜像文件',
    'image': '图片文件',
    'document': '文档文件',
    'video': '视频文件',
    'other': '其他文件'
}

# 文件扩展名到子分类的映射
app.config['EXTENSION_MAPPING'] = {
    'mirror': ['.iso', '.img', '.vmdk', '.ova', '.qcow2'],
    'image': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp'],
    'document': ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.md'],
    'video': ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv', '.webm']
}

# 用户组权限配置
app.config['USER_GROUPS'] = {
    'root2': {
        'name': '超级管理员',
        'permissions': ['upload', 'download', 'delete', 'user_management', 'rename_files', 'change_subcategory']
    },
    'root': {
        'name': '管理员',
        'permissions': ['upload', 'download', 'delete', 'rename_files', 'change_subcategory']
    },
    'competition': {
        'name': '比赛用户',
        'permissions': ['upload', 'download', 'rename_files', 'change_subcategory']
    },
    'other': {
        'name': '普通用户',
        'permissions': ['download']
    }
}

# 存储目录
app.config['EVERYONE_FOLDERS'] = {
    'primary': os.path.join(BASE_UPLOAD_FOLDER, 'everyone'),
    'external': os.path.join(EXTERNAL_UPLOAD_FOLDER, 'everyone')
}

app.config['COMPETITION_FOLDERS'] = {
    'primary': os.path.join(BASE_UPLOAD_FOLDER, 'competition'),
    'external': os.path.join(EXTERNAL_UPLOAD_FOLDER, 'competition')
}

app.config['MAX_CONTENT_LENGTH'] = 70 * 1024 * 1024 * 1024
app.config['CHUNK_SIZE'] = 100 * 1024 * 1024


def init_subcategory_directories():
    """初始化子分类目录"""
    logger.info("开始初始化子分类目录")
    for category in ['everyone', 'competition']:
        for subcategory in app.config['SUBCATEGORIES'].keys():
            # 主存储目录
            primary_path = os.path.join(
                app.config[f'{category.upper()}_FOLDERS']['primary'],
                subcategory
            )
            # 外部存储目录
            external_path = os.path.join(
                app.config[f'{category.upper()}_FOLDERS']['external'],
                subcategory
            )

            os.makedirs(primary_path, exist_ok=True)
            os.makedirs(external_path, exist_ok=True)
            logger.info(f"创建目录: {primary_path}")
            logger.info(f"创建目录: {external_path}")


# 确保所有目录存在
try:
    for folders in [app.config['EVERYONE_FOLDERS'], app.config['COMPETITION_FOLDERS']]:
        for folder_path in folders.values():
            os.makedirs(folder_path, exist_ok=True)
    os.makedirs(os.path.join(BASE_UPLOAD_FOLDER, 'temp'), exist_ok=True)

    # 初始化子分类目录
    init_subcategory_directories()

    logger.info("所有目录创建成功")
except Exception as e:
    logger.error(f"目录创建失败: {str(e)}")

# 数据库配置
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'Key-1122',
    'db': 'file_manager',
    'charset': 'utf8mb4',
    'cursorclass': DictCursor
}


# ========== 权限检查装饰器 ==========
def permission_required(permission):
    """权限检查装饰器"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('logged_in'):
                return jsonify({'error': '需要登录'}), 401

            user_group = session.get('user_group', 'other')
            user_permissions = app.config['USER_GROUPS'].get(user_group, {}).get('permissions', [])

            if permission not in user_permissions:
                return jsonify({'error': '权限不足'}), 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def root2_required(f):
    """root2组权限检查装饰器"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': '需要登录'}), 401

        if session.get('user_group') != 'root2':
            return jsonify({'error': '需要超级管理员权限'}), 403

        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """管理员权限检查装饰器（root2或root组）"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': '需要登录'}), 401

        user_group = session.get('user_group')
        if user_group not in ['root2', 'root']:
            return jsonify({'error': '需要管理员权限'}), 403

        return f(*args, **kwargs)

    return decorated_function


def file_management_required(f):
    """文件管理权限检查装饰器（root2、root、competition组）"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': '需要登录'}), 401

        user_group = session.get('user_group')
        if user_group not in ['root2', 'root', 'competition']:
            return jsonify({'error': '需要文件管理权限'}), 403

        return f(*args, **kwargs)

    return decorated_function


# ========== 数据库相关函数 ==========
def get_db_connection():
    """获取数据库连接"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"获取数据库连接失败: {str(e)}")
        raise


def init_database():
    """初始化数据库表结构（只在表不存在时创建）"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 创建用户表（如果不存在）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    password VARCHAR(255) NOT NULL,
                    email VARCHAR(255),
                    user_group ENUM('root2', 'root', 'competition', 'other') DEFAULT 'other',
                    chinese_alias VARCHAR(255),  -- 新增中文别名字段
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 创建文件夹表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS folders (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    path VARCHAR(500) NOT NULL UNIQUE,
                    created_by INT NOT NULL,
                    created_username VARCHAR(100) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    allowed_groups JSON NOT NULL,
                    is_visible_to_all BOOLEAN DEFAULT FALSE,
                    creator_group ENUM('root2', 'root', 'competition', 'other') DEFAULT 'other',
                    FOREIGN KEY (created_by) REFERENCES users(id)
                )
            """)

            # 创建文件信息表（如果不存在）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_info (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    stored_filename VARCHAR(255) NOT NULL UNIQUE,
                    original_filename VARCHAR(255) NOT NULL,
                    file_size BIGINT NOT NULL,
                    upload_time DATETIME NOT NULL,
                    upload_user_id INT NOT NULL,
                    upload_username VARCHAR(100) NOT NULL,
                    download_count INT DEFAULT 0,
                    file_category ENUM('everyone', 'competition') DEFAULT 'competition',
                    file_subcategory VARCHAR(50) DEFAULT 'other',
                    storage_type ENUM('dual', 'external_only', 'external_with_link', 'primary_only') DEFAULT 'dual',
                    folder_id INT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (upload_user_id) REFERENCES users(id),
                    FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL
                )
            """)

            # 创建下载日志表（如果不存在）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS download_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    file_id INT NOT NULL,
                    user_id INT NOT NULL,
                    username VARCHAR(100) NOT NULL,
                    download_time DATETIME NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 检查默认管理员用户是否存在，不存在则创建


            conn.commit()
            logger.info("数据库表结构初始化成功")
    except Exception as e:
        logger.error(f"数据库表结构初始化失败: {str(e)}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()


def test_database_connection():
    """测试数据库连接"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        conn.close()
        logger.info("数据库连接测试成功")
        return True
    except Exception as e:
        logger.error(f"数据库连接失败: {str(e)}")
        return False


# ========== 存储相关函数 ==========
def check_disk_space(path):
    """检查指定路径的磁盘空间"""
    try:
        stat = os.statvfs(path)
        free_space = stat.f_frsize * stat.f_bavail  # 可用空间（字节）
        return free_space
    except Exception as e:
        logger.error(f"检查磁盘空间错误 {path}: {str(e)}")
        return 0


def get_available_storage_locations(file_size, category, subcategory='other'):
    """获取可用的存储位置（考虑子分类目录）"""
    locations = []

    # 检查外部存储空间
    external_folder = os.path.join(
        app.config['EVERYONE_FOLDERS']['external'] if category == 'everyone' else app.config['COMPETITION_FOLDERS'][
            'external'],
        subcategory
    )
    external_free = check_disk_space(external_folder)

    if external_free > file_size + app.config['MIN_FREE_SPACE']:
        locations.append('external')
        logger.info(f"外部存储可用: {external_free / (1024 * 1024 * 1024):.2f} GB 剩余 (子分类: {subcategory})")
    else:
        logger.warning(
            f"外部存储空间不足: {external_free / (1024 * 1024 * 1024):.2f} GB 剩余，需要 {file_size / (1024 * 1024 * 1024):.2f} GB (子分类: {subcategory})")

    # 检查主存储空间
    primary_folder = os.path.join(
        app.config['EVERYONE_FOLDERS']['primary'] if category == 'everyone' else app.config['COMPETITION_FOLDERS'][
            'primary'],
        subcategory
    )
    primary_free = check_disk_space(primary_folder)

    if primary_free > file_size + app.config['MIN_FREE_SPACE']:
        locations.append('primary')
        logger.info(f"主存储可用: {primary_free / (1024 * 1024 * 1024):.2f} GB 剩余 (子分类: {subcategory})")
    else:
        logger.warning(
            f"主存储空间不足: {primary_free / (1024 * 1024 * 1024):.2f} GB 剩余，需要 {file_size / (1024 * 1024 * 1024):.2f} GB (子分类: {subcategory})")

    return locations


def get_file_paths(stored_filename, category, subcategory='other'):
    """根据文件名、分类和子分类获取所有存储路径"""
    if category == 'everyone':
        return {
            'primary': os.path.join(app.config['EVERYONE_FOLDERS']['primary'], subcategory, stored_filename),
            'external': os.path.join(app.config['EVERYONE_FOLDERS']['external'], subcategory, stored_filename)
        }
    else:
        return {
            'primary': os.path.join(app.config['COMPETITION_FOLDERS']['primary'], subcategory, stored_filename),
            'external': os.path.join(app.config['COMPETITION_FOLDERS']['external'], subcategory, stored_filename)
        }


def get_any_existing_file_path(stored_filename, category, subcategory='other'):
    """获取任何存在的文件路径（增强版本）"""
    try:
        logger.info(f"🔍 开始查找文件: {stored_filename}, 分类: {category}, 子分类: {subcategory}")

        # 新路径（有子分类）
        new_paths = get_file_paths(stored_filename, category, subcategory)

        # 旧路径（无子分类） - 兼容性支持
        old_paths = {}
        if category == 'everyone':
            old_paths = {
                'primary': os.path.join(app.config['EVERYONE_FOLDERS']['primary'], stored_filename),
                'external': os.path.join(app.config['EVERYONE_FOLDERS']['external'], stored_filename)
            }
        else:
            old_paths = {
                'primary': os.path.join(app.config['COMPETITION_FOLDERS']['primary'], stored_filename),
                'external': os.path.join(app.config['COMPETITION_FOLDERS']['external'], stored_filename)
            }

        # 检查所有可能的路径
        all_paths = []

        # 新路径
        for location in ['external', 'primary']:
            path = new_paths[location]
            all_paths.append(('新路径', location, path))

        # 旧路径
        for location in ['external', 'primary']:
            path = old_paths[location]
            all_paths.append(('旧路径', location, path))

        # 检查所有路径
        found_path = None
        for path_type, location, path in all_paths:
            logger.info(f"检查{path_type} {location}: {path}")
            if os.path.exists(path):
                logger.info(f"✅ 文件在{path_type} {location}找到: {path}")
                found_path = path
                break

        if not found_path:
            # 尝试模糊匹配
            logger.warning(f"精确匹配失败，尝试模糊匹配: {stored_filename}")
            fuzzy_path = find_file_by_fuzzy_match(stored_filename, category, subcategory)
            if fuzzy_path:
                logger.info(f"✅ 通过模糊匹配找到文件: {fuzzy_path}")
                found_path = fuzzy_path

        if not found_path:
            logger.error(f"❌ 文件不存在: {stored_filename}")
            for path_type, location, path in all_paths:
                logger.error(f"检查过的路径 - {path_type} {location}: {path}")

        return found_path

    except Exception as e:
        logger.error(f"获取文件路径失败: {str(e)}")
        return None


def find_file_by_fuzzy_match(stored_filename, category, subcategory='other'):
    """通过模糊匹配查找文件（处理拼写错误）"""
    try:
        # 获取基础目录
        if category == 'everyone':
            base_dirs = [
                app.config['EVERYONE_FOLDERS']['primary'],
                app.config['EVERYONE_FOLDERS']['external']
            ]
        else:
            base_dirs = [
                app.config['COMPETITION_FOLDERS']['primary'],
                app.config['COMPETITION_FOLDERS']['external']
            ]

        # 可能的子分类目录
        subcategories = list(app.config['SUBCATEGORIES'].keys()) + ['']

        for base_dir in base_dirs:
            for subcat in subcategories:
                search_dir = os.path.join(base_dir, subcat) if subcat else base_dir
                if not os.path.exists(search_dir):
                    continue

                # 列出目录中的所有文件
                for filename in os.listdir(search_dir):
                    file_path = os.path.join(search_dir, filename)
                    if os.path.isfile(file_path):
                        # 简单的模糊匹配：检查文件名是否包含关键部分
                        if ('network' in filename.lower() and 'zip' in filename.lower() and
                                'network' in stored_filename.lower()):
                            logger.info(f"模糊匹配成功: {filename} -> {stored_filename}")
                            return file_path
                        # 检查常见的拼写错误模式
                        if (stored_filename.replace('world', 'work') in filename or
                                stored_filename.replace('work', 'world') in filename):
                            logger.info(f"拼写错误纠正: {filename} -> {stored_filename}")
                            return file_path

        return None
    except Exception as e:
        logger.error(f"模糊匹配失败: {str(e)}")
        return None


def get_unique_filename(filename, category, subcategory='other'):
    """生成唯一文件名，重名时在两个位置检查"""
    name, ext = os.path.splitext(filename)

    if category == 'everyone':
        folders = app.config['EVERYONE_FOLDERS']
    else:
        folders = app.config['COMPETITION_FOLDERS']

    candidate = f"{name}{ext}"

    def file_exists_in_any_location(candidate_name):
        for folder_path in folders.values():
            file_path = os.path.join(folder_path, subcategory, candidate_name)
            if os.path.exists(file_path):
                return True
        return False

    counter = 1
    while file_exists_in_any_location(candidate):
        candidate = f"{name}_{counter}{ext}"
        counter += 1

    return candidate


def detect_file_subcategory(filename):
    """根据文件扩展名自动检测文件子分类"""
    ext = os.path.splitext(filename.lower())[1]

    for subcategory, extensions in app.config['EXTENSION_MAPPING'].items():
        if ext in extensions:
            return subcategory

    return 'other'


def smart_file_storage(file_obj, stored_filename, category, subcategory='other'):
    """
    智能文件存储：根据可用空间自动选择存储位置
    优化：使用流式传输(shutil.copyfileobj)代替一次性读取内存，支持10GB+大文件
    """
    paths = get_file_paths(stored_filename, category, subcategory)

    try:
        # 1. 获取文件大小（不读取内容到内存）
        file_size = 0
        if hasattr(file_obj, 'file_path') and os.path.exists(file_obj.file_path):
            # 场景A: 来自 merge_chunks 的临时文件路径包装器
            file_size = os.path.getsize(file_obj.file_path)
        elif hasattr(file_obj, 'seek') and hasattr(file_obj, 'tell'):
            # 场景B: 来自 Flask 上传的 FileStorage 对象
            file_obj.seek(0, os.SEEK_END)
            file_size = file_obj.tell()
            file_obj.seek(0)  # 重置指针
        else:
            # 场景C: 紧急后备（仅小文件）
            content = file_obj.read()
            file_size = len(content)
            from io import BytesIO
            file_obj = BytesIO(content)

        # 2. 获取可用的存储位置
        available_locations = get_available_storage_locations(file_size, category, subcategory)

        if not available_locations:
            return False, None, "所有存储位置空间不足"

        storage_type = ""

        # 判断是否重要文件
        filename_lower = stored_filename.lower()
        is_important = any(filename_lower.endswith(ext) for ext in app.config['IMPORTANT_EXTENSIONS'])
        should_dual_store = is_important or file_size < app.config['DUAL_STORAGE_THRESHOLD']

        # --- 定义流式写入辅助函数 (核心优化) ---
        def stream_save_to(dest_path):
            """将源文件流式写入目标路径，内存占用极低"""
            # 确保目标目录存在
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            with open(dest_path, 'wb') as f_dest:
                if hasattr(file_obj, 'file_path') and os.path.exists(file_obj.file_path):
                    # 来源是磁盘文件：使用高效的 copyfileobj
                    with open(file_obj.file_path, 'rb') as f_src:
                        shutil.copyfileobj(f_src, f_dest, length=1024 * 1024 * 10)  # 10MB 缓冲区
                elif hasattr(file_obj, 'save'):
                    # 来源是 Flask FileStorage
                    file_obj.save(dest_path)
                else:
                    # 来源是 BytesIO 或通用流
                    if hasattr(file_obj, 'seek'):
                        file_obj.seek(0)
                    shutil.copyfileobj(file_obj, f_dest, length=1024 * 1024 * 10)

        # 3. 执行存储策略
        if should_dual_store and 'external' in available_locations and 'primary' in available_locations:
            # 双存储策略：先存到外部
            stream_save_to(paths['external'])

            # 再从外部复制到内部（避免再次读取上传流，且最快）
            if os.path.exists(paths['external']):
                shutil.copy2(paths['external'], paths['primary'])

            storage_type = 'dual'
            logger.info(f"文件双存储(流式): {stored_filename} (大小: {file_size} bytes)")

        elif 'external' in available_locations:
            # 只存储到外部
            stream_save_to(paths['external'])

            if 'primary' in available_locations:
                # 创建软链接
                if os.path.exists(paths['primary']):
                    os.remove(paths['primary'])
                try:
                    os.symlink(paths['external'], paths['primary'])
                    storage_type = 'external_with_link'
                except OSError:
                    storage_type = 'external_only'
            else:
                storage_type = 'external_only'

            logger.info(f"文件外部存储(流式): {stored_filename} (大小: {file_size} bytes)")

        elif 'primary' in available_locations:
            # 只存储到主存储
            stream_save_to(paths['primary'])
            storage_type = 'primary_only'
            logger.info(f"文件主存储(流式): {stored_filename} (大小: {file_size} bytes)")

        else:
            return False, None, "没有可用的存储位置"

        return True, storage_type, None

    except Exception as e:
        error_msg = f"文件保存失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        # 清理可能已保存的文件
        for location in ['external', 'primary']:
            path = paths[location]
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
        return False, None, error_msg


# ========== 工具函数 ==========
def hash_password(password):
    """密码保持明文存储"""
    return password


def generate_captcha(length=4):
    """生成随机验证码"""
    try:
        characters = string.ascii_uppercase + string.digits
        return ''.join(random.choice(characters) for _ in range(length))
    except Exception as e:
        logger.error(f"生成验证码内容错误: {str(e)}")
        # 返回一个默认验证码以防万一
        return "ABCD"


def secure_filename_with_chinese(filename):
    """安全文件名处理，但保留中文字符"""
    import re
    # 保留中文字符、字母、数字、下划线、点、连字符、空格
    pattern = re.compile(r'[^\u4e00-\u9fa5a-zA-Z0-9_\-. ]')
    filename = pattern.sub('', filename)

    # 去除路径分隔符
    filename = filename.replace('/', '').replace('\\', '')

    # 确保文件名不为空
    if not filename or filename in ('.', '..'):
        return None

    return filename


def login_required(f):
    """登录验证装饰器"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': '需要登录'}), 401
        return f(*args, **kwargs)

    return decorated_function


def is_port_in_use(port, host='0.0.0.0'):
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except socket.error:
            return True


def find_available_port(start_port=5000, max_attempts=10):
    """查找可用的端口"""
    for port in range(start_port, start_port + max_attempts):
        if not is_port_in_use(port):
            return port
    return None


# ========== 用户信息管理路由 ==========
@app.route('/user/profile', methods=['GET'])
@login_required
def get_user_profile():
    """获取当前用户信息"""
    try:
        user_id = session.get('user_id')
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT username, email, user_group, chinese_alias FROM users WHERE id = %s"
            cursor.execute(sql, (user_id,))
            user = cursor.fetchone()

        conn.close()

        if user:
            return jsonify({
                'username': user['username'],
                'email': user['email'] or '',
                'user_group': user['user_group'],
                'chinese_alias': user['chinese_alias'] or ''
            })
        else:
            return jsonify({'error': '用户不存在'}), 404
    except Exception as e:
        logger.error(f"获取用户信息错误: {str(e)}")
        return jsonify({'error': '获取用户信息失败'}), 500


@app.route('/user/profile', methods=['PUT'])
@login_required
def update_user_profile():
    """更新当前用户信息"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        new_username = data.get('username')
        new_chinese_alias = data.get('chinese_alias')
        new_password = data.get('password')

        user_id = session.get('user_id')
        current_username = session.get('username')

        if not new_username:
            return jsonify({'error': '用户名不能为空'}), 400

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查新用户名是否已被其他用户使用
            sql = "SELECT id FROM users WHERE username = %s AND id != %s"
            cursor.execute(sql, (new_username, user_id))
            if cursor.fetchone():
                conn.close()
                return jsonify({'error': '用户名已存在'}), 400

            # 更新用户信息
            if new_password:
                # 更新密码
                hashed_password = hash_password(new_password)
                sql = "UPDATE users SET username = %s, chinese_alias = %s, password = %s WHERE id = %s"
                cursor.execute(sql, (new_username, new_chinese_alias, hashed_password, user_id))
            else:
                # 不更新密码
                sql = "UPDATE users SET username = %s, chinese_alias = %s WHERE id = %s"
                cursor.execute(sql, (new_username, new_chinese_alias, user_id))

            conn.commit()

        conn.close()

        # 更新session中的用户名
        session['username'] = new_username

        logger.info(f"用户信息更新成功: 用户ID {user_id}, 新用户名: {new_username}")
        return jsonify({'success': True, 'message': '用户信息更新成功'})
    except Exception as e:
        logger.error(f"更新用户信息错误: {str(e)}")
        return jsonify({'error': '用户信息更新失败'}), 500


@app.route('/users/<int:user_id>/chinese_alias', methods=['PUT'])
@admin_required
def update_user_chinese_alias(user_id):
    """管理员更新用户中文别名"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        new_chinese_alias = data.get('chinese_alias')

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查用户是否存在
            sql = "SELECT username, user_group FROM users WHERE id = %s"
            cursor.execute(sql, (user_id,))
            user = cursor.fetchone()

            if not user:
                conn.close()
                return jsonify({'error': '用户不存在'}), 404

            # 检查权限：非root2用户不能修改root2用户的信息
            current_user_group = session.get('user_group')
            if current_user_group != 'root2' and user['user_group'] == 'root2':
                conn.close()
                return jsonify({'error': '没有权限修改超级管理员信息'}), 403

            # 更新中文别名
            sql = "UPDATE users SET chinese_alias = %s WHERE id = %s"
            cursor.execute(sql, (new_chinese_alias, user_id))
            conn.commit()

        conn.close()
        logger.info(f"用户中文别名更新成功: 用户ID {user_id}, 中文别名: {new_chinese_alias}")
        return jsonify({'success': True, 'message': '中文别名更新成功'})
    except Exception as e:
        logger.error(f"更新用户中文别名错误: {str(e)}")
        return jsonify({'error': '中文别名更新失败'}), 500


# ========== 用户管理函数 ==========
def get_user_permissions(user_group):
    """获取用户组权限"""
    group_config = app.config['USER_GROUPS'].get(user_group, {})
    return group_config.get('permissions', [])


def can_manage_users(current_user_group, target_user_current_group, new_group=None):
    """检查是否可以管理目标用户组"""
    if current_user_group == 'root2':
        # root2可以管理所有用户组
        return True
    elif current_user_group == 'root':
        # root可以管理除root2外的其他用户组
        # 不能管理已经是root2的用户，也不能将用户改为root2组
        if target_user_current_group == 'root2':
            return False
        if new_group == 'root2':
            return False
        return True
    else:
        # 其他用户组不能管理用户
        return False


# ========== 数据库操作函数 ==========
def record_file_upload(stored_filename, original_filename, file_size, user_id, username, category='competition',
                       subcategory='other', storage_type='dual', folder_id=None):
    """记录文件上传信息到数据库"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO file_info 
                (stored_filename, original_filename, file_size, upload_time, upload_user_id, upload_username, download_count, file_category, file_subcategory, storage_type, folder_id)
                VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s)
            """
            cursor.execute(sql, (
                stored_filename,
                original_filename,  # 这里存储原始文件名（包含中文）
                file_size,
                datetime.now(),
                user_id,
                username,
                category,
                subcategory,
                storage_type,
                folder_id
            ))
            conn.commit()
        conn.close()
        logger.info(
            f"文件信息记录成功: {stored_filename} 原始文件名: {original_filename} 存储类型: {storage_type} 子分类: {subcategory} 文件夹ID: {folder_id}")
        return True, None
    except Exception as e:
        error_msg = f"记录文件信息失败: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def record_file_download(stored_filename, user_id, username):
    """记录文件下载信息到数据库"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 首先获取文件ID
            sql = "SELECT id FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

            if file_info:
                file_id = file_info['id']

                # 插入下载记录
                sql = """
                    INSERT INTO download_logs 
                    (file_id, user_id, username, download_time)
                    VALUES (%s, %s, %s, %s)
                """
                cursor.execute(sql, (
                    file_id,
                    user_id,
                    username,
                    datetime.now()
                ))

                # 更新下载次数
                sql = "UPDATE file_info SET download_count = download_count + 1 WHERE id = %s"
                cursor.execute(sql, (file_id,))

                conn.commit()
                logger.info(f"文件下载记录成功: {stored_filename} 下载者: {username}")
        conn.close()
        return True
    except Exception as e:
        logger.error(f"记录文件下载信息失败: {str(e)}")
        return False


def get_all_files_from_database(category=None, subcategory=None, user_group='other', search=None):
    """
    从数据库获取文件列表
    修改：增加了文件夹权限判断
    1. 如果文件不在文件夹中 (folder_id IS NULL)，遵循原有的分类规则。
    2. 如果文件在文件夹中，管理员可见所有；普通用户仅当文件夹 is_visible_to_all=TRUE 时可见。
    """
    files = []
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 修改 SQL：关联 folders 表以获取文件夹的公开状态
            base_sql = """
                SELECT 
                    f.stored_filename, 
                    f.original_filename as filename, 
                    f.file_size, 
                    f.upload_time, 
                    f.upload_username,
                    f.download_count,
                    f.file_category,
                    f.file_subcategory,
                    f.storage_type,
                    f.folder_id,
                    fo.is_visible_to_all
                FROM file_info f
                LEFT JOIN folders fo ON f.folder_id = fo.id
            """

            where_clauses = []
            params = []

            # === 核心修改开始：权限过滤逻辑 ===

            # 逻辑 A: 基础分类筛选 (Everyone/Competition)
            if user_group == 'other':
                # other 组用户只能看 everyone 分类的文件
                where_clauses.append("f.file_category = 'everyone'")

            if category:
                if user_group != 'other' or category == 'everyone':
                    where_clauses.append("f.file_category = %s")
                    params.append(category)
                elif user_group == 'other' and category != 'everyone':
                    where_clauses.append("1 = 0")  # 强制为空

            if subcategory:
                where_clauses.append("f.file_subcategory = %s")
                params.append(subcategory)

            # 逻辑 B: 文件夹可见性筛选
            # 如果用户是管理员(root/root2)，可以看到私有文件夹的内容
            # 如果是普通用户(competition/other)，只能看:
            # 1. 不在文件夹里的文件 (f.folder_id IS NULL)
            # 2. OR 在文件夹里且文件夹是公开的 (fo.is_visible_to_all = TRUE)
            if user_group not in ['root', 'root2']:
                where_clauses.append("(f.folder_id IS NULL OR fo.is_visible_to_all = TRUE)")

            # === 核心修改结束 ===

            # 搜索筛选
            if search:
                where_clauses.append("(f.original_filename LIKE %s OR f.stored_filename LIKE %s)")
                search_term = f"%{search}%"
                params.append(search_term)
                params.append(search_term)

            # 组合查询
            if where_clauses:
                base_sql += " WHERE " + " AND ".join(where_clauses)

            base_sql += " ORDER BY f.upload_time DESC"

            cursor.execute(base_sql, tuple(params))
            files = cursor.fetchall()

            # 格式化时间
            for file in files:
                if isinstance(file['upload_time'], datetime):
                    file['upload_time'] = file['upload_time'].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    file['upload_time'] = str(file['upload_time'])

        conn.close()
    except Exception as e:
        logger.error(f"从数据库获取文件列表错误: {str(e)}")
    return files


def migrate_existing_files():
    """将系统中已存在的文件迁移到数据库（检查两个存储位置）"""
    try:
        logger.info("开始迁移现有文件（检查两个存储位置）")

        all_files = []

        # 检查两个分类目录在两个存储位置中的文件
        for category in ['everyone', 'competition']:
            folders = app.config[f'{category.upper()}_FOLDERS']

            for location, folder_path in folders.items():
                if os.path.exists(folder_path):
                    # 遍历所有子分类目录
                    for subcategory in app.config['SUBCATEGORIES'].keys():
                        subcategory_path = os.path.join(folder_path, subcategory)
                        if os.path.exists(subcategory_path):
                            files = [f for f in os.listdir(subcategory_path)
                                     if os.path.isfile(os.path.join(subcategory_path, f))]

                            for filename in files:
                                file_path = os.path.join(subcategory_path, filename)
                                if os.path.isfile(file_path):
                                    all_files.append((category, subcategory, filename, file_path, location))

        logger.info(f"发现 {len(all_files)} 个文件需要检查迁移")

        if not all_files:
            logger.info("上传目录中没有文件需要迁移")
            return

        conn = get_db_connection()

        with conn.cursor() as cursor:
            # 获取数据库中已记录的文件名
            sql = "SELECT stored_filename FROM file_info"
            cursor.execute(sql)
            db_files = [row['stored_filename'] for row in cursor.fetchall()]

            # 找出需要迁移的文件
            files_to_migrate = [f for f in all_files if f[2] not in db_files]

            if files_to_migrate:
                logger.info(f"发现 {len(files_to_migrate)} 个文件需要迁移到数据库")

                # 检查是否已有admin用户，如果没有则创建
                cursor.execute("SELECT id FROM users WHERE username = 'admin'")
                admin_user = cursor.fetchone()
                if not admin_user:
                    cursor.execute(
                        "INSERT INTO users (username, password, email) VALUES ('admin', 'admin123', 'admin@example.com')"
                    )
                    admin_id = cursor.lastrowid
                    conn.commit()
                else:
                    admin_id = admin_user['id']

                migrated_count = 0
                for category, subcategory, stored_filename, file_path, location in files_to_migrate:
                    if os.path.isfile(file_path):
                        try:
                            file_size = os.path.getsize(file_path)
                            upload_time = datetime.fromtimestamp(os.path.getctime(file_path))

                            # 判断存储类型
                            if location == 'primary':
                                # 检查外部存储是否也有相同文件
                                external_path = get_file_paths(stored_filename, category, subcategory)['external']
                                if os.path.exists(external_path):
                                    storage_type = 'dual'
                                else:
                                    storage_type = 'primary_only'
                            else:  # external
                                # 检查主存储是否也有相同文件
                                primary_path = get_file_paths(stored_filename, category, subcategory)['primary']
                                if os.path.exists(primary_path):
                                    storage_type = 'dual'
                                else:
                                    storage_type = 'external_only'

                            # 插入数据库记录
                            sql = """
                                INSERT INTO file_info 
                                (stored_filename, original_filename, file_size, upload_time, upload_user_id, upload_username, download_count, file_category, file_subcategory, storage_type)
                                VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s, %s)
                            """
                            cursor.execute(sql, (
                                stored_filename,
                                stored_filename,  # 使用存储的文件名作为原始文件名
                                file_size,
                                upload_time,
                                admin_id,
                                'admin',
                                category,
                                subcategory,
                                storage_type
                            ))
                            migrated_count += 1
                            logger.info(
                                f"迁移文件: {stored_filename} 分类: {category} 子分类: {subcategory} 位置: {location} 存储类型: {storage_type}")
                        except Exception as e:
                            logger.error(f"迁移文件失败 {stored_filename}: {str(e)}")

                conn.commit()
                logger.info(f"成功迁移 {migrated_count} 个文件到数据库")
            else:
                logger.info("没有需要迁移的文件")

        conn.close()
    except Exception as e:
        logger.error(f"迁移现有文件失败: {str(e)}")


# ========== 路由定义 ==========
@app.route('/')
def index():
    """首页路由"""
    return render_template('index.html')


@app.route('/get_captcha')
def get_captcha():
    """获取验证码API"""
    try:
        captcha_text = generate_captcha()
        if not captcha_text:
            logger.error("生成的验证码为空")
            captcha_text = "ABCD"  # 默认值

        session['captcha'] = captcha_text
        session['captcha_time'] = time.time()

        logger.info(f"生成验证码成功: {captcha_text}")
        return jsonify({'captcha': captcha_text})

    except Exception as e:
        logger.error(f"生成验证码错误: {str(e)}", exc_info=True)
        # 返回一个默认验证码，避免前端完全无法使用
        default_captcha = "1234"
        session['captcha'] = default_captcha
        session['captcha_time'] = time.time()
        return jsonify({'captcha': default_captcha})


def validate_password_strength(password):
    """
    校验密码强度
    要求：
    1. 长度至少8位
    2. 包含至少一个小写字母
    3. 包含至少一个大写字母
    4. 包含至少一个数字
    5. 包含至少一个特殊字符
    """
    if len(password) < 8:
        return False, "密码长度至少需要8个字符"

    if not re.search(r"[a-z]", password):
        return False, "密码需要包含至少一个小写字母"

    if not re.search(r"[A-Z]", password):
        return False, "密码需要包含至少一个大写字母"

    if not re.search(r"\d", password):
        return False, "密码需要包含至少一个数字"

    # 检查特殊字符 (可以根据需要调整允许的字符范围)
    if not re.search(r"[ !@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password):
        return False, "密码需要包含至少一个特殊字符 (如 @, #, $, %, . 等)"

    return True, None


@app.route('/register', methods=['POST'])
def register():
    """用户注册API"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        username = data.get('username')
        password = data.get('password') # 获取密码
        email = data.get('email', '')
        chinese_alias = data.get('chinese_alias', '')

        logger.info(f"注册尝试: 用户名={username}, 邮箱={email}, 中文别名={chinese_alias}")

        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400

        # ================== [新增代码 START] ==================
        # 校验密码强度
        is_valid_pwd, pwd_error_msg = validate_password_strength(password)
        if not is_valid_pwd:
            return jsonify({'success': False, 'message': f'密码强度不足: {pwd_error_msg}'}), 400

        # 密码明文存储
        hashed_password = hash_password(password)

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查用户名是否已存在
            sql = "SELECT id FROM users WHERE username = %s"
            cursor.execute(sql, (username,))
            if cursor.fetchone():
                conn.close()
                logger.warning(f"用户名已存在: {username}")
                return jsonify({'success': False, 'message': '用户名已存在'}), 400

            # 插入新用户，默认属于other组
            sql = "INSERT INTO users (username, password, email, user_group, chinese_alias) VALUES (%s, %s, %s, 'other', %s)"
            cursor.execute(sql, (username, hashed_password, email, chinese_alias))
            conn.commit()

        conn.close()
        logger.info(
            f"用户注册成功: {username} 来自 {request.remote_addr}, 默认分配到other组, 中文别名: {chinese_alias}")
        return jsonify({'success': True, 'message': '注册成功'})

    except Exception as e:
        logger.error(f"注册错误: {str(e)}")
        import traceback
        logger.error(f"注册详细错误: {traceback.format_exc()}")
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500


@app.route('/login', methods=['POST'])
def login():
    """登录API"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        captcha = data.get('captcha', '')

        logger.info(f"登录尝试来自: {request.remote_addr}，用户: {username}")

        # 验证验证码
        session_captcha = session.get('captcha')
        captcha_time = session.get('captcha_time', 0)

        # 验证码有效期5分钟
        if not session_captcha or time.time() - captcha_time > 300:
            return jsonify({'success': False, 'message': '验证码已过期，请刷新'}), 401

        if not captcha or captcha.upper() != session_captcha:
            # 验证码错误时清除session中的验证码，强制刷新
            session.pop('captcha', None)
            session.pop('captcha_time', None)
            return jsonify({'success': False, 'message': '验证码错误'}), 401

        # 密码明文验证
        hashed_password = hash_password(password)

        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT id, username, user_group FROM users WHERE username = %s AND password = %s"
            cursor.execute(sql, (username, hashed_password))
            user = cursor.fetchone()

        conn.close()

        if user:
            # 登录成功后清除验证码
            session.pop('captcha', None)
            session.pop('captcha_time', None)
            session['logged_in'] = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['user_group'] = user['user_group']  # 添加用户组信息

            logger.info(f"用户登录成功: {username} 用户组: {user['user_group']}")
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': '用户名或密码错误'}), 401

    except Exception as e:
        logger.error(f"登录错误: {str(e)}")
        return jsonify({'success': False, 'message': '服务器错误'}), 500


@app.route('/logout', methods=['POST'])
def logout():
    """退出登录API"""
    session.pop('logged_in', None)
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('user_group', None)
    return jsonify({'success': True})


@app.route('/check_login')
def check_login():
    return jsonify({
        'logged_in': session.get('logged_in', False),
        'username': session.get('username', ''),
        'user_group': session.get('user_group', 'other'),
        'user_id': session.get('user_id')  # 新增用户ID
    })


# ========== 用户管理路由 ==========
@app.route('/users', methods=['GET'])
@admin_required  # 改为admin_required，允许root和root2访问
def list_users():
    """获取所有用户列表（root2和root可访问）"""
    try:
        current_user_group = session.get('user_group')
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT id, username, email, user_group, chinese_alias, created_at FROM users ORDER BY created_at DESC"
            cursor.execute(sql)
            users = cursor.fetchall()

            # 如果不是root2用户，隐藏root2用户的用户名
            if current_user_group != 'root2':
                for user in users:
                    if user['user_group'] == 'root2':
                        user['username'] = '******'  # 隐藏用户名
                        user['email'] = '******'  # 隐藏邮箱

            # 格式化时间
            for user in users:
                if isinstance(user['created_at'], datetime):
                    user['created_at'] = user['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    user['created_at'] = str(user['created_at'])

        conn.close()
        return jsonify({'users': users})
    except Exception as e:
        logger.error(f"获取用户列表错误: {str(e)}")
        return jsonify({'error': '获取用户列表失败'}), 500


@app.route('/users/<int:user_id>', methods=['PUT'])
@admin_required  # 改为admin_required，允许root和root2访问
def update_user(user_id):
    """更新用户信息（root2和root可访问）"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        new_group = data.get('user_group')

        if new_group not in app.config['USER_GROUPS']:
            return jsonify({'error': '无效的用户组'}), 400

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查目标用户是否存在
            sql = "SELECT username, user_group FROM users WHERE id = %s"
            cursor.execute(sql, (user_id,))
            target_user = cursor.fetchone()

            if not target_user:
                conn.close()
                return jsonify({'error': '用户不存在'}), 404

            # 检查是否可以管理目标用户
            current_user_group = session.get('user_group')
            if not can_manage_users(current_user_group, target_user['user_group'], new_group):
                conn.close()
                return jsonify({'error': '没有权限管理该用户'}), 403

            # 更新用户组
            sql = "UPDATE users SET user_group = %s WHERE id = %s"
            cursor.execute(sql, (new_group, user_id))
            conn.commit()

        conn.close()
        logger.info(f"用户组更新成功: 用户ID {user_id} 改为 {new_group}")
        return jsonify({'success': True, 'message': '用户组更新成功'})
    except Exception as e:
        logger.error(f"更新用户组错误: {str(e)}")
        return jsonify({'error': '用户组更新失败'}), 500


@app.route('/user/permissions')
@login_required
def get_user_permissions_info():
    """获取当前用户的权限信息"""
    try:
        user_group = session.get('user_group', 'other')
        permissions = get_user_permissions(user_group)
        group_name = app.config['USER_GROUPS'].get(user_group, {}).get('name', '未知用户组')

        # 修改：root和root2都可以管理用户
        can_manage_users = user_group in ['root2', 'root']

        return jsonify({
            'user_group': user_group,
            'group_name': group_name,
            'permissions': permissions,
            'can_manage_users': can_manage_users
        })
    except Exception as e:
        logger.error(f"获取用户权限信息错误: {str(e)}")
        return jsonify({'error': '获取权限信息失败'}), 500


# ========== 用户管理路由 - 添加删除功能 ==========
@app.route('/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """
    删除用户
    (MODIFIED for Feature 3: Added 'force' parameter to re-assign data and delete user)
    """
    try:
        force = request.args.get('force', 'false').lower() == 'true'
        current_user_id = session.get('user_id')
        current_username = session.get('username')
        current_user_group = session.get('user_group')

        # 只有root2可以删除用户
        if current_user_group != 'root2':
            return jsonify({'error': '需要超级管理员权限才能删除用户'}), 403

        # 不能删除自己
        if user_id == current_user_id:
            return jsonify({'error': '不能删除当前登录的用户'}), 400

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查目标用户是否存在
            sql = "SELECT username, user_group FROM users WHERE id = %s"
            cursor.execute(sql, (user_id,))
            target_user = cursor.fetchone()

            if not target_user:
                conn.close()
                return jsonify({'error': '用户不存在'}), 404

            # root2不能删除其他root2用户（只能删除自己以外的root、competition、other用户）
            if target_user['user_group'] == 'root2':
                conn.close()
                return jsonify({'error': '不能删除其他超级管理员用户'}), 403

            # 检查用户是否有文件记录
            sql = "SELECT COUNT(*) as file_count FROM file_info WHERE upload_user_id = %s"
            cursor.execute(sql, (user_id,))
            file_count = cursor.fetchone()['file_count']

            # 检查用户是否有文件夹
            sql = "SELECT COUNT(*) as folder_count FROM folders WHERE created_by = %s"
            cursor.execute(sql, (user_id,))
            folder_count = cursor.fetchone()['folder_count']

            # 检查用户是否有下载记录
            sql = "SELECT COUNT(*) as download_count FROM download_logs WHERE user_id = %s"
            cursor.execute(sql, (user_id,))
            download_count = cursor.fetchone()['download_count']

            has_related_data = file_count > 0 or folder_count > 0 or download_count > 0

            if has_related_data and not force:
                conn.close()
                return jsonify({
                    'error': '用户有关联数据，无法删除',
                    'details': {
                        'file_count': file_count,
                        'folder_count': folder_count,
                        'download_count': download_count
                    }
                }), 400

            if has_related_data and force:
                logger.warning(
                    f"强制删除用户 {user_id} ({target_user['username']}). 数据将转移给 {current_username} (ID: {current_user_id})")

                # 1. 转移文件
                sql = "UPDATE file_info SET upload_user_id = %s, upload_username = %s WHERE upload_user_id = %s"
                cursor.execute(sql, (current_user_id, current_username, user_id))

                # 2. 转移文件夹
                sql = "UPDATE folders SET created_by = %s, created_username = %s WHERE created_by = %s"
                cursor.execute(sql, (current_user_id, current_username, user_id))

                # 3. 删除下载日志 (这些只是日志，可以直接删除)
                sql = "DELETE FROM download_logs WHERE user_id = %s"
                cursor.execute(sql, (user_id,))

                conn.commit()
                logger.info(f"用户 {user_id} 的关联数据已转移给用户 {current_user_id}")

            # (Now safe to) 删除用户
            sql = "DELETE FROM users WHERE id = %s"
            cursor.execute(sql, (user_id,))
            conn.commit()

        conn.close()

        if has_related_data and force:
            logger.info(f"用户已强制删除: 用户ID {user_id} 用户名: {target_user['username']}")
            return jsonify({'success': True, 'message': '用户已强制删除，数据已转移'})
        else:
            logger.info(f"用户删除成功: 用户ID {user_id} 用户名: {target_user['username']}")
            return jsonify({'success': True, 'message': '用户删除成功'})

    except Exception as e:
        logger.error(f"删除用户错误: {str(e)}")
        return jsonify({'error': '用户删除失败'}), 500


# ========== 文件操作路由 ==========
@app.route('/files')
@login_required
@permission_required('download')
def list_files():
    """
    获取所有文件列表（从数据库读取）
    (MODIFIED for Feature 2: Added 'search' parameter)
    """
    try:
        category = request.args.get('category', None)
        subcategory = request.args.get('subcategory', None)
        search = request.args.get('search', None)  # NEW
        user_group = session.get('user_group', 'other')

        all_files = get_all_files_from_database(category, subcategory, user_group, search)

        return jsonify({'files': all_files})
    except Exception as e:
        logger.error(f"获取文件列表错误: {str(e)}")
        return jsonify({'error': '获取文件列表失败'}), 500


@app.route('/subcategories')
@login_required
def get_subcategories():
    """获取所有子分类"""
    return jsonify({
        'subcategories': app.config['SUBCATEGORIES'],
        'extension_mapping': app.config['EXTENSION_MAPPING']
    })


@app.route('/upload', methods=['POST'])
@login_required
@permission_required('upload')
def upload_file():
    """文件上传API（智能存储策略）- 普通上传模式"""
    try:
        logger.info("开始文件上传处理（智能存储）")

        if 'file' not in request.files:
            return jsonify({'error': '没有文件部分'}), 400

        file = request.files['file']
        category = request.form.get('category', 'competition')
        subcategory = request.form.get('subcategory', 'other')
        folder_id = request.form.get('folder_id', None)

        if file.filename == '':
            return jsonify({'error': '没有选择文件'}), 400

        if category not in ['everyone', 'competition']:
            category = 'competition'

        if subcategory not in app.config['SUBCATEGORIES']:
            subcategory = detect_file_subcategory(file.filename)

        original_filename = secure_filename_with_chinese(file.filename)
        if not original_filename:
            original_filename = "unnamed_file"

        stored_filename = get_unique_filename(original_filename, category, subcategory)

        # === 关键修改：直接传递 file 对象，绝不调用 file.read() ===
        success, storage_type, save_error = smart_file_storage(file, stored_filename, category, subcategory)

        if not success:
            return jsonify({'error': f'文件保存失败: {save_error}'}), 500

        # 获取路径计算大小
        file_path = get_file_paths(stored_filename, category, subcategory)['external']
        if storage_type == 'primary_only':
            file_path = get_file_paths(stored_filename, category, subcategory)['primary']

        file_size = os.path.getsize(file_path)
        user_id = session.get('user_id')
        username = session.get('username')

        # 文件夹权限检查 (逻辑保持不变，省略部分重复代码以节省篇幅，请保留原有的 folder_id 检查逻辑)
        if folder_id:
            # ... (保持原有权限检查代码不变) ...
            pass

        success, db_error = record_file_upload(stored_filename, original_filename, file_size, user_id, username,
                                               category, subcategory, storage_type, folder_id)

        if not success:
            # 失败清理逻辑...
            return jsonify({'error': f'数据库记录失败: {db_error}'}), 500

        return jsonify({
            'success': True,
            'message': '文件上传成功',
            'filename': original_filename,
            'subcategory': subcategory,
            'storage_type': storage_type
        }), 200
    except Exception as e:
        logger.error(f"文件上传错误: {str(e)}", exc_info=True)
        return jsonify({'error': f'文件上传失败: {str(e)}'}), 500


@app.route('/upload_chunk', methods=['POST'])
@login_required
@permission_required('upload')
def upload_chunk():
    """分块上传API"""
    try:
        chunk = request.files.get('chunk')
        chunk_number = request.form.get('chunkNumber')
        total_chunks = request.form.get('totalChunks')
        filename = secure_filename_with_chinese(request.form.get('filename'))  # 修改这里
        if not filename:
            filename = "unnamed_file"
        identifier = request.form.get('identifier')
        category = request.form.get('category', 'competition')
        subcategory = request.form.get('subcategory', 'other')

        if not all([chunk, chunk_number, total_chunks, filename, identifier]):
            return jsonify({'error': '缺少必要参数'}), 400

        if category not in ['everyone', 'competition']:
            category = 'competition'

        if subcategory not in app.config['SUBCATEGORIES']:
            subcategory = detect_file_subcategory(filename)

        # 临时目录
        temp_dir = os.path.join(BASE_UPLOAD_FOLDER, 'temp', identifier)
        os.makedirs(temp_dir, exist_ok=True)

        chunk_path = os.path.join(temp_dir, f"{chunk_number}.part")
        chunk.save(chunk_path)

        logger.info(f"分块 {chunk_number}/{total_chunks} 上传成功: {filename} 分类: {category} 子分类: {subcategory}")
        return jsonify({'success': True, 'message': f'分块 {chunk_number}/{total_chunks} 上传成功'})

    except Exception as e:
        logger.error(f"分块上传错误: {str(e)}")
        return jsonify({'error': '分块上传失败'}), 500


@app.route('/merge_chunks', methods=['POST'])
@login_required
@permission_required('upload')
def merge_chunks():
    """合并分块API - 流式合并"""
    try:
        filename = secure_filename_with_chinese(request.form.get('filename'))
        if not filename: filename = "unnamed_file"
        identifier = request.form.get('identifier')
        total_chunks = int(request.form.get('totalChunks'))
        category = request.form.get('category', 'competition')
        subcategory = request.form.get('subcategory', 'other')

        if subcategory not in app.config['SUBCATEGORIES']:
            subcategory = detect_file_subcategory(filename)

        temp_dir = os.path.join(BASE_UPLOAD_FOLDER, 'temp', identifier)
        stored_filename = get_unique_filename(filename, category, subcategory)

        # 检查分块完整性
        for i in range(1, total_chunks + 1):
            if not os.path.exists(os.path.join(temp_dir, f"{i}.part")):
                return jsonify({'error': f'缺少分块: {i}'}), 400

        # 合并分块 (流式写入，内存占用极低)
        temp_file_path = os.path.join(BASE_UPLOAD_FOLDER, 'temp', f"{identifier}_merged")

        with open(temp_file_path, 'wb') as output_file:
            for i in range(1, total_chunks + 1):
                chunk_path = os.path.join(temp_dir, f"{i}.part")
                with open(chunk_path, 'rb') as chunk_file:
                    # 使用 10MB 缓冲区进行流式复制
                    shutil.copyfileobj(chunk_file, output_file, length=1024 * 1024 * 10)
                os.remove(chunk_path)  # 合并完一个删一个，节省空间

        if os.path.exists(temp_dir):
            os.rmdir(temp_dir)

        # 定义包装类，只传递路径，禁止 smart_file_storage 读取内容
        class FilePathWrapper:
            def __init__(self, path):
                self.file_path = path

        # 移动/保存合并后的文件
        file_obj = FilePathWrapper(temp_file_path)
        success, storage_type, save_error = smart_file_storage(file_obj, stored_filename, category, subcategory)

        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        if not success:
            return jsonify({'error': f'文件合并失败: {save_error}'}), 500

        # 记录到数据库
        file_path = get_file_paths(stored_filename, category, subcategory)['external']
        if storage_type == 'primary_only':
            file_path = get_file_paths(stored_filename, category, subcategory)['primary']

        file_size = os.path.getsize(file_path)
        user_id = session.get('user_id')
        username = session.get('username')
        folder_id = request.form.get('folder_id', None)
        if folder_id == 'null' or folder_id == '': folder_id = None

        success, db_error = record_file_upload(stored_filename, filename, file_size, user_id, username, category,
                                               subcategory, storage_type, folder_id)

        if not success:
            return jsonify({'error': f'数据库记录失败: {db_error}'}), 500

        return jsonify({'success': True, 'message': '文件合并成功', 'filename': filename})

    except Exception as e:
        logger.error(f"合并分块错误: {str(e)}", exc_info=True)
        return jsonify({'error': '文件合并失败'}), 500


@app.route('/download/<string:stored_filename>')
@login_required
@permission_required('download')
def download_file(stored_filename):
    """统一文件下载API，支持所有大小的文件"""
    try:
        logger.info(f"开始文件下载: {stored_filename}")

        # 从数据库获取文件信息
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT file_category, file_subcategory, original_filename, file_size, storage_type 
                FROM file_info WHERE stored_filename = %s
            """
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

        conn.close()

        if not file_info:
            logger.error(f"文件不存在于数据库: {stored_filename}")
            return jsonify({'error': '文件不存在'}), 404

        category = file_info['file_category']
        subcategory = file_info['file_subcategory']
        original_filename = file_info['original_filename'] or stored_filename
        file_size = file_info['file_size']
        storage_type = file_info['storage_type']

        # 查找文件路径
        file_path = get_any_existing_file_path(stored_filename, category, subcategory)

        if not file_path or not os.path.exists(file_path):
            logger.error(f"文件不存在于磁盘: {stored_filename}")
            return jsonify({'error': '文件不存在'}), 404

        # 处理软链接
        if os.path.islink(file_path):
            real_path = os.path.realpath(file_path)
            if os.path.exists(real_path):
                file_path = real_path
                logger.info(f"解析软链接: {file_path} -> {real_path}")
            else:
                logger.error(f"文件链接已损坏: {file_path}")
                return jsonify({'error': '文件链接已损坏'}), 404

        # 记录下载信息
        user_id = session.get('user_id')
        username = session.get('username')
        record_file_download(stored_filename, user_id, username)

        actual_file_size = os.path.getsize(file_path)
        logger.info(f"文件下载开始: {stored_filename} 大小: {actual_file_size} bytes")

        # 根据文件大小选择不同的下载策略
        if actual_file_size < 100 * 1024 * 1024:  # 小于100MB
            return download_small_file(file_path, original_filename)
        elif actual_file_size > 10 * 1024 * 1024 * 1024:  # 大于10GB
            return download_huge_file_optimized(file_path, original_filename, actual_file_size)
        else:  # 100MB - 10GB
            return download_medium_file(file_path, original_filename, actual_file_size)

    except Exception as e:
        logger.error(f"文件下载错误: {str(e)}", exc_info=True)
        return jsonify({'error': '文件下载失败'}), 500


# 在下载函数中添加更详细的监控
def monitor_download_progress(stored_filename, bytes_sent, total_size):
    """监控下载进度"""
    percent = (bytes_sent / total_size * 100) if total_size > 0 else 0
    logger.info(
        f"📊 下载进度: {stored_filename} - "
        f"{bytes_sent}/{total_size} bytes ({percent:.1f}%)"
    )


def download_small_file(file_path, original_filename):
    """下载小文件（<100MB）- 直接发送"""
    try:
        logger.info(f"使用小文件下载策略: {original_filename}")
        return send_file(
            file_path,
            as_attachment=True,
            download_name=original_filename,
            conditional=True
        )
    except Exception as e:
        logger.error(f"小文件下载失败: {str(e)}")
        return jsonify({'error': '文件下载失败'}), 500


def download_medium_file(file_path, original_filename, file_size):
    """下载中等文件（100MB - 10GB）- 流式传输"""

    def generate():
        try:
            chunk_size = 512 * 1024  # 512KB
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
        except Exception as e:
            logger.error(f"中等文件流式传输错误: {str(e)}")
            raise

    # 修复：对文件名进行URL编码，防止中文报错
    encoded_filename = quote(original_filename.encode('utf-8'))

    response = Response(
        generate(),
        mimetype='application/octet-stream',
        headers={
            # 使用 RFC 5987 标准格式，兼容所有浏览器且支持中文
            'Content-Disposition': f'attachment; filename="{encoded_filename}"; filename*=UTF-8\'\'{encoded_filename}',
            'Content-Length': str(file_size)
        }
    )
    return response


def download_huge_file_optimized(file_path, original_filename, file_size):
    """下载超大文件（>10GB）- 优化版本"""

    def generate_optimized():
        try:
            # 根据文件大小动态调整块大小
            if file_size > 50 * 1024 * 1024 * 1024:  # >50GB
                chunk_size = 64 * 1024  # 64KB
            elif file_size > 20 * 1024 * 1024 * 1024:  # >20GB
                chunk_size = 128 * 1024  # 128KB
            else:  # 10GB - 20GB
                chunk_size = 256 * 1024  # 256KB

            bytes_sent = 0
            start_time = time.time()
            last_log_time = start_time

            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        logger.info("超大文件传输完成")
                        break

                    bytes_sent += len(chunk)
                    yield chunk

                    # 智能日志记录
                    current_time = time.time()
                    if current_time - last_log_time > 60:  # 每分钟记录一次
                        elapsed = current_time - start_time
                        speed = bytes_sent / elapsed if elapsed > 0 else 0
                        percent = (bytes_sent / file_size * 100) if file_size > 0 else 0

                        logger.info(
                            f"超大文件传输进度: {bytes_sent}/{file_size} bytes "
                            f"({percent:.1f}%) 速度: {speed / 1024 / 1024:.2f} MB/s"
                        )
                        last_log_time = current_time

        except Exception as e:
            logger.error(f"超大文件流式传输错误: {str(e)}")
            raise

    response = Response(
        generate_optimized(),
        mimetype='application/octet-stream',
        headers={
            'Content-Disposition': f'attachment; filename="{original_filename}"',
            'Content-Length': str(file_size),
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'X-Accel-Buffering': 'no'  # 禁用Nginx缓冲
        }
    )
    return response


@app.route('/file_info/<string:stored_filename>')
@login_required
@permission_required('download')
def get_file_info(stored_filename):
    """获取文件详细信息，用于前端进度显示"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT stored_filename, original_filename, file_size, file_category, 
                       file_subcategory, storage_type, upload_time, upload_username
                FROM file_info WHERE stored_filename = %s
            """
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

        conn.close()

        if not file_info:
            return jsonify({'error': '文件不存在'}), 404

        # 获取实际文件路径和大小
        file_path = get_any_existing_file_path(
            stored_filename,
            file_info['file_category'],
            file_info['file_subcategory']
        )

        actual_size = 0
        if file_path and os.path.exists(file_path):
            actual_size = os.path.getsize(file_path)

        # 格式化时间
        if isinstance(file_info['upload_time'], datetime):
            upload_time = file_info['upload_time'].strftime('%Y-%m-%d %H:%M:%S')
        else:
            upload_time = str(file_info['upload_time'])

        return jsonify({
            'success': True,
            'file_info': {
                'stored_filename': file_info['stored_filename'],
                'original_filename': file_info['original_filename'],
                'file_size': file_info['file_size'],
                'actual_size': actual_size,
                'file_category': file_info['file_category'],
                'file_subcategory': file_info['file_subcategory'],
                'storage_type': file_info['storage_type'],
                'upload_time': upload_time,
                'upload_username': file_info['upload_username']
            }
        })

    except Exception as e:
        logger.error(f"获取文件信息错误: {str(e)}")
        return jsonify({'error': '获取文件信息失败'}), 500


@app.route('/delete/<string:stored_filename>', methods=['DELETE'])
@login_required
@permission_required('delete')
def delete_file(stored_filename):
    """文件删除API（处理多种存储类型）"""
    try:
        # 从数据库获取文件信息
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT file_category, file_subcategory, storage_type FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

            if file_info:
                category = file_info['file_category']
                subcategory = file_info['file_subcategory']
                storage_type = file_info['storage_type']
                paths = get_file_paths(stored_filename, category, subcategory)

                # 删除数据库记录
                sql = "DELETE FROM file_info WHERE stored_filename = %s"
                cursor.execute(sql, (stored_filename,))
                conn.commit()

                # 根据存储类型删除文件
                if storage_type == 'dual':
                    # 删除两个位置的实体文件
                    for path in paths.values():
                        if os.path.exists(path) and not os.path.islink(path):
                            os.remove(path)
                elif storage_type == 'external_with_link':
                    # 删除外部存储的实体文件和主存储的软链接
                    if os.path.exists(paths['external']) and not os.path.islink(paths['external']):
                        os.remove(paths['external'])
                    if os.path.exists(paths['primary']):
                        os.remove(paths['primary'])
                elif storage_type == 'external_only':
                    # 只删除外部存储的实体文件
                    if os.path.exists(paths['external']) and not os.path.islink(paths['external']):
                        os.remove(paths['external'])
                elif storage_type == 'primary_only':
                    # 只删除主存储的实体文件
                    if os.path.exists(paths['primary']) and not os.path.islink(paths['primary']):
                        os.remove(paths['primary'])

                logger.info(f"文件删除成功: {stored_filename} 存储类型: {storage_type} 子分类: {subcategory}")
                conn.close()
                return jsonify({'success': True, 'message': '文件删除成功'}), 200
            else:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404
    except Exception as e:
        logger.error(f"文件删除错误: {str(e)}")
        return jsonify({'error': '文件删除失败'}), 500


@app.route('/download_large/<string:stored_filename>')
@login_required
@permission_required('download')
def download_large_file_optimized(file_path, original_filename, file_size):
    """下载超大文件（>10GB）- 优化版本"""

    def generate_optimized():
        try:
            # 根据文件大小动态调整块大小
            if file_size > 50 * 1024 * 1024 * 1024:  # >50GB
                chunk_size = 64 * 1024  # 64KB
            elif file_size > 20 * 1024 * 1024 * 1024:  # >20GB
                chunk_size = 128 * 1024  # 128KB
            else:  # 10GB - 20GB
                chunk_size = 256 * 1024  # 256KB

            bytes_sent = 0
            start_time = time.time()
            last_log_time = start_time

            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        logger.info("超大文件传输完成")
                        break

                    bytes_sent += len(chunk)
                    yield chunk

                    # 智能日志记录
                    current_time = time.time()
                    if current_time - last_log_time > 60:  # 每分钟记录一次
                        elapsed = current_time - start_time
                        speed = bytes_sent / elapsed if elapsed > 0 else 0
                        percent = (bytes_sent / file_size * 100) if file_size > 0 else 0

                        logger.info(
                            f"超大文件传输进度: {bytes_sent}/{file_size} bytes "
                            f"({percent:.1f}%) 速度: {speed / 1024 / 1024:.2f} MB/s"
                        )
                        last_log_time = current_time

        except Exception as e:
            logger.error(f"超大文件流式传输错误: {str(e)}")
            raise

    # 修复：对文件名进行URL编码，防止中文报错
    encoded_filename = quote(original_filename.encode('utf-8'))

    # 创建响应
    response = Response(
        generate_optimized(),
        mimetype='application/octet-stream',
        direct_passthrough=True
    )

    # 设置响应头 (修复中文文件名问题)
    headers = {
        # 使用 RFC 5987 标准格式
        'Content-Disposition': f'attachment; filename="{encoded_filename}"; filename*=UTF-8\'\'{encoded_filename}',
        'Content-Length': str(file_size),
        'Accept-Ranges': 'bytes',
        'Cache-Control': 'no-cache, no-store, must-revalidate, max-age=0',
        'Pragma': 'no-cache',
        'Expires': '0',
        'X-Accel-Buffering': 'no',
        'X-Content-Type-Options': 'nosniff',
        'X-File-Size': str(file_size),
        'X-File-Name': encoded_filename, # Header中只允许ASCII
    }

    response.headers.update(headers)
    logger.info(f"超大文件下载响应已发送: {original_filename}")
    return response

    # except Exception as e:
    #     logger.error(f"超大文件下载错误: {str(e)}", exc_info=True)
    #     return jsonify({'error': '文件下载失败'}), 500


@app.route('/download_status/<string:stored_filename>')
@login_required
def get_download_status(stored_filename):
    """获取文件下载状态（用于前端进度监控）"""
    try:
        # 这里可以扩展为实时监控下载状态
        # 目前返回基本文件信息供前端计算进度
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT original_filename, file_size FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

        conn.close()

        if not file_info:
            return jsonify({'error': '文件不存在'}), 404

        return jsonify({
            'success': True,
            'filename': file_info['original_filename'],
            'total_size': file_info['file_size'],
            'downloadable': True
        })

    except Exception as e:
        logger.error(f"获取下载状态错误: {str(e)}")
        return jsonify({'error': '获取下载状态失败'}), 500


# ========== 文件夹管理路由 ==========
@app.route('/folders', methods=['GET'])
@login_required
def get_folders():
    """获取用户有权限访问的文件夹列表"""
    try:
        user_group = session.get('user_group', 'other')
        user_id = session.get('user_id')

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 根据用户组获取不同的文件夹列表
            if user_group == 'root2':
                # root2可以看到所有文件夹
                sql = """
                    SELECT f.*, u.username as creator_name 
                    FROM folders f 
                    LEFT JOIN users u ON f.created_by = u.id 
                    ORDER BY f.created_at DESC
                """
                cursor.execute(sql)
            elif user_group == 'root':
                # root可以看到自己创建的 + 所有公开的 + 其他管理员创建的(非root2私有)
                # 简化逻辑：Root 可以管理大部分内容，这里允许看自己创建的和所有公开的
                sql = """
                    SELECT f.*, u.username as creator_name 
                    FROM folders f 
                    LEFT JOIN users u ON f.created_by = u.id 
                    WHERE f.created_by = %s OR f.is_visible_to_all = TRUE OR f.creator_group = 'root'
                    ORDER BY f.created_at DESC
                """
                cursor.execute(sql, (user_id,))
            else:
                # 修改：其他用户(competition/other)可以看到 *所有* 公开文件夹
                # 之前限制了只能看 competition/other 创建的公开文件夹，现在去掉这个限制
                sql = """
                    SELECT f.*, u.username as creator_name 
                    FROM folders f 
                    LEFT JOIN users u ON f.created_by = u.id 
                    WHERE f.is_visible_to_all = TRUE
                    ORDER BY f.created_at DESC
                """
                cursor.execute(sql)

            folders = cursor.fetchall()

            # 格式化时间
            for folder in folders:
                if isinstance(folder['created_at'], datetime):
                    folder['created_at'] = folder['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    folder['created_at'] = str(folder['created_at'])

        conn.close()
        return jsonify({'folders': folders})
    except Exception as e:
        logger.error(f"获取文件夹列表错误: {str(e)}")
        return jsonify({'error': '获取文件夹列表失败'}), 500


@app.route('/folders', methods=['POST'])
@admin_required
def create_folder():
    """创建文件夹（仅root2和root可以创建）"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        folder_name = data.get('name')
        allowed_groups = data.get('allowed_groups', [])
        is_visible_to_all = data.get('is_visible_to_all', False)

        if not folder_name:
            return jsonify({'error': '文件夹名称不能为空'}), 400

        # 安全处理文件夹名称
        safe_folder_name = secure_filename_with_chinese(folder_name)
        if not safe_folder_name:
            return jsonify({'error': '文件夹名称无效'}), 400

        user_id = session.get('user_id')
        username = session.get('username')
        user_group = session.get('user_group')

        # 根据用户组生成不同的文件夹路径
        if user_group == 'root2':
            # 超级管理员文件夹
            folder_path = os.path.join(BASE_UPLOAD_FOLDER, 'admin_folders', 'root2', safe_folder_name)
        else:
            # 管理员文件夹
            folder_path = os.path.join(BASE_UPLOAD_FOLDER, 'admin_folders', 'root', safe_folder_name)

        # 检查文件夹是否已存在
        if os.path.exists(folder_path):
            return jsonify({'error': '文件夹已存在'}), 400

        # 创建物理文件夹
        os.makedirs(folder_path, exist_ok=True)

        # 在外部存储也创建对应文件夹
        external_folder_path = os.path.join(EXTERNAL_UPLOAD_FOLDER, 'admin_folders',
                                            'root2' if user_group == 'root2' else 'root', safe_folder_name)
        os.makedirs(external_folder_path, exist_ok=True)

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查数据库中的文件夹名称是否唯一
            sql = "SELECT id FROM folders WHERE path = %s"
            cursor.execute(sql, (folder_path,))
            if cursor.fetchone():
                conn.close()
                # 清理已创建的物理文件夹
                shutil.rmtree(folder_path, ignore_errors=True)
                shutil.rmtree(external_folder_path, ignore_errors=True)
                return jsonify({'error': '文件夹已存在'}), 400

            # 插入文件夹记录
            sql = """
                INSERT INTO folders (name, path, created_by, created_username, allowed_groups, is_visible_to_all, creator_group)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (
                folder_name,
                folder_path,
                user_id,
                username,
                json.dumps(allowed_groups),
                is_visible_to_all,
                user_group  # 记录创建者用户组
            ))
            conn.commit()

        conn.close()
        logger.info(f"文件夹创建成功: {folder_name} 创建者: {username} 用户组: {user_group}")
        return jsonify({'success': True, 'message': '文件夹创建成功'})
    except Exception as e:
        logger.error(f"创建文件夹错误: {str(e)}")
        return jsonify({'error': '文件夹创建失败'}), 500


@app.route('/folders/<int:folder_id>', methods=['PUT'])
@admin_required
def update_folder(folder_id):
    """更新文件夹权限（仅root2可以修改权限）"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        allowed_groups = data.get('allowed_groups', [])
        is_visible_to_all = data.get('is_visible_to_all', False)
        user_group = session.get('user_group')

        # 只有root2可以修改文件夹权限
        if user_group != 'root2':
            return jsonify({'error': '只有超级管理员可以修改文件夹权限'}), 403

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查文件夹是否存在
            sql = "SELECT created_by, created_username, creator_group FROM folders WHERE id = %s"
            cursor.execute(sql, (folder_id,))
            folder = cursor.fetchone()

            if not folder:
                conn.close()
                return jsonify({'error': '文件夹不存在'}), 404

            # 更新文件夹权限
            sql = "UPDATE folders SET allowed_groups = %s, is_visible_to_all = %s WHERE id = %s"
            cursor.execute(sql, (
                json.dumps(allowed_groups),
                is_visible_to_all,
                folder_id
            ))
            conn.commit()

        conn.close()
        logger.info(f"文件夹权限更新成功: 文件夹ID {folder_id}")
        return jsonify({'success': True, 'message': '文件夹权限更新成功'})
    except Exception as e:
        logger.error(f"更新文件夹权限错误: {str(e)}")
        return jsonify({'error': '文件夹权限更新失败'}), 500


@app.route('/folders/<int:folder_id>', methods=['DELETE'])
@admin_required
def delete_folder(folder_id):
    """删除文件夹（仅创建者或root2可以删除）"""
    try:
        user_id = session.get('user_id')
        user_group = session.get('user_group')

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查文件夹是否存在
            sql = "SELECT path, created_by, creator_group FROM folders WHERE id = %s"
            cursor.execute(sql, (folder_id,))
            folder = cursor.fetchone()

            if not folder:
                conn.close()
                return jsonify({'error': '文件夹不存在'}), 404

            # 检查权限：只有创建者或root2可以删除
            # root2可以删除任何文件夹，root只能删除自己创建的文件夹
            can_delete = False
            if user_group == 'root2':
                can_delete = True
            elif user_group == 'root' and folder['created_by'] == user_id and folder['creator_group'] == 'root':
                can_delete = True

            if not can_delete:
                conn.close()
                return jsonify({'error': '没有权限删除此文件夹'}), 403

            # 检查文件夹中是否有文件
            sql = "SELECT COUNT(*) as file_count FROM file_info WHERE folder_id = %s"
            cursor.execute(sql, (folder_id,))
            file_count = cursor.fetchone()['file_count']

            if file_count > 0:
                conn.close()
                return jsonify({'error': '文件夹不为空，无法删除'}), 400

            # 删除物理文件夹
            folder_path = folder['path']
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path, ignore_errors=True)

            # 删除外部存储的对应文件夹
            external_base = EXTERNAL_UPLOAD_FOLDER
            relative_path = os.path.relpath(folder_path, BASE_UPLOAD_FOLDER)
            external_folder_path = os.path.join(external_base, relative_path)
            if os.path.exists(external_folder_path):
                shutil.rmtree(external_folder_path, ignore_errors=True)

            # 删除数据库记录
            sql = "DELETE FROM folders WHERE id = %s"
            cursor.execute(sql, (folder_id,))
            conn.commit()

        conn.close()
        logger.info(f"文件夹删除成功: 文件夹ID {folder_id}")
        return jsonify({'success': True, 'message': '文件夹删除成功'})
    except Exception as e:
        logger.error(f"删除文件夹错误: {str(e)}")
        return jsonify({'error': '文件夹删除失败'}), 500


@app.route('/folder_files/<int:folder_id>')
@login_required
@permission_required('download')
def get_folder_files(folder_id):
    """获取文件夹中的文件列表"""
    try:
        user_group = session.get('user_group', 'other')
        user_id = session.get('user_id')

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 1. 检查文件夹存在性和权限
            # 管理员(root/root2)可以访问所有(或大部分)文件夹
            # 普通用户只能访问 is_visible_to_all = TRUE 的文件夹

            sql_folder = "SELECT * FROM folders WHERE id = %s"
            cursor.execute(sql_folder, (folder_id,))
            folder = cursor.fetchone()

            if not folder:
                conn.close()
                return jsonify({'error': '文件夹不存在'}), 404

            has_permission = False

            if user_group == 'root2':
                has_permission = True
            elif user_group == 'root':
                # root 可以看自己的，或者公开的，或者其他root创建的
                if folder['created_by'] == user_id or folder['is_visible_to_all'] or folder['creator_group'] == 'root':
                    has_permission = True
            else:
                # 普通用户只能看公开的
                if folder['is_visible_to_all']:
                    has_permission = True

            if not has_permission:
                conn.close()
                return jsonify({'error': '没有权限访问此文件夹（文件夹未公开）'}), 403

            # 2. 获取文件夹中的文件
            sql = """
                SELECT 
                    stored_filename, 
                    original_filename as filename, 
                    file_size, 
                    upload_time, 
                    upload_username,
                    download_count,
                    file_category,
                    file_subcategory,
                    storage_type
                FROM file_info 
                WHERE folder_id = %s
                ORDER BY upload_time DESC
            """
            cursor.execute(sql, (folder_id,))
            files = cursor.fetchall()

            # 格式化时间
            for file in files:
                if isinstance(file['upload_time'], datetime):
                    file['upload_time'] = file['upload_time'].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    file['upload_time'] = str(file['upload_time'])

        conn.close()
        return jsonify({'files': files, 'folder': folder})
    except Exception as e:
        logger.error(f"获取文件夹文件列表错误: {str(e)}")
        return jsonify({'error': '获取文件夹文件列表失败'}), 500


# ========== 新增功能：文件重命名和子分类修改 ==========
@app.route('/rename_file/<string:stored_filename>', methods=['PUT'])
@login_required
@file_management_required
def rename_file(stored_filename):
    """文件重命名API（支持中文字符）"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        new_filename = data.get('new_filename')

        if not new_filename:
            return jsonify({'error': '新文件名不能为空'}), 400

        # 安全处理文件名，但保留中文字符
        # 使用自定义的安全文件名函数，避免过滤中文字符
        safe_new_filename = secure_filename_with_chinese(new_filename)

        if not safe_new_filename:
            return jsonify({'error': '文件名无效'}), 400

        # 从数据库获取文件信息
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT file_category, file_subcategory, storage_type FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

            if not file_info:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404

            category = file_info['file_category']
            subcategory = file_info['file_subcategory']
            storage_type = file_info['storage_type']

            # 检查新文件名是否已存在
            sql = "SELECT id FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (safe_new_filename,))
            if cursor.fetchone():
                conn.close()
                return jsonify({'error': '文件名已存在'}), 400

            # 获取文件路径
            old_paths = get_file_paths(stored_filename, category, subcategory)
            new_paths = get_file_paths(safe_new_filename, category, subcategory)

            # 移动文件到新文件名
            moved = False
            if storage_type == 'dual':
                # 移动两个位置的实体文件
                for location in ['primary', 'external']:
                    old_path = old_paths[location]
                    new_path = new_paths[location]

                    if os.path.exists(old_path):
                        shutil.move(old_path, new_path)
                        moved = True
            elif storage_type == 'external_with_link':
                # 移动外部存储的实体文件，重新创建软链接
                if os.path.exists(old_paths['external']):
                    shutil.move(old_paths['external'], new_paths['external'])
                    # 重新创建软链接
                    if os.path.exists(new_paths['primary']):
                        os.remove(new_paths['primary'])
                    os.symlink(new_paths['external'], new_paths['primary'])
                    moved = True
            elif storage_type == 'external_only':
                # 移动外部存储的实体文件
                if os.path.exists(old_paths['external']):
                    shutil.move(old_paths['external'], new_paths['external'])
                    moved = True
            elif storage_type == 'primary_only':
                # 移动主存储的实体文件
                if os.path.exists(old_paths['primary']):
                    shutil.move(old_paths['primary'], new_paths['primary'])
                    moved = True

            if moved:
                # 更新数据库记录
                sql = "UPDATE file_info SET stored_filename = %s, original_filename = %s WHERE stored_filename = %s"
                cursor.execute(sql, (safe_new_filename, new_filename, stored_filename))
                conn.commit()

                logger.info(f"文件重命名成功: {stored_filename} 改为 {safe_new_filename} (显示名: {new_filename})")
                conn.close()
                return jsonify({'success': True, 'message': '文件重命名成功'})
            else:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404

    except Exception as e:
        logger.error(f"文件重命名错误: {str(e)}")
        return jsonify({'error': '文件重命名失败'}), 500


@app.route('/update_subcategory/<string:stored_filename>', methods=['PUT'])
@login_required
@file_management_required
def update_file_subcategory(stored_filename):
    """更新文件子分类API"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        new_subcategory = data.get('subcategory')

        if new_subcategory not in app.config['SUBCATEGORIES']:
            return jsonify({'error': '无效的文件子分类'}), 400

        # 从数据库获取当前文件信息
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT file_category, file_subcategory, storage_type FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

            if not file_info:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404

            old_category = file_info['file_category']
            old_subcategory = file_info['file_subcategory']
            storage_type = file_info['storage_type']

            if old_subcategory == new_subcategory:
                conn.close()
                return jsonify({'success': True, 'message': '文件子分类未改变'})

            # 获取文件路径
            old_paths = get_file_paths(stored_filename, old_category, old_subcategory)
            new_paths = get_file_paths(stored_filename, old_category, new_subcategory)

            # 移动文件到新目录
            moved = False
            if storage_type == 'dual':
                # 移动两个位置的实体文件
                for location in ['primary', 'external']:
                    old_path = old_paths[location]
                    new_path = new_paths[location]

                    if os.path.exists(old_path):
                        shutil.move(old_path, new_path)
                        moved = True
            elif storage_type == 'external_with_link':
                # 移动外部存储的实体文件，重新创建软链接
                if os.path.exists(old_paths['external']):
                    shutil.move(old_paths['external'], new_paths['external'])
                    # 重新创建软链接
                    if os.path.exists(new_paths['primary']):
                        os.remove(new_paths['primary'])
                    os.symlink(new_paths['external'], new_paths['primary'])
                    moved = True
            elif storage_type == 'external_only':
                # 移动外部存储的实体文件
                if os.path.exists(old_paths['external']):
                    shutil.move(old_paths['external'], new_paths['external'])
                    moved = True
            elif storage_type == 'primary_only':
                # 移动主存储的实体文件
                if os.path.exists(old_paths['primary']):
                    shutil.move(old_paths['primary'], new_paths['primary'])
                    moved = True

            if moved:
                # 更新数据库记录
                sql = "UPDATE file_info SET file_subcategory = %s WHERE stored_filename = %s"
                cursor.execute(sql, (new_subcategory, stored_filename))
                conn.commit()

                logger.info(
                    f"文件子分类更新成功: {stored_filename} 从 {old_subcategory} 改为 {new_subcategory} 分类: {old_category}")
                conn.close()
                return jsonify({'success': True, 'message': '文件子分类更新成功'})
            else:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404

    except Exception as e:
        logger.error(f"更新文件子分类错误: {str(e)}")
        return jsonify({'error': '文件子分类更新失败'}), 500


@app.route('/update_category/<string:stored_filename>', methods=['PUT'])
@login_required
@permission_required('delete')
def update_file_category(stored_filename):
    """更新文件分类API"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        new_category = data.get('category')

        if new_category not in ['everyone', 'competition']:
            return jsonify({'error': '无效的文件分类'}), 400

        # 从数据库获取当前文件信息
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT file_category, file_subcategory, storage_type FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

            if not file_info:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404

            old_category = file_info['file_category']
            subcategory = file_info['file_subcategory']
            storage_type = file_info['storage_type']

            if old_category == new_category:
                conn.close()
                return jsonify({'success': True, 'message': '文件分类未改变'})

            # 获取文件路径
            old_paths = get_file_paths(stored_filename, old_category, subcategory)
            new_paths = get_file_paths(stored_filename, new_category, subcategory)

            # 移动文件到新目录
            moved = False
            if storage_type == 'dual':
                # 移动两个位置的实体文件
                for location in ['primary', 'external']:
                    old_path = old_paths[location]
                    new_path = new_paths[location]

                    if os.path.exists(old_path):
                        shutil.move(old_path, new_path)
                        moved = True
            elif storage_type == 'external_with_link':
                # 移动外部存储的实体文件，重新创建软链接
                if os.path.exists(old_paths['external']):
                    shutil.move(old_paths['external'], new_paths['external'])
                    # 重新创建软链接
                    if os.path.exists(new_paths['primary']):
                        os.remove(new_paths['primary'])
                    os.symlink(new_paths['external'], new_paths['primary'])
                    moved = True
            elif storage_type == 'external_only':
                # 移动外部存储的实体文件
                if os.path.exists(old_paths['external']):
                    shutil.move(old_paths['external'], new_paths['external'])
                    moved = True
            elif storage_type == 'primary_only':
                # 移动主存储的实体文件
                if os.path.exists(old_paths['primary']):
                    shutil.move(old_paths['primary'], new_paths['primary'])
                    moved = True

            if moved:
                # 更新数据库记录
                sql = "UPDATE file_info SET file_category = %s WHERE stored_filename = %s"
                cursor.execute(sql, (new_category, stored_filename))
                conn.commit()

                logger.info(
                    f"文件分类更新成功: {stored_filename} 从 {old_category} 改为 {new_category} 子分类: {subcategory}")
                conn.close()
                return jsonify({'success': True, 'message': '文件分类更新成功'})
            else:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404

    except Exception as e:
        logger.error(f"更新文件分类错误: {str(e)}")
        return jsonify({'error': '文件分类更新失败'}), 500


# ========== 错误处理 ==========
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': '资源未找到'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': '服务器内部错误'}), 500


@app.errorhandler(413)
def too_large(error):
    return jsonify({'error': '文件太大'}), 413


# ========== 主程序 ==========
if __name__ == '__main__':
    logger.info("启动Flask文件上传服务器（智能存储版本+权限管理）")
    logger.info("启动Flask文件上传服务器（优化大文件下载版本）")
    logger.info(f"主上传目录: {BASE_UPLOAD_FOLDER}")
    logger.info(f"外部上传目录: {EXTERNAL_UPLOAD_FOLDER}")
    logger.info(f"双存储阈值: {app.config['DUAL_STORAGE_THRESHOLD'] / (1024 * 1024)} MB")
    logger.info(f"最小剩余空间: {app.config['MIN_FREE_SPACE'] / (1024 * 1024 * 1024)} GB")
    logger.info(f"用户组权限配置: {app.config['USER_GROUPS']}")
    logger.info("启动优化版文件服务器（支持10GB+大文件下载）")

    # 检查目录权限
    for folder_name, folders in [('EVERYONE_FOLDERS', app.config['EVERYONE_FOLDERS']),
                                 ('COMPETITION_FOLDERS', app.config['COMPETITION_FOLDERS'])]:
        for location, folder_path in folders.items():
            if os.path.exists(folder_path):
                logger.info(f"目录 {folder_path} 存在，权限: {oct(os.stat(folder_path).st_mode)[-3:]}")
            else:
                logger.warning(f"目录 {folder_path} 不存在")

    # 测试数据库连接
    test_database_connection()

    # 初始化数据库表结构
    try:
        init_database()
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}")

    # 迁移现有文件到数据库
    migrate_existing_files()

    # 优化服务器配置
    # 在 app.config 部分添加
    app.config.update(
        MAX_CONTENT_LENGTH=100 * 1024 * 1024 * 1024,  # 100GB
        SEND_FILE_MAX_AGE_DEFAULT=0,
        TEMPLATES_AUTO_RELOAD=True,
        # 添加以下优化配置
        PREFERRED_URL_SCHEME='https',  # 如果使用HTTPS
        SONIFY_PRETTYPRINT_REGULAR=False,
        JSON_SORT_KEYS=False
    )

    port = find_available_port()
    if port is None:
        logger.error("找不到可用端口，服务器启动失败")
        exit(1)

    logger.info(f"服务器地址: http://localhost:{port}")
    if port != 5000:
        logger.warning(f"端口 5000 被占用，使用端口 {port}")

    try:
        # 尝试导入 Waitress
        from waitress import serve
        import logging as waitress_logging

        # 配置 Waitress 日志
        waitress_logger = waitress_logging.getLogger('waitress')
        waitress_logger.setLevel(waitress_logging.INFO)

        # 获取可用端口
        port = find_available_port()
        if port is None:
            logger.error("找不到可用端口")
            exit(1)

        logger.info(f"使用 Waitress 在生产模式启动服务器，端口: {port}")

        # 生产服务器配置
        serve(
            app,
            host='0.0.0.0',
            port=port,
            threads=8,
            connection_limit=1000,
            asyncore_use_poll=True,
            send_bytes=LargeFileConfig.CHUNK_SIZE,
            channel_timeout=LargeFileConfig.DOWNLOAD_TIMEOUT,
            cleanup_interval=300
        )

    except ImportError:
        logger.warning("Waitress 未安装，使用开发服务器")
        # 回退到开发服务器
        port = find_available_port()
        if port:
            app.run(
                debug=False,
                host='0.0.0.0',
                port=port,
                threaded=True,
                use_reloader=False,
                passthrough_errors=True
            )
        else:
            logger.error("找不到可用端口")#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import socket
import random
import string
import shutil
import json
from datetime import datetime
from flask import Flask, request, render_template, send_file, jsonify, session, Response
from werkzeug.utils import secure_filename
import pymysql
from pymysql.cursors import DictCursor
from functools import wraps

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('flask_upload.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 创建 Flask 应用
app = Flask(__name__)
app.secret_key = os.urandom(24)

# 配置文件上传参数
BASE_UPLOAD_FOLDER = '/root/flask_file_upload/uploads'
EXTERNAL_UPLOAD_FOLDER = '/mnt/uploads'

app.config['UPLOAD_FOLDER'] = BASE_UPLOAD_FOLDER
app.config['EXTERNAL_UPLOAD_FOLDER'] = EXTERNAL_UPLOAD_FOLDER

# 大文件下载优化配置
class LargeFileConfig:
    CHUNK_SIZE = 64 * 1024  # 64KB 块大小，减少内存使用
    STREAM_BUFFER_SIZE = 8192
    MAX_MEMORY_USAGE = 500 * 1024 * 1024  # 500MB 最大内存使用
    DOWNLOAD_TIMEOUT = 3600  # 1小时超时

# 存储配置
app.config['DUAL_STORAGE_THRESHOLD'] = 100 * 1024 * 1024  # 100MB
app.config['IMPORTANT_EXTENSIONS'] = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt']
app.config['MIN_FREE_SPACE'] = 1 * 1024 * 1024 * 1024  # 最小剩余空间1GB

# 子分类配置
app.config['SUBCATEGORIES'] = {
    'mirror': '镜像文件',
    'image': '图片文件',
    'document': '文档文件',
    'video': '视频文件',
    'other': '其他文件'
}

# 文件扩展名到子分类的映射
app.config['EXTENSION_MAPPING'] = {
    'mirror': ['.iso', '.img', '.vmdk', '.ova', '.qcow2'],
    'image': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp'],
    'document': ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.md'],
    'video': ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv', '.webm']
}

# 用户组权限配置
app.config['USER_GROUPS'] = {
    'root2': {
        'name': '超级管理员',
        'permissions': ['upload', 'download', 'delete', 'user_management', 'rename_files', 'change_subcategory']
    },
    'root': {
        'name': '管理员',
        'permissions': ['upload', 'download', 'delete', 'rename_files', 'change_subcategory']
    },
    'competition': {
        'name': '比赛用户',
        'permissions': ['upload', 'download', 'rename_files', 'change_subcategory']
    },
    'other': {
        'name': '普通用户',
        'permissions': ['download']
    }
}

# 存储目录
app.config['EVERYONE_FOLDERS'] = {
    'primary': os.path.join(BASE_UPLOAD_FOLDER, 'everyone'),
    'external': os.path.join(EXTERNAL_UPLOAD_FOLDER, 'everyone')
}

app.config['COMPETITION_FOLDERS'] = {
    'primary': os.path.join(BASE_UPLOAD_FOLDER, 'competition'),
    'external': os.path.join(EXTERNAL_UPLOAD_FOLDER, 'competition')
}

app.config['MAX_CONTENT_LENGTH'] = 70 * 1024 * 1024 * 1024
app.config['CHUNK_SIZE'] = 100 * 1024 * 1024

def init_subcategory_directories():
    """初始化子分类目录"""
    logger.info("开始初始化子分类目录")
    for category in ['everyone', 'competition']:
        for subcategory in app.config['SUBCATEGORIES'].keys():
            # 主存储目录
            primary_path = os.path.join(
                app.config[f'{category.upper()}_FOLDERS']['primary'],
                subcategory
            )
            # 外部存储目录
            external_path = os.path.join(
                app.config[f'{category.upper()}_FOLDERS']['external'],
                subcategory
            )

            os.makedirs(primary_path, exist_ok=True)
            os.makedirs(external_path, exist_ok=True)
            logger.info(f"创建目录: {primary_path}")
            logger.info(f"创建目录: {external_path}")

# 确保所有目录存在
try:
    for folders in [app.config['EVERYONE_FOLDERS'], app.config['COMPETITION_FOLDERS']]:
        for folder_path in folders.values():
            os.makedirs(folder_path, exist_ok=True)
    os.makedirs(os.path.join(BASE_UPLOAD_FOLDER, 'temp'), exist_ok=True)

    # 初始化子分类目录
    init_subcategory_directories()

    logger.info("所有目录创建成功")
except Exception as e:
    logger.error(f"目录创建失败: {str(e)}")

# 数据库配置
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'Key-1122',
    'db': 'file_manager',
    'charset': 'utf8mb4',
    'cursorclass': DictCursor
}

# ========== 权限检查装饰器 ==========
def permission_required(permission):
    """权限检查装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('logged_in'):
                return jsonify({'error': '需要登录'}), 401

            user_group = session.get('user_group', 'other')
            user_permissions = app.config['USER_GROUPS'].get(user_group, {}).get('permissions', [])

            if permission not in user_permissions:
                return jsonify({'error': '权限不足'}), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator

def root2_required(f):
    """root2组权限检查装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': '需要登录'}), 401

        if session.get('user_group') != 'root2':
            return jsonify({'error': '需要超级管理员权限'}), 403

        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """管理员权限检查装饰器（root2或root组）"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': '需要登录'}), 401

        user_group = session.get('user_group')
        if user_group not in ['root2', 'root']:
            return jsonify({'error': '需要管理员权限'}), 403

        return f(*args, **kwargs)
    return decorated_function

def file_management_required(f):
    """文件管理权限检查装饰器（root2、root、competition组）"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': '需要登录'}), 401

        user_group = session.get('user_group')
        if user_group not in ['root2', 'root', 'competition']:
            return jsonify({'error': '需要文件管理权限'}), 403

        return f(*args, **kwargs)
    return decorated_function

# ========== 数据库相关函数 ==========
def get_db_connection():
    """获取数据库连接"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"获取数据库连接失败: {str(e)}")
        raise

def init_database():
    """初始化数据库表结构（只在表不存在时创建）"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 创建用户表（如果不存在）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    password VARCHAR(255) NOT NULL,
                    email VARCHAR(255),
                    user_group ENUM('root2', 'root', 'competition', 'other') DEFAULT 'other',
                    chinese_alias VARCHAR(255),  -- 新增中文别名字段
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 创建文件夹表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS folders (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    path VARCHAR(500) NOT NULL UNIQUE,
                    created_by INT NOT NULL,
                    created_username VARCHAR(100) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    allowed_groups JSON NOT NULL,
                    is_visible_to_all BOOLEAN DEFAULT FALSE,
                    creator_group ENUM('root2', 'root', 'competition', 'other') DEFAULT 'other',
                    FOREIGN KEY (created_by) REFERENCES users(id)
                )
            """)

            # 创建文件信息表（如果不存在）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_info (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    stored_filename VARCHAR(255) NOT NULL UNIQUE,
                    original_filename VARCHAR(255) NOT NULL,
                    file_size BIGINT NOT NULL,
                    upload_time DATETIME NOT NULL,
                    upload_user_id INT NOT NULL,
                    upload_username VARCHAR(100) NOT NULL,
                    download_count INT DEFAULT 0,
                    file_category ENUM('everyone', 'competition') DEFAULT 'competition',
                    file_subcategory VARCHAR(50) DEFAULT 'other',
                    storage_type ENUM('dual', 'external_only', 'external_with_link', 'primary_only') DEFAULT 'dual',
                    folder_id INT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (upload_user_id) REFERENCES users(id),
                    FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL
                )
            """)

            # 创建下载日志表（如果不存在）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS download_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    file_id INT NOT NULL,
                    user_id INT NOT NULL,
                    username VARCHAR(100) NOT NULL,
                    download_time DATETIME NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 检查默认管理员用户是否存在，不存在则创建
            cursor.execute("SELECT id FROM users WHERE username = 'root2'")
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO users (username, password, email, user_group, chinese_alias) VALUES ('root2', 'Huang@-1122', '', 'root2', '超级管理员')"
                )
                logger.info("创建默认root2管理员用户")
            else:
                # 只更新用户组，不更新密码，避免重置密码
                cursor.execute(
                    "UPDATE users SET user_group = 'root2', chinese_alias = NULL WHERE username = 'root2'"
                )
                logger.info("确保root2用户的用户组正确")

            # 检查kfzxroot用户是否存在，不存在则创建
            cursor.execute("SELECT id FROM users WHERE username = 'kfzxroot'")
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO users (username, password, email, user_group, chinese_alias) VALUES ('kfzxroot', 'kfzx@-1122', 'admin@example.com', 'root', '管理员')"
                )
                logger.info("创建默认kfzxroot管理员用户")
            else:
                # 只更新用户组，不更新密码，避免重置密码
                cursor.execute(
                     "UPDATE users SET user_group = 'root', chinese_alias = NULL WHERE username = 'kfzxroot'"
                )
                logger.info("确保kfzxroot用户的用户组正确")

            # 删除可能存在的旧admin用户（只在不存在kfzxroot用户时）
            cursor.execute("SELECT id FROM users WHERE username = 'admin'")
            admin_user = cursor.fetchone()
            if admin_user:
                # 检查是否有其他管理员用户
                cursor.execute("SELECT COUNT(*) as admin_count FROM users WHERE user_group IN ('root2', 'root')")
                admin_count = cursor.fetchone()['admin_count']
                if admin_count > 0:
                    # 有其他管理员用户，可以安全删除admin用户
                    cursor.execute("DELETE FROM users WHERE username = 'admin'")
                    logger.info("删除旧的admin用户")
                else:
                    # 没有其他管理员用户，保留admin用户但更新其权限
                    cursor.execute("UPDATE users SET user_group = 'root' WHERE username = 'admin'")
                    logger.info("更新admin用户的用户组为root")

            conn.commit()
            logger.info("数据库表结构初始化成功")
    except Exception as e:
        logger.error(f"数据库表结构初始化失败: {str(e)}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

def test_database_connection():
    """测试数据库连接"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        conn.close()
        logger.info("数据库连接测试成功")
        return True
    except Exception as e:
        logger.error(f"数据库连接失败: {str(e)}")
        return False

# ========== 存储相关函数 ==========
def check_disk_space(path):
    """检查指定路径的磁盘空间"""
    try:
        stat = os.statvfs(path)
        free_space = stat.f_frsize * stat.f_bavail  # 可用空间（字节）
        return free_space
    except Exception as e:
        logger.error(f"检查磁盘空间错误 {path}: {str(e)}")
        return 0

def get_available_storage_locations(file_size, category, subcategory='other'):
    """获取可用的存储位置（考虑子分类目录）"""
    locations = []

    # 检查外部存储空间
    external_folder = os.path.join(
        app.config['EVERYONE_FOLDERS']['external'] if category == 'everyone' else app.config['COMPETITION_FOLDERS']['external'],
        subcategory
    )
    external_free = check_disk_space(external_folder)

    if external_free > file_size + app.config['MIN_FREE_SPACE']:
        locations.append('external')
        logger.info(f"外部存储可用: {external_free / (1024*1024*1024):.2f} GB 剩余 (子分类: {subcategory})")
    else:
        logger.warning(f"外部存储空间不足: {external_free / (1024*1024*1024):.2f} GB 剩余，需要 {file_size / (1024*1024*1024):.2f} GB (子分类: {subcategory})")

    # 检查主存储空间
    primary_folder = os.path.join(
        app.config['EVERYONE_FOLDERS']['primary'] if category == 'everyone' else app.config['COMPETITION_FOLDERS']['primary'],
        subcategory
    )
    primary_free = check_disk_space(primary_folder)

    if primary_free > file_size + app.config['MIN_FREE_SPACE']:
        locations.append('primary')
        logger.info(f"主存储可用: {primary_free / (1024*1024*1024):.2f} GB 剩余 (子分类: {subcategory})")
    else:
        logger.warning(f"主存储空间不足: {primary_free / (1024*1024*1024):.2f} GB 剩余，需要 {file_size / (1024*1024*1024):.2f} GB (子分类: {subcategory})")

    return locations

def get_file_paths(stored_filename, category, subcategory='other'):
    """根据文件名、分类和子分类获取所有存储路径"""
    if category == 'everyone':
        return {
            'primary': os.path.join(app.config['EVERYONE_FOLDERS']['primary'], subcategory, stored_filename),
            'external': os.path.join(app.config['EVERYONE_FOLDERS']['external'], subcategory, stored_filename)
        }
    else:
        return {
            'primary': os.path.join(app.config['COMPETITION_FOLDERS']['primary'], subcategory, stored_filename),
            'external': os.path.join(app.config['COMPETITION_FOLDERS']['external'], subcategory, stored_filename)
        }

def get_any_existing_file_path(stored_filename, category, subcategory='other'):
    """获取任何存在的文件路径（增强版本）"""
    try:
        logger.info(f"🔍 开始查找文件: {stored_filename}, 分类: {category}, 子分类: {subcategory}")

        # 新路径（有子分类）
        new_paths = get_file_paths(stored_filename, category, subcategory)

        # 旧路径（无子分类） - 兼容性支持
        old_paths = {}
        if category == 'everyone':
            old_paths = {
                'primary': os.path.join(app.config['EVERYONE_FOLDERS']['primary'], stored_filename),
                'external': os.path.join(app.config['EVERYONE_FOLDERS']['external'], stored_filename)
            }
        else:
            old_paths = {
                'primary': os.path.join(app.config['COMPETITION_FOLDERS']['primary'], stored_filename),
                'external': os.path.join(app.config['COMPETITION_FOLDERS']['external'], stored_filename)
            }

        # 检查所有可能的路径
        all_paths = []

        # 新路径
        for location in ['external', 'primary']:
            path = new_paths[location]
            all_paths.append(('新路径', location, path))

        # 旧路径
        for location in ['external', 'primary']:
            path = old_paths[location]
            all_paths.append(('旧路径', location, path))

        # 检查所有路径
        found_path = None
        for path_type, location, path in all_paths:
            logger.info(f"检查{path_type} {location}: {path}")
            if os.path.exists(path):
                logger.info(f"✅ 文件在{path_type} {location}找到: {path}")
                found_path = path
                break

        if not found_path:
            # 尝试模糊匹配
            logger.warning(f"精确匹配失败，尝试模糊匹配: {stored_filename}")
            fuzzy_path = find_file_by_fuzzy_match(stored_filename, category, subcategory)
            if fuzzy_path:
                logger.info(f"✅ 通过模糊匹配找到文件: {fuzzy_path}")
                found_path = fuzzy_path

        if not found_path:
            logger.error(f"❌ 文件不存在: {stored_filename}")
            for path_type, location, path in all_paths:
                logger.error(f"检查过的路径 - {path_type} {location}: {path}")

        return found_path

    except Exception as e:
        logger.error(f"获取文件路径失败: {str(e)}")
        return None

def find_file_by_fuzzy_match(stored_filename, category, subcategory='other'):
    """通过模糊匹配查找文件（处理拼写错误）"""
    try:
        # 获取基础目录
        if category == 'everyone':
            base_dirs = [
                app.config['EVERYONE_FOLDERS']['primary'],
                app.config['EVERYONE_FOLDERS']['external']
            ]
        else:
            base_dirs = [
                app.config['COMPETITION_FOLDERS']['primary'],
                app.config['COMPETITION_FOLDERS']['external']
            ]

        # 可能的子分类目录
        subcategories = list(app.config['SUBCATEGORIES'].keys()) + ['']

        for base_dir in base_dirs:
            for subcat in subcategories:
                search_dir = os.path.join(base_dir, subcat) if subcat else base_dir
                if not os.path.exists(search_dir):
                    continue

                # 列出目录中的所有文件
                for filename in os.listdir(search_dir):
                    file_path = os.path.join(search_dir, filename)
                    if os.path.isfile(file_path):
                        # 简单的模糊匹配：检查文件名是否包含关键部分
                        if ('network' in filename.lower() and 'zip' in filename.lower() and
                            'network' in stored_filename.lower()):
                            logger.info(f"模糊匹配成功: {filename} -> {stored_filename}")
                            return file_path
                        # 检查常见的拼写错误模式
                        if (stored_filename.replace('world', 'work') in filename or
                            stored_filename.replace('work', 'world') in filename):
                            logger.info(f"拼写错误纠正: {filename} -> {stored_filename}")
                            return file_path

        return None
    except Exception as e:
        logger.error(f"模糊匹配失败: {str(e)}")
        return None

def get_unique_filename(filename, category, subcategory='other'):
    """生成唯一文件名，重名时在两个位置检查"""
    name, ext = os.path.splitext(filename)

    if category == 'everyone':
        folders = app.config['EVERYONE_FOLDERS']
    else:
        folders = app.config['COMPETITION_FOLDERS']

    candidate = f"{name}{ext}"

    def file_exists_in_any_location(candidate_name):
        for folder_path in folders.values():
            file_path = os.path.join(folder_path, subcategory, candidate_name)
            if os.path.exists(file_path):
                return True
        return False

    counter = 1
    while file_exists_in_any_location(candidate):
        candidate = f"{name}_{counter}{ext}"
        counter += 1

    return candidate

def detect_file_subcategory(filename):
    """根据文件扩展名自动检测文件子分类"""
    ext = os.path.splitext(filename.lower())[1]

    for subcategory, extensions in app.config['EXTENSION_MAPPING'].items():
        if ext in extensions:
            return subcategory

    return 'other'

def smart_file_storage(file, stored_filename, category, subcategory='other'):
    """智能文件存储：根据可用空间自动选择存储位置"""
    paths = get_file_paths(stored_filename, category, subcategory)

    try:
        # 读取文件内容并获取文件大小
        file_content = file.read()
        file_size = len(file_content)

        # 获取可用的存储位置
        available_locations = get_available_storage_locations(file_size, category, subcategory)

        if not available_locations:
            return False, None, "所有存储位置空间不足"

        storage_type = ""
        saved_locations = []

        # 判断是否重要文件
        filename_lower = stored_filename.lower()
        is_important = any(filename_lower.endswith(ext) for ext in app.config['IMPORTANT_EXTENSIONS'])
        should_dual_store = is_important or file_size < app.config['DUAL_STORAGE_THRESHOLD']

        # 存储策略
        if should_dual_store and 'external' in available_locations and 'primary' in available_locations:
            # 双存储：两个位置都可用
            with open(paths['external'], 'wb') as f:
                f.write(file_content)
            with open(paths['primary'], 'wb') as f:
                f.write(file_content)
            storage_type = 'dual'
            saved_locations = ['external', 'primary']
            logger.info(f"文件双存储: {stored_filename} (大小: {file_size} bytes, 子分类: {subcategory})")

        elif 'external' in available_locations:
            # 只存储到外部
            with open(paths['external'], 'wb') as f:
                f.write(file_content)

            if 'primary' in available_locations:
                # 在主存储创建软链接
                if os.path.exists(paths['primary']):
                    os.remove(paths['primary'])
                os.symlink(paths['external'], paths['primary'])
                storage_type = 'external_with_link'
                saved_locations = ['external', 'primary_link']
            else:
                storage_type = 'external_only'
                saved_locations = ['external']

            logger.info(f"文件外部存储: {stored_filename} (大小: {file_size} bytes, 子分类: {subcategory})")

        elif 'primary' in available_locations:
            # 只存储到主存储
            with open(paths['primary'], 'wb') as f:
                f.write(file_content)
            storage_type = 'primary_only'
            saved_locations = ['primary']
            logger.info(f"文件主存储: {stored_filename} (大小: {file_size} bytes, 子分类: {subcategory})")

        else:
            return False, None, "没有可用的存储位置"

        return True, storage_type, None

    except Exception as e:
        error_msg = f"文件保存失败: {str(e)}"
        logger.error(error_msg)
        # 清理可能已保存的文件
        for location in ['external', 'primary']:
            path = paths[location]
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
        return False, None, error_msg

# ========== 工具函数 ==========
def hash_password(password):
    """密码保持明文存储"""
    return password

def generate_captcha(length=4):
    """生成随机验证码"""
    try:
        characters = string.ascii_uppercase + string.digits
        return ''.join(random.choice(characters) for _ in range(length))
    except Exception as e:
        logger.error(f"生成验证码内容错误: {str(e)}")
        # 返回一个默认验证码以防万一
        return "ABCD"

def secure_filename_with_chinese(filename):
    """安全文件名处理，但保留中文字符"""
    import re
    # 保留中文字符、字母、数字、下划线、点、连字符、空格
    pattern = re.compile(r'[^\u4e00-\u9fa5a-zA-Z0-9_\-. ]')
    filename = pattern.sub('', filename)

    # 去除路径分隔符
    filename = filename.replace('/', '').replace('\\', '')

    # 确保文件名不为空
    if not filename or filename in ('.', '..'):
        return None

    return filename


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': '需要登录'}), 401
        return f(*args, **kwargs)
    return decorated_function

def is_port_in_use(port, host='0.0.0.0'):
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except socket.error:
            return True

def find_available_port(start_port=5000, max_attempts=10):
    """查找可用的端口"""
    for port in range(start_port, start_port + max_attempts):
        if not is_port_in_use(port):
            return port
    return None

# ========== 用户信息管理路由 ==========
@app.route('/user/profile', methods=['GET'])
@login_required
def get_user_profile():
    """获取当前用户信息"""
    try:
        user_id = session.get('user_id')
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT username, email, user_group, chinese_alias FROM users WHERE id = %s"
            cursor.execute(sql, (user_id,))
            user = cursor.fetchone()

        conn.close()

        if user:
            return jsonify({
                'username': user['username'],
                'email': user['email'] or '',
                'user_group': user['user_group'],
                'chinese_alias': user['chinese_alias'] or ''
            })
        else:
            return jsonify({'error': '用户不存在'}), 404
    except Exception as e:
        logger.error(f"获取用户信息错误: {str(e)}")
        return jsonify({'error': '获取用户信息失败'}), 500

@app.route('/user/profile', methods=['PUT'])
@login_required
def update_user_profile():
    """更新当前用户信息"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        new_username = data.get('username')
        new_chinese_alias = data.get('chinese_alias')
        new_password = data.get('password')

        user_id = session.get('user_id')
        current_username = session.get('username')

        if not new_username:
            return jsonify({'error': '用户名不能为空'}), 400

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查新用户名是否已被其他用户使用
            sql = "SELECT id FROM users WHERE username = %s AND id != %s"
            cursor.execute(sql, (new_username, user_id))
            if cursor.fetchone():
                conn.close()
                return jsonify({'error': '用户名已存在'}), 400

            # 更新用户信息
            if new_password:
                # 更新密码
                hashed_password = hash_password(new_password)
                sql = "UPDATE users SET username = %s, chinese_alias = %s, password = %s WHERE id = %s"
                cursor.execute(sql, (new_username, new_chinese_alias, hashed_password, user_id))
            else:
                # 不更新密码
                sql = "UPDATE users SET username = %s, chinese_alias = %s WHERE id = %s"
                cursor.execute(sql, (new_username, new_chinese_alias, user_id))

            conn.commit()

        conn.close()

        # 更新session中的用户名
        session['username'] = new_username

        logger.info(f"用户信息更新成功: 用户ID {user_id}, 新用户名: {new_username}")
        return jsonify({'success': True, 'message': '用户信息更新成功'})
    except Exception as e:
        logger.error(f"更新用户信息错误: {str(e)}")
        return jsonify({'error': '用户信息更新失败'}), 500

@app.route('/users/<int:user_id>/chinese_alias', methods=['PUT'])
@admin_required
def update_user_chinese_alias(user_id):
    """管理员更新用户中文别名"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        new_chinese_alias = data.get('chinese_alias')

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查用户是否存在
            sql = "SELECT username, user_group FROM users WHERE id = %s"
            cursor.execute(sql, (user_id,))
            user = cursor.fetchone()

            if not user:
                conn.close()
                return jsonify({'error': '用户不存在'}), 404

            # 检查权限：非root2用户不能修改root2用户的信息
            current_user_group = session.get('user_group')
            if current_user_group != 'root2' and user['user_group'] == 'root2':
                conn.close()
                return jsonify({'error': '没有权限修改超级管理员信息'}), 403

            # 更新中文别名
            sql = "UPDATE users SET chinese_alias = %s WHERE id = %s"
            cursor.execute(sql, (new_chinese_alias, user_id))
            conn.commit()

        conn.close()
        logger.info(f"用户中文别名更新成功: 用户ID {user_id}, 中文别名: {new_chinese_alias}")
        return jsonify({'success': True, 'message': '中文别名更新成功'})
    except Exception as e:
        logger.error(f"更新用户中文别名错误: {str(e)}")
        return jsonify({'error': '中文别名更新失败'}), 500

# ========== 用户管理函数 ==========
def get_user_permissions(user_group):
    """获取用户组权限"""
    group_config = app.config['USER_GROUPS'].get(user_group, {})
    return group_config.get('permissions', [])

def can_manage_users(current_user_group, target_user_current_group, new_group=None):
    """检查是否可以管理目标用户组"""
    if current_user_group == 'root2':
        # root2可以管理所有用户组
        return True
    elif current_user_group == 'root':
        # root可以管理除root2外的其他用户组
        # 不能管理已经是root2的用户，也不能将用户改为root2组
        if target_user_current_group == 'root2':
            return False
        if new_group == 'root2':
            return False
        return True
    else:
        # 其他用户组不能管理用户
        return False

# ========== 数据库操作函数 ==========
def record_file_upload(stored_filename, original_filename, file_size, user_id, username, category='competition', subcategory='other', storage_type='dual', folder_id=None):
    """记录文件上传信息到数据库"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO file_info 
                (stored_filename, original_filename, file_size, upload_time, upload_user_id, upload_username, download_count, file_category, file_subcategory, storage_type, folder_id)
                VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s)
            """
            cursor.execute(sql, (
                stored_filename,
                original_filename,  # 这里存储原始文件名（包含中文）
                file_size,
                datetime.now(),
                user_id,
                username,
                category,
                subcategory,
                storage_type,
                folder_id
            ))
            conn.commit()
        conn.close()
        logger.info(f"文件信息记录成功: {stored_filename} 原始文件名: {original_filename} 存储类型: {storage_type} 子分类: {subcategory} 文件夹ID: {folder_id}")
        return True, None
    except Exception as e:
        error_msg = f"记录文件信息失败: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def record_file_download(stored_filename, user_id, username):
    """记录文件下载信息到数据库"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 首先获取文件ID
            sql = "SELECT id FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

            if file_info:
                file_id = file_info['id']

                # 插入下载记录
                sql = """
                    INSERT INTO download_logs 
                    (file_id, user_id, username, download_time)
                    VALUES (%s, %s, %s, %s)
                """
                cursor.execute(sql, (
                    file_id,
                    user_id,
                    username,
                    datetime.now()
                ))

                # 更新下载次数
                sql = "UPDATE file_info SET download_count = download_count + 1 WHERE id = %s"
                cursor.execute(sql, (file_id,))

                conn.commit()
                logger.info(f"文件下载记录成功: {stored_filename} 下载者: {username}")
        conn.close()
        return True
    except Exception as e:
        logger.error(f"记录文件下载信息失败: {str(e)}")
        return False

def get_all_files_from_database(category=None, subcategory=None, user_group='other', search=None):
    """
    从数据库获取文件列表
    (MODIFIED for Feature 2: Added 'search' parameter and dynamic query building)
    """
    files = []
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:

            base_sql = """
                SELECT 
                    stored_filename, 
                    original_filename as filename, 
                    file_size, 
                    upload_time, 
                    upload_username,
                    download_count,
                    file_category,
                    file_subcategory,
                    storage_type
                FROM file_info
            """

            where_clauses = []
            params = []

            # 1. 用户组权限 (other组只能看everyone)
            if user_group == 'other':
                where_clauses.append("file_category = 'everyone'")

            # 2. 分类筛选
            if category:
                # 'other' 组用户请求非 'everyone' 文件, 在 'user_group' 检查中已处理
                if user_group != 'other' or category == 'everyone':
                    where_clauses.append("file_category = %s")
                    params.append(category)
                elif user_group == 'other' and category != 'everyone':
                    # This case will result in 0 files, which is correct.
                    # Add a clause that is always false
                    where_clauses.append("1 = 0")

            # 3. 子分类筛选
            if subcategory:
                where_clauses.append("file_subcategory = %s")
                params.append(subcategory)

            # 4. 搜索筛选 (NEW)
            if search:
                where_clauses.append("(original_filename LIKE %s OR stored_filename LIKE %s)")
                search_term = f"%{search}%"
                params.append(search_term)
                params.append(search_term)

            # 组合查询
            if where_clauses:
                base_sql += " WHERE " + " AND ".join(where_clauses)

            base_sql += " ORDER BY upload_time DESC"

            cursor.execute(base_sql, tuple(params))
            files = cursor.fetchall()

            logger.info(f"从数据库获取到 {len(files)} 个文件 (用户组: {user_group}, 筛选: c={category}, s={subcategory}, q={search})")

            # 格式化时间
            for file in files:
                if isinstance(file['upload_time'], datetime):
                    file['upload_time'] = file['upload_time'].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    file['upload_time'] = str(file['upload_time'])

        conn.close()
    except Exception as e:
        logger.error(f"从数据库获取文件列表错误: {str(e)}")
    return files

def migrate_existing_files():
    """将系统中已存在的文件迁移到数据库（检查两个存储位置）"""
    try:
        logger.info("开始迁移现有文件（检查两个存储位置）")

        all_files = []

        # 检查两个分类目录在两个存储位置中的文件
        for category in ['everyone', 'competition']:
            folders = app.config[f'{category.upper()}_FOLDERS']

            for location, folder_path in folders.items():
                if os.path.exists(folder_path):
                    # 遍历所有子分类目录
                    for subcategory in app.config['SUBCATEGORIES'].keys():
                        subcategory_path = os.path.join(folder_path, subcategory)
                        if os.path.exists(subcategory_path):
                            files = [f for f in os.listdir(subcategory_path)
                                    if os.path.isfile(os.path.join(subcategory_path, f))]

                            for filename in files:
                                file_path = os.path.join(subcategory_path, filename)
                                if os.path.isfile(file_path):
                                    all_files.append((category, subcategory, filename, file_path, location))

        logger.info(f"发现 {len(all_files)} 个文件需要检查迁移")

        if not all_files:
            logger.info("上传目录中没有文件需要迁移")
            return

        conn = get_db_connection()

        with conn.cursor() as cursor:
            # 获取数据库中已记录的文件名
            sql = "SELECT stored_filename FROM file_info"
            cursor.execute(sql)
            db_files = [row['stored_filename'] for row in cursor.fetchall()]

            # 找出需要迁移的文件
            files_to_migrate = [f for f in all_files if f[2] not in db_files]

            if files_to_migrate:
                logger.info(f"发现 {len(files_to_migrate)} 个文件需要迁移到数据库")

                # 检查是否已有admin用户，如果没有则创建
                cursor.execute("SELECT id FROM users WHERE username = 'admin'")
                admin_user = cursor.fetchone()
                if not admin_user:
                    cursor.execute(
                        "INSERT INTO users (username, password, email) VALUES ('admin', 'admin123', 'admin@example.com')"
                    )
                    admin_id = cursor.lastrowid
                    conn.commit()
                else:
                    admin_id = admin_user['id']

                migrated_count = 0
                for category, subcategory, stored_filename, file_path, location in files_to_migrate:
                    if os.path.isfile(file_path):
                        try:
                            file_size = os.path.getsize(file_path)
                            upload_time = datetime.fromtimestamp(os.path.getctime(file_path))

                            # 判断存储类型
                            if location == 'primary':
                                # 检查外部存储是否也有相同文件
                                external_path = get_file_paths(stored_filename, category, subcategory)['external']
                                if os.path.exists(external_path):
                                    storage_type = 'dual'
                                else:
                                    storage_type = 'primary_only'
                            else:  # external
                                # 检查主存储是否也有相同文件
                                primary_path = get_file_paths(stored_filename, category, subcategory)['primary']
                                if os.path.exists(primary_path):
                                    storage_type = 'dual'
                                else:
                                    storage_type = 'external_only'

                            # 插入数据库记录
                            sql = """
                                INSERT INTO file_info 
                                (stored_filename, original_filename, file_size, upload_time, upload_user_id, upload_username, download_count, file_category, file_subcategory, storage_type)
                                VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s, %s)
                            """
                            cursor.execute(sql, (
                                stored_filename,
                                stored_filename,  # 使用存储的文件名作为原始文件名
                                file_size,
                                upload_time,
                                admin_id,
                                'admin',
                                category,
                                subcategory,
                                storage_type
                            ))
                            migrated_count += 1
                            logger.info(f"迁移文件: {stored_filename} 分类: {category} 子分类: {subcategory} 位置: {location} 存储类型: {storage_type}")
                        except Exception as e:
                            logger.error(f"迁移文件失败 {stored_filename}: {str(e)}")

                conn.commit()
                logger.info(f"成功迁移 {migrated_count} 个文件到数据库")
            else:
                logger.info("没有需要迁移的文件")

        conn.close()
    except Exception as e:
        logger.error(f"迁移现有文件失败: {str(e)}")

# ========== 路由定义 ==========
@app.route('/')
def index():
    """首页路由"""
    return render_template('index.html')

@app.route('/get_captcha')
def get_captcha():
    """获取验证码API"""
    try:
        captcha_text = generate_captcha()
        if not captcha_text:
            logger.error("生成的验证码为空")
            captcha_text = "ABCD"  # 默认值

        session['captcha'] = captcha_text
        session['captcha_time'] = time.time()

        logger.info(f"生成验证码成功: {captcha_text}")
        return jsonify({'captcha': captcha_text})

    except Exception as e:
        logger.error(f"生成验证码错误: {str(e)}", exc_info=True)
        # 返回一个默认验证码，避免前端完全无法使用
        default_captcha = "1234"
        session['captcha'] = default_captcha
        session['captcha_time'] = time.time()
        return jsonify({'captcha': default_captcha})

@app.route('/register', methods=['POST'])
def register():
    """用户注册API"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        email = data.get('email', '')
        chinese_alias = data.get('chinese_alias', '')  # 新增中文别名

        logger.info(f"注册尝试: 用户名={username}, 邮箱={email}, 中文别名={chinese_alias}")

        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400

        # 密码明文存储
        hashed_password = hash_password(password)

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查用户名是否已存在
            sql = "SELECT id FROM users WHERE username = %s"
            cursor.execute(sql, (username,))
            if cursor.fetchone():
                conn.close()
                logger.warning(f"用户名已存在: {username}")
                return jsonify({'success': False, 'message': '用户名已存在'}), 400

            # 插入新用户，默认属于other组
            sql = "INSERT INTO users (username, password, email, user_group, chinese_alias) VALUES (%s, %s, %s, 'other', %s)"
            cursor.execute(sql, (username, hashed_password, email, chinese_alias))
            conn.commit()

        conn.close()
        logger.info(f"用户注册成功: {username} 来自 {request.remote_addr}, 默认分配到other组, 中文别名: {chinese_alias}")
        return jsonify({'success': True, 'message': '注册成功'})

    except Exception as e:
        logger.error(f"注册错误: {str(e)}")
        import traceback
        logger.error(f"注册详细错误: {traceback.format_exc()}")
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500

@app.route('/login', methods=['POST'])
def login():
    """登录API"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        captcha = data.get('captcha', '')

        logger.info(f"登录尝试来自: {request.remote_addr}，用户: {username}")

        # 验证验证码
        session_captcha = session.get('captcha')
        captcha_time = session.get('captcha_time', 0)

        # 验证码有效期5分钟
        if not session_captcha or time.time() - captcha_time > 300:
            return jsonify({'success': False, 'message': '验证码已过期，请刷新'}), 401

        if not captcha or captcha.upper() != session_captcha:
            # 验证码错误时清除session中的验证码，强制刷新
            session.pop('captcha', None)
            session.pop('captcha_time', None)
            return jsonify({'success': False, 'message': '验证码错误'}), 401

        # 密码明文验证
        hashed_password = hash_password(password)

        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT id, username, user_group FROM users WHERE username = %s AND password = %s"
            cursor.execute(sql, (username, hashed_password))
            user = cursor.fetchone()

        conn.close()

        if user:
            # 登录成功后清除验证码
            session.pop('captcha', None)
            session.pop('captcha_time', None)
            session['logged_in'] = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['user_group'] = user['user_group']  # 添加用户组信息

            logger.info(f"用户登录成功: {username} 用户组: {user['user_group']}")
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': '用户名或密码错误'}), 401

    except Exception as e:
        logger.error(f"登录错误: {str(e)}")
        return jsonify({'success': False, 'message': '服务器错误'}), 500

@app.route('/logout', methods=['POST'])
def logout():
    """退出登录API"""
    session.pop('logged_in', None)
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('user_group', None)
    return jsonify({'success': True})

@app.route('/check_login')
def check_login():
    return jsonify({
        'logged_in': session.get('logged_in', False),
        'username': session.get('username', ''),
        'user_group': session.get('user_group', 'other'),
        'user_id': session.get('user_id')  # 新增用户ID
    })

# ========== 用户管理路由 ==========
@app.route('/users', methods=['GET'])
@admin_required  # 改为admin_required，允许root和root2访问
def list_users():
    """获取所有用户列表（root2和root可访问）"""
    try:
        current_user_group = session.get('user_group')
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT id, username, email, user_group, chinese_alias, created_at FROM users ORDER BY created_at DESC"
            cursor.execute(sql)
            users = cursor.fetchall()

            # 如果不是root2用户，隐藏root2用户的用户名
            if current_user_group != 'root2':
                for user in users:
                    if user['user_group'] == 'root2':
                        user['username'] = '******'  # 隐藏用户名
                        user['email'] = '******'     # 隐藏邮箱

            # 格式化时间
            for user in users:
                if isinstance(user['created_at'], datetime):
                    user['created_at'] = user['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    user['created_at'] = str(user['created_at'])

        conn.close()
        return jsonify({'users': users})
    except Exception as e:
        logger.error(f"获取用户列表错误: {str(e)}")
        return jsonify({'error': '获取用户列表失败'}), 500

@app.route('/users/<int:user_id>', methods=['PUT'])
@admin_required  # 改为admin_required，允许root和root2访问
def update_user(user_id):
    """更新用户信息（root2和root可访问）"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        new_group = data.get('user_group')

        if new_group not in app.config['USER_GROUPS']:
            return jsonify({'error': '无效的用户组'}), 400

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查目标用户是否存在
            sql = "SELECT username, user_group FROM users WHERE id = %s"
            cursor.execute(sql, (user_id,))
            target_user = cursor.fetchone()

            if not target_user:
                conn.close()
                return jsonify({'error': '用户不存在'}), 404

            # 检查是否可以管理目标用户
            current_user_group = session.get('user_group')
            if not can_manage_users(current_user_group, target_user['user_group'], new_group):
                conn.close()
                return jsonify({'error': '没有权限管理该用户'}), 403

            # 更新用户组
            sql = "UPDATE users SET user_group = %s WHERE id = %s"
            cursor.execute(sql, (new_group, user_id))
            conn.commit()

        conn.close()
        logger.info(f"用户组更新成功: 用户ID {user_id} 改为 {new_group}")
        return jsonify({'success': True, 'message': '用户组更新成功'})
    except Exception as e:
        logger.error(f"更新用户组错误: {str(e)}")
        return jsonify({'error': '用户组更新失败'}), 500

@app.route('/user/permissions')
@login_required
def get_user_permissions_info():
    """获取当前用户的权限信息"""
    try:
        user_group = session.get('user_group', 'other')
        permissions = get_user_permissions(user_group)
        group_name = app.config['USER_GROUPS'].get(user_group, {}).get('name', '未知用户组')

        # 修改：root和root2都可以管理用户
        can_manage_users = user_group in ['root2', 'root']

        return jsonify({
            'user_group': user_group,
            'group_name': group_name,
            'permissions': permissions,
            'can_manage_users': can_manage_users
        })
    except Exception as e:
        logger.error(f"获取用户权限信息错误: {str(e)}")
        return jsonify({'error': '获取权限信息失败'}), 500


# ========== 用户管理路由 - 添加删除功能 ==========
@app.route('/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """
    删除用户
    (MODIFIED for Feature 3: Added 'force' parameter to re-assign data and delete user)
    """
    try:
        force = request.args.get('force', 'false').lower() == 'true'
        current_user_id = session.get('user_id')
        current_username = session.get('username')
        current_user_group = session.get('user_group')

        # 只有root2可以删除用户
        if current_user_group != 'root2':
            return jsonify({'error': '需要超级管理员权限才能删除用户'}), 403

        # 不能删除自己
        if user_id == current_user_id:
            return jsonify({'error': '不能删除当前登录的用户'}), 400

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查目标用户是否存在
            sql = "SELECT username, user_group FROM users WHERE id = %s"
            cursor.execute(sql, (user_id,))
            target_user = cursor.fetchone()

            if not target_user:
                conn.close()
                return jsonify({'error': '用户不存在'}), 404

            # root2不能删除其他root2用户（只能删除自己以外的root、competition、other用户）
            if target_user['user_group'] == 'root2':
                conn.close()
                return jsonify({'error': '不能删除其他超级管理员用户'}), 403

            # 检查用户是否有文件记录
            sql = "SELECT COUNT(*) as file_count FROM file_info WHERE upload_user_id = %s"
            cursor.execute(sql, (user_id,))
            file_count = cursor.fetchone()['file_count']

            # 检查用户是否有文件夹
            sql = "SELECT COUNT(*) as folder_count FROM folders WHERE created_by = %s"
            cursor.execute(sql, (user_id,))
            folder_count = cursor.fetchone()['folder_count']

            # 检查用户是否有下载记录
            sql = "SELECT COUNT(*) as download_count FROM download_logs WHERE user_id = %s"
            cursor.execute(sql, (user_id,))
            download_count = cursor.fetchone()['download_count']

            has_related_data = file_count > 0 or folder_count > 0 or download_count > 0

            if has_related_data and not force:
                conn.close()
                return jsonify({
                    'error': '用户有关联数据，无法删除',
                    'details': {
                        'file_count': file_count,
                        'folder_count': folder_count,
                        'download_count': download_count
                    }
                }), 400

            if has_related_data and force:
                logger.warning(f"强制删除用户 {user_id} ({target_user['username']}). 数据将转移给 {current_username} (ID: {current_user_id})")

                # 1. 转移文件
                sql = "UPDATE file_info SET upload_user_id = %s, upload_username = %s WHERE upload_user_id = %s"
                cursor.execute(sql, (current_user_id, current_username, user_id))

                # 2. 转移文件夹
                sql = "UPDATE folders SET created_by = %s, created_username = %s WHERE created_by = %s"
                cursor.execute(sql, (current_user_id, current_username, user_id))

                # 3. 删除下载日志 (这些只是日志，可以直接删除)
                sql = "DELETE FROM download_logs WHERE user_id = %s"
                cursor.execute(sql, (user_id,))

                conn.commit()
                logger.info(f"用户 {user_id} 的关联数据已转移给用户 {current_user_id}")

            # (Now safe to) 删除用户
            sql = "DELETE FROM users WHERE id = %s"
            cursor.execute(sql, (user_id,))
            conn.commit()

        conn.close()

        if has_related_data and force:
            logger.info(f"用户已强制删除: 用户ID {user_id} 用户名: {target_user['username']}")
            return jsonify({'success': True, 'message': '用户已强制删除，数据已转移'})
        else:
            logger.info(f"用户删除成功: 用户ID {user_id} 用户名: {target_user['username']}")
            return jsonify({'success': True, 'message': '用户删除成功'})

    except Exception as e:
        logger.error(f"删除用户错误: {str(e)}")
        return jsonify({'error': '用户删除失败'}), 500


# ========== 文件操作路由 ==========
@app.route('/files')
@login_required
@permission_required('download')
def list_files():
    """
    获取所有文件列表（从数据库读取）
    (MODIFIED for Feature 2: Added 'search' parameter)
    """
    try:
        category = request.args.get('category', None)
        subcategory = request.args.get('subcategory', None)
        search = request.args.get('search', None) # NEW
        user_group = session.get('user_group', 'other')

        all_files = get_all_files_from_database(category, subcategory, user_group, search)

        return jsonify({'files': all_files})
    except Exception as e:
        logger.error(f"获取文件列表错误: {str(e)}")
        return jsonify({'error': '获取文件列表失败'}), 500

@app.route('/subcategories')
@login_required
def get_subcategories():
    """获取所有子分类"""
    return jsonify({
        'subcategories': app.config['SUBCATEGORIES'],
        'extension_mapping': app.config['EXTENSION_MAPPING']
    })

@app.route('/upload', methods=['POST'])
@login_required
@permission_required('upload')
def upload_file():
    """文件上传API（智能存储策略）"""
    try:
        logger.info("开始文件上传处理（智能存储）")

        if 'file' not in request.files:
            return jsonify({'error': '没有文件部分'}), 400

        file = request.files['file']
        category = request.form.get('category', 'competition')
        subcategory = request.form.get('subcategory', 'other')
        folder_id = request.form.get('folder_id', None)  # 新增文件夹ID参数

        logger.info(f"收到上传请求: 文件名={file.filename}, 分类={category}, 子分类={subcategory}, 文件夹ID={folder_id}")

        if file.filename == '':
            return jsonify({'error': '没有选择文件'}), 400

        if category not in ['everyone', 'competition']:
            category = 'competition'

        if subcategory not in app.config['SUBCATEGORIES']:
            # 自动检测文件子分类
            subcategory = detect_file_subcategory(file.filename)
            logger.info(f"自动检测文件子分类: {subcategory}")

        # 生成唯一文件名 - 使用支持中文的函数
        original_filename = secure_filename_with_chinese(file.filename)
        if not original_filename:
            original_filename = "unnamed_file"  # 如果文件名无效，使用默认名称

        stored_filename = get_unique_filename(original_filename, category, subcategory)

        logger.info(f"准备保存文件: {stored_filename} 到子分类: {subcategory}")

        # 使用智能存储策略保存文件
        success, storage_type, save_error = smart_file_storage(file, stored_filename, category, subcategory)
        if not success:
            return jsonify({'error': f'文件保存失败: {save_error}'}), 500

        logger.info(f"文件保存成功: {stored_filename} 存储类型: {storage_type} 子分类: {subcategory}")

        # 记录文件信息到数据库 - 使用原始文件名（包含中文）
        file_path = get_file_paths(stored_filename, category, subcategory)['external'] if storage_type != 'primary_only' else get_file_paths(stored_filename, category, subcategory)['primary']
        file_size = os.path.getsize(file_path)
        user_id = session.get('user_id')
        username = session.get('username')

        # 如果有文件夹ID，验证用户是否有权限上传到该文件夹
        if folder_id:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                sql = "SELECT created_by, allowed_groups, is_visible_to_all, creator_group FROM folders WHERE id = %s"
                cursor.execute(sql, (folder_id,))
                folder = cursor.fetchone()

                if not folder:
                    conn.close()
                    # 删除已上传的文件
                    paths = get_file_paths(stored_filename, category, subcategory)
                    for path in paths.values():
                        if os.path.exists(path) and not os.path.islink(path):
                            os.remove(path)
                        elif os.path.islink(path):
                            os.unlink(path)
                    return jsonify({'error': '文件夹不存在'}), 404

                # 检查权限
                user_group = session.get('user_group')
                has_permission = (
                    folder['created_by'] == user_id or
                    user_group in json.loads(folder['allowed_groups']) or
                    folder['is_visible_to_all'] or
                    user_group == 'root2'
                )

                if not has_permission:
                    conn.close()
                    # 删除已上传的文件
                    paths = get_file_paths(stored_filename, category, subcategory)
                    for path in paths.values():
                        if os.path.exists(path) and not os.path.islink(path):
                            os.remove(path)
                        elif os.path.islink(path):
                            os.unlink(path)
                    return jsonify({'error': '没有权限上传文件到此文件夹'}), 403

            conn.close()

        success, db_error = record_file_upload(stored_filename, original_filename, file_size, user_id, username, category, subcategory, storage_type, folder_id)
        if not success:
            # 如果数据库记录失败，删除已上传的文件
            paths = get_file_paths(stored_filename, category, subcategory)
            for path in paths.values():
                if os.path.exists(path) and not os.path.islink(path):
                    os.remove(path)
                elif os.path.islink(path):
                    os.unlink(path)
            logger.error(f"数据库记录失败: {db_error}")
            return jsonify({'error': f'文件信息记录失败: {db_error}'}), 500

        logger.info(f"文件上传成功: {original_filename} 存储类型: {storage_type} 子分类: {subcategory}")
        return jsonify({
            'success': True,
            'message': '文件上传成功',
            'filename': original_filename,
            'subcategory': subcategory,
            'storage_type': storage_type
        }), 200

    except Exception as e:
        logger.error(f"文件上传错误: {str(e)}", exc_info=True)
        return jsonify({'error': f'文件上传失败: {str(e)}'}), 500

@app.route('/upload_chunk', methods=['POST'])
@login_required
@permission_required('upload')
def upload_chunk():
    """分块上传API"""
    try:
        chunk = request.files.get('chunk')
        chunk_number = request.form.get('chunkNumber')
        total_chunks = request.form.get('totalChunks')
        filename = secure_filename_with_chinese(request.form.get('filename'))  # 修改这里
        if not filename:
            filename = "unnamed_file"
        identifier = request.form.get('identifier')
        category = request.form.get('category', 'competition')
        subcategory = request.form.get('subcategory', 'other')

        if not all([chunk, chunk_number, total_chunks, filename, identifier]):
            return jsonify({'error': '缺少必要参数'}), 400

        if category not in ['everyone', 'competition']:
            category = 'competition'

        if subcategory not in app.config['SUBCATEGORIES']:
            subcategory = detect_file_subcategory(filename)

        # 临时目录
        temp_dir = os.path.join(BASE_UPLOAD_FOLDER, 'temp', identifier)
        os.makedirs(temp_dir, exist_ok=True)

        chunk_path = os.path.join(temp_dir, f"{chunk_number}.part")
        chunk.save(chunk_path)

        logger.info(f"分块 {chunk_number}/{total_chunks} 上传成功: {filename} 分类: {category} 子分类: {subcategory}")
        return jsonify({'success': True, 'message': f'分块 {chunk_number}/{total_chunks} 上传成功'})

    except Exception as e:
        logger.error(f"分块上传错误: {str(e)}")
        return jsonify({'error': '分块上传失败'}), 500

@app.route('/merge_chunks', methods=['POST'])
@login_required
@permission_required('upload')
def merge_chunks():
    """合并分块API"""
    try:
        filename = secure_filename_with_chinese(request.form.get('filename'))
        if not filename:
            filename = "unnamed_file"
        identifier = request.form.get('identifier')
        total_chunks = int(request.form.get('totalChunks'))
        category = request.form.get('category', 'competition')
        subcategory = request.form.get('subcategory', 'other')

        if not all([filename, identifier, total_chunks]):
            return jsonify({'error': '缺少必要参数'}), 400

        if category not in ['everyone', 'competition']:
            category = 'competition'

        if subcategory not in app.config['SUBCATEGORIES']:
            subcategory = detect_file_subcategory(filename)

        # 临时目录
        temp_dir = os.path.join(BASE_UPLOAD_FOLDER, 'temp', identifier)

        # 生成唯一文件名
        stored_filename = get_unique_filename(filename, category, subcategory)

        # 检查是否有缺失的分块
        for i in range(1, total_chunks + 1):
            chunk_path = os.path.join(temp_dir, f"{i}.part")
            if not os.path.exists(chunk_path):
                return jsonify({'error': f'缺少分块: {i}'}), 400

        # 合并分块到临时文件
        temp_file_path = os.path.join(BASE_UPLOAD_FOLDER, 'temp', f"{identifier}_merged")

        # 使用流式写入合并，避免内存溢出
        with open(temp_file_path, 'wb') as output_file:
            for i in range(1, total_chunks + 1):
                chunk_path = os.path.join(temp_dir, f"{i}.part")
                # 使用 shutil.copyfileobj 替代 read()/write()
                with open(chunk_path, 'rb') as chunk_file:
                    shutil.copyfileobj(chunk_file, output_file, length=1024 * 1024 * 10)
                os.remove(chunk_path)

        # 删除临时分块目录
        if os.path.exists(temp_dir):
            os.rmdir(temp_dir)

        # 定义一个简单的包装类，只传递路径，不读取内容
        class FilePathWrapper:
            def __init__(self, path):
                self.file_path = path

            # 不要实现 read() 方法，防止 smart_file_storage 误用

        # 使用智能存储策略保存合并后的文件（传递包装类）
        file_obj = FilePathWrapper(temp_file_path)
        success, storage_type, save_error = smart_file_storage(file_obj, stored_filename, category, subcategory)

        # 删除临时的合并文件
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        if not success:
            return jsonify({'error': f'文件合并失败: {save_error}'}), 500

        # 记录文件信息到数据库
        file_path = get_file_paths(stored_filename, category, subcategory)[
            'external'] if storage_type != 'primary_only' else get_file_paths(stored_filename, category, subcategory)[
            'primary']
        file_size = os.path.getsize(file_path)
        user_id = session.get('user_id')
        username = session.get('username')

        success, db_error = record_file_upload(stored_filename, request.form.get('filename'), file_size, user_id,
                                               username, category, subcategory, storage_type)
        if not success:
            paths = get_file_paths(stored_filename, category, subcategory)
            for path in paths.values():
                if os.path.exists(path) and not os.path.islink(path):
                    os.remove(path)
                elif os.path.islink(path):
                    os.unlink(path)
            return jsonify({'error': f'文件信息记录失败: {db_error}'}), 500

        logger.info(f"文件合并成功: {filename} 保存为 {stored_filename} 存储类型: {storage_type} 子分类: {subcategory}")
        return jsonify({
            'success': True,
            'message': '文件合并成功',
            'filename': filename
        })

    except Exception as e:
        logger.error(f"合并分块错误: {str(e)}")
        return jsonify({'error': '文件合并失败'}), 500

@app.route('/download/<string:stored_filename>')
@login_required
@permission_required('download')
def download_file(stored_filename):
    """统一文件下载API，支持所有大小的文件"""
    try:
        logger.info(f"开始文件下载: {stored_filename}")

        # 从数据库获取文件信息
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT file_category, file_subcategory, original_filename, file_size, storage_type 
                FROM file_info WHERE stored_filename = %s
            """
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

        conn.close()

        if not file_info:
            logger.error(f"文件不存在于数据库: {stored_filename}")
            return jsonify({'error': '文件不存在'}), 404

        category = file_info['file_category']
        subcategory = file_info['file_subcategory']
        original_filename = file_info['original_filename'] or stored_filename
        file_size = file_info['file_size']
        storage_type = file_info['storage_type']

        # 查找文件路径
        file_path = get_any_existing_file_path(stored_filename, category, subcategory)

        if not file_path or not os.path.exists(file_path):
            logger.error(f"文件不存在于磁盘: {stored_filename}")
            return jsonify({'error': '文件不存在'}), 404

        # 处理软链接
        if os.path.islink(file_path):
            real_path = os.path.realpath(file_path)
            if os.path.exists(real_path):
                file_path = real_path
                logger.info(f"解析软链接: {file_path} -> {real_path}")
            else:
                logger.error(f"文件链接已损坏: {file_path}")
                return jsonify({'error': '文件链接已损坏'}), 404

        # 记录下载信息
        user_id = session.get('user_id')
        username = session.get('username')
        record_file_download(stored_filename, user_id, username)

        actual_file_size = os.path.getsize(file_path)
        logger.info(f"文件下载开始: {stored_filename} 大小: {actual_file_size} bytes")

        # 根据文件大小选择不同的下载策略
        if actual_file_size < 100 * 1024 * 1024:  # 小于100MB
            return download_small_file(file_path, original_filename)
        elif actual_file_size > 10 * 1024 * 1024 * 1024:  # 大于10GB
            return download_huge_file_optimized(file_path, original_filename, actual_file_size)
        else:  # 100MB - 10GB
            return download_medium_file(file_path, original_filename, actual_file_size)

    except Exception as e:
        logger.error(f"文件下载错误: {str(e)}", exc_info=True)
        return jsonify({'error': '文件下载失败'}), 500

# 在下载函数中添加更详细的监控
def monitor_download_progress(stored_filename, bytes_sent, total_size):
    """监控下载进度"""
    percent = (bytes_sent / total_size * 100) if total_size > 0 else 0
    logger.info(
        f"📊 下载进度: {stored_filename} - "
        f"{bytes_sent}/{total_size} bytes ({percent:.1f}%)"
    )


def download_small_file(file_path, original_filename):
    """下载小文件（<100MB）- 直接发送"""
    try:
        logger.info(f"使用小文件下载策略: {original_filename}")
        return send_file(
            file_path,
            as_attachment=True,
            download_name=original_filename,
            conditional=True
        )
    except Exception as e:
        logger.error(f"小文件下载失败: {str(e)}")
        return jsonify({'error': '文件下载失败'}), 500

def download_medium_file(file_path, original_filename, file_size):
    """下载中等文件（100MB - 10GB）- 流式传输"""
    def generate():
        try:
            chunk_size = 512 * 1024  # 512KB
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
        except Exception as e:
            logger.error(f"中等文件流式传输错误: {str(e)}")
            raise

    response = Response(
        generate(),
        mimetype='application/octet-stream',
        headers={
            'Content-Disposition': f'attachment; filename="{original_filename}"',
            'Content-Length': str(file_size)
        }
    )
    return response

def download_huge_file_optimized(file_path, original_filename, file_size):
    """下载超大文件（>10GB）- 优化版本"""
    def generate_optimized():
        try:
            # 根据文件大小动态调整块大小
            if file_size > 50 * 1024 * 1024 * 1024:  # >50GB
                chunk_size = 64 * 1024  # 64KB
            elif file_size > 20 * 1024 * 1024 * 1024:  # >20GB
                chunk_size = 128 * 1024  # 128KB
            else:  # 10GB - 20GB
                chunk_size = 256 * 1024  # 256KB

            bytes_sent = 0
            start_time = time.time()
            last_log_time = start_time

            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        logger.info("超大文件传输完成")
                        break

                    bytes_sent += len(chunk)
                    yield chunk

                    # 智能日志记录
                    current_time = time.time()
                    if current_time - last_log_time > 60:  # 每分钟记录一次
                        elapsed = current_time - start_time
                        speed = bytes_sent / elapsed if elapsed > 0 else 0
                        percent = (bytes_sent / file_size * 100) if file_size > 0 else 0

                        logger.info(
                            f"超大文件传输进度: {bytes_sent}/{file_size} bytes "
                            f"({percent:.1f}%) 速度: {speed/1024/1024:.2f} MB/s"
                        )
                        last_log_time = current_time

        except Exception as e:
            logger.error(f"超大文件流式传输错误: {str(e)}")
            raise

    response = Response(
        generate_optimized(),
        mimetype='application/octet-stream',
        headers={
            'Content-Disposition': f'attachment; filename="{original_filename}"',
            'Content-Length': str(file_size),
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'X-Accel-Buffering': 'no'  # 禁用Nginx缓冲
        }
    )
    return response


@app.route('/file_info/<string:stored_filename>')
@login_required
@permission_required('download')
def get_file_info(stored_filename):
    """获取文件详细信息，用于前端进度显示"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT stored_filename, original_filename, file_size, file_category, 
                       file_subcategory, storage_type, upload_time, upload_username
                FROM file_info WHERE stored_filename = %s
            """
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

        conn.close()

        if not file_info:
            return jsonify({'error': '文件不存在'}), 404

        # 获取实际文件路径和大小
        file_path = get_any_existing_file_path(
            stored_filename,
            file_info['file_category'],
            file_info['file_subcategory']
        )

        actual_size = 0
        if file_path and os.path.exists(file_path):
            actual_size = os.path.getsize(file_path)

        # 格式化时间
        if isinstance(file_info['upload_time'], datetime):
            upload_time = file_info['upload_time'].strftime('%Y-%m-%d %H:%M:%S')
        else:
            upload_time = str(file_info['upload_time'])

        return jsonify({
            'success': True,
            'file_info': {
                'stored_filename': file_info['stored_filename'],
                'original_filename': file_info['original_filename'],
                'file_size': file_info['file_size'],
                'actual_size': actual_size,
                'file_category': file_info['file_category'],
                'file_subcategory': file_info['file_subcategory'],
                'storage_type': file_info['storage_type'],
                'upload_time': upload_time,
                'upload_username': file_info['upload_username']
            }
        })

    except Exception as e:
        logger.error(f"获取文件信息错误: {str(e)}")
        return jsonify({'error': '获取文件信息失败'}), 500

@app.route('/delete/<string:stored_filename>', methods=['DELETE'])
@login_required
@permission_required('delete')
def delete_file(stored_filename):
    """文件删除API（处理多种存储类型）"""
    try:
        # 从数据库获取文件信息
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT file_category, file_subcategory, storage_type FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

            if file_info:
                category = file_info['file_category']
                subcategory = file_info['file_subcategory']
                storage_type = file_info['storage_type']
                paths = get_file_paths(stored_filename, category, subcategory)

                # 删除数据库记录
                sql = "DELETE FROM file_info WHERE stored_filename = %s"
                cursor.execute(sql, (stored_filename,))
                conn.commit()

                # 根据存储类型删除文件
                if storage_type == 'dual':
                    # 删除两个位置的实体文件
                    for path in paths.values():
                        if os.path.exists(path) and not os.path.islink(path):
                            os.remove(path)
                elif storage_type == 'external_with_link':
                    # 删除外部存储的实体文件和主存储的软链接
                    if os.path.exists(paths['external']) and not os.path.islink(paths['external']):
                        os.remove(paths['external'])
                    if os.path.exists(paths['primary']):
                        os.remove(paths['primary'])
                elif storage_type == 'external_only':
                    # 只删除外部存储的实体文件
                    if os.path.exists(paths['external']) and not os.path.islink(paths['external']):
                        os.remove(paths['external'])
                elif storage_type == 'primary_only':
                    # 只删除主存储的实体文件
                    if os.path.exists(paths['primary']) and not os.path.islink(paths['primary']):
                        os.remove(paths['primary'])

                logger.info(f"文件删除成功: {stored_filename} 存储类型: {storage_type} 子分类: {subcategory}")
                conn.close()
                return jsonify({'success': True, 'message': '文件删除成功'}), 200
            else:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404
    except Exception as e:
        logger.error(f"文件删除错误: {str(e)}")
        return jsonify({'error': '文件删除失败'}), 500

@app.route('/download_large/<string:stored_filename>')
@login_required
@permission_required('download')
def download_large_file_optimized(stored_filename):
    """优化的大文件下载API - 支持10GB+文件"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT file_category, file_subcategory, storage_type, original_filename, file_size FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

        conn.close()

        if not file_info:
            return jsonify({'error': '文件不存在'}), 404

        category = file_info['file_category']
        subcategory = file_info['file_subcategory']
        original_filename = file_info['original_filename'] or stored_filename

        file_path = get_any_existing_file_path(stored_filename, category, subcategory)

        if not file_path or not os.path.exists(file_path):
            return jsonify({'error': '文件不存在'}), 404

        # 如果是软链接，获取真实路径
        if os.path.islink(file_path):
            real_path = os.path.realpath(file_path)
            if os.path.exists(real_path):
                file_path = real_path
            else:
                return jsonify({'error': '文件链接已损坏'}), 404

        # 记录下载信息
        user_id = session.get('user_id')
        username = session.get('username')
        record_file_download(stored_filename, user_id, username)

        actual_file_size = os.path.getsize(file_path)
        logger.info(f"超大文件下载开始: {stored_filename} 大小: {actual_file_size} bytes")

        def generate_file_stream():
            """生成文件流 - 优化内存使用"""
            try:
                chunk_size = LargeFileConfig.CHUNK_SIZE
                bytes_sent = 0
                start_time = time.time()
                last_log_time = start_time

                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        bytes_sent += len(chunk)
                        yield chunk

                        # 每发送500MB或30秒记录一次日志，避免频繁IO
                        current_time = time.time()
                        if (bytes_sent % (500 * 1024 * 1024) < chunk_size or
                            current_time - last_log_time > 30):
                            elapsed = current_time - start_time
                            speed = bytes_sent / elapsed if elapsed > 0 else 0
                            logger.info(
                                f"超大文件传输进度: {bytes_sent}/{actual_file_size} bytes "
                                f"({bytes_sent/actual_file_size*100:.1f}%) "
                                f"速度: {speed/1024/1024:.2f} MB/s"
                            )
                            last_log_time = current_time

            except GeneratorExit:
                logger.info(f"客户端中断下载: {stored_filename}")
                raise
            except Exception as e:
                logger.error(f"文件流错误: {str(e)}")
                raise

        # 创建响应
        response = Response(
            generate_file_stream(),
            mimetype='application/octet-stream',
            direct_passthrough=True
        )

        # 设置响应头
        headers = {
            'Content-Disposition': f'attachment; filename="{original_filename}"',
            'Content-Length': str(actual_file_size),
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'no-cache, no-store, must-revalidate, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0',
            'X-Accel-Buffering': 'no',
            'X-Content-Type-Options': 'nosniff',
            'X-File-Size': str(actual_file_size),
            'X-File-Name': original_filename,
        }

        response.headers.update(headers)
        logger.info(f"超大文件下载响应已发送: {original_filename}")
        return response

    except Exception as e:
        logger.error(f"超大文件下载错误: {str(e)}", exc_info=True)
        return jsonify({'error': '文件下载失败'}), 500

@app.route('/download_status/<string:stored_filename>')
@login_required
def get_download_status(stored_filename):
    """获取文件下载状态（用于前端进度监控）"""
    try:
        # 这里可以扩展为实时监控下载状态
        # 目前返回基本文件信息供前端计算进度
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT original_filename, file_size FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

        conn.close()

        if not file_info:
            return jsonify({'error': '文件不存在'}), 404

        return jsonify({
            'success': True,
            'filename': file_info['original_filename'],
            'total_size': file_info['file_size'],
            'downloadable': True
        })

    except Exception as e:
        logger.error(f"获取下载状态错误: {str(e)}")
        return jsonify({'error': '获取下载状态失败'}), 500


# ========== 文件夹管理路由 ==========
@app.route('/folders', methods=['GET'])
@login_required
def get_folders():
    """获取用户有权限访问的文件夹列表"""
    try:
        user_group = session.get('user_group', 'other')
        user_id = session.get('user_id')

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 根据用户组获取不同的文件夹列表
            if user_group == 'root2':
                # root2可以看到所有文件夹
                sql = """
                    SELECT f.*, u.username as creator_name 
                    FROM folders f 
                    LEFT JOIN users u ON f.created_by = u.id 
                    ORDER BY f.created_at DESC
                """
                cursor.execute(sql)
            elif user_group == 'root':
                # root只能看到自己创建的文件夹和公开文件夹，不能看到root2创建的
                sql = """
                    SELECT f.*, u.username as creator_name 
                    FROM folders f 
                    LEFT JOIN users u ON f.created_by = u.id 
                    WHERE (f.created_by = %s OR f.is_visible_to_all = TRUE)
                    AND f.creator_group != 'root2'
                    ORDER BY f.created_at DESC
                """
                cursor.execute(sql, (user_id,))
            else:
                # 其他用户只能看到公开文件夹且创建者为competition或other
                sql = """
                    SELECT f.*, u.username as creator_name 
                    FROM folders f 
                    LEFT JOIN users u ON f.created_by = u.id 
                    WHERE f.is_visible_to_all = TRUE
                    AND (f.creator_group = 'competition' OR f.creator_group = 'other')
                    ORDER BY f.created_at DESC
                """
                cursor.execute(sql)

            folders = cursor.fetchall()

            # 格式化时间
            for folder in folders:
                if isinstance(folder['created_at'], datetime):
                    folder['created_at'] = folder['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    folder['created_at'] = str(folder['created_at'])

        conn.close()
        return jsonify({'folders': folders})
    except Exception as e:
        logger.error(f"获取文件夹列表错误: {str(e)}")
        return jsonify({'error': '获取文件夹列表失败'}), 500

@app.route('/folders', methods=['POST'])
@admin_required
def create_folder():
    """创建文件夹（仅root2和root可以创建）"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        folder_name = data.get('name')
        allowed_groups = data.get('allowed_groups', [])
        is_visible_to_all = data.get('is_visible_to_all', False)

        if not folder_name:
            return jsonify({'error': '文件夹名称不能为空'}), 400

        # 安全处理文件夹名称
        safe_folder_name = secure_filename_with_chinese(folder_name)
        if not safe_folder_name:
            return jsonify({'error': '文件夹名称无效'}), 400

        user_id = session.get('user_id')
        username = session.get('username')
        user_group = session.get('user_group')

        # 根据用户组生成不同的文件夹路径
        if user_group == 'root2':
            # 超级管理员文件夹
            folder_path = os.path.join(BASE_UPLOAD_FOLDER, 'admin_folders', 'root2', safe_folder_name)
        else:
            # 管理员文件夹
            folder_path = os.path.join(BASE_UPLOAD_FOLDER, 'admin_folders', 'root', safe_folder_name)

        # 检查文件夹是否已存在
        if os.path.exists(folder_path):
            return jsonify({'error': '文件夹已存在'}), 400

        # 创建物理文件夹
        os.makedirs(folder_path, exist_ok=True)

        # 在外部存储也创建对应文件夹
        external_folder_path = os.path.join(EXTERNAL_UPLOAD_FOLDER, 'admin_folders', 'root2' if user_group == 'root2' else 'root', safe_folder_name)
        os.makedirs(external_folder_path, exist_ok=True)

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查数据库中的文件夹名称是否唯一
            sql = "SELECT id FROM folders WHERE path = %s"
            cursor.execute(sql, (folder_path,))
            if cursor.fetchone():
                conn.close()
                # 清理已创建的物理文件夹
                shutil.rmtree(folder_path, ignore_errors=True)
                shutil.rmtree(external_folder_path, ignore_errors=True)
                return jsonify({'error': '文件夹已存在'}), 400

            # 插入文件夹记录
            sql = """
                INSERT INTO folders (name, path, created_by, created_username, allowed_groups, is_visible_to_all, creator_group)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (
                folder_name,
                folder_path,
                user_id,
                username,
                json.dumps(allowed_groups),
                is_visible_to_all,
                user_group  # 记录创建者用户组
            ))
            conn.commit()

        conn.close()
        logger.info(f"文件夹创建成功: {folder_name} 创建者: {username} 用户组: {user_group}")
        return jsonify({'success': True, 'message': '文件夹创建成功'})
    except Exception as e:
        logger.error(f"创建文件夹错误: {str(e)}")
        return jsonify({'error': '文件夹创建失败'}), 500

@app.route('/folders/<int:folder_id>', methods=['PUT'])
@admin_required
def update_folder(folder_id):
    """更新文件夹权限（仅root2可以修改权限）"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        allowed_groups = data.get('allowed_groups', [])
        is_visible_to_all = data.get('is_visible_to_all', False)
        user_group = session.get('user_group')

        # 只有root2可以修改文件夹权限
        if user_group != 'root2':
            return jsonify({'error': '只有超级管理员可以修改文件夹权限'}), 403

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查文件夹是否存在
            sql = "SELECT created_by, created_username, creator_group FROM folders WHERE id = %s"
            cursor.execute(sql, (folder_id,))
            folder = cursor.fetchone()

            if not folder:
                conn.close()
                return jsonify({'error': '文件夹不存在'}), 404

            # 更新文件夹权限
            sql = "UPDATE folders SET allowed_groups = %s, is_visible_to_all = %s WHERE id = %s"
            cursor.execute(sql, (
                json.dumps(allowed_groups),
                is_visible_to_all,
                folder_id
            ))
            conn.commit()

        conn.close()
        logger.info(f"文件夹权限更新成功: 文件夹ID {folder_id}")
        return jsonify({'success': True, 'message': '文件夹权限更新成功'})
    except Exception as e:
        logger.error(f"更新文件夹权限错误: {str(e)}")
        return jsonify({'error': '文件夹权限更新失败'}), 500

@app.route('/folders/<int:folder_id>', methods=['DELETE'])
@admin_required
def delete_folder(folder_id):
    """删除文件夹（仅创建者或root2可以删除）"""
    try:
        user_id = session.get('user_id')
        user_group = session.get('user_group')

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查文件夹是否存在
            sql = "SELECT path, created_by, creator_group FROM folders WHERE id = %s"
            cursor.execute(sql, (folder_id,))
            folder = cursor.fetchone()

            if not folder:
                conn.close()
                return jsonify({'error': '文件夹不存在'}), 404

            # 检查权限：只有创建者或root2可以删除
            # root2可以删除任何文件夹，root只能删除自己创建的文件夹
            can_delete = False
            if user_group == 'root2':
                can_delete = True
            elif user_group == 'root' and folder['created_by'] == user_id and folder['creator_group'] == 'root':
                can_delete = True

            if not can_delete:
                conn.close()
                return jsonify({'error': '没有权限删除此文件夹'}), 403

            # 检查文件夹中是否有文件
            sql = "SELECT COUNT(*) as file_count FROM file_info WHERE folder_id = %s"
            cursor.execute(sql, (folder_id,))
            file_count = cursor.fetchone()['file_count']

            if file_count > 0:
                conn.close()
                return jsonify({'error': '文件夹不为空，无法删除'}), 400

            # 删除物理文件夹
            folder_path = folder['path']
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path, ignore_errors=True)

            # 删除外部存储的对应文件夹
            external_base = EXTERNAL_UPLOAD_FOLDER
            relative_path = os.path.relpath(folder_path, BASE_UPLOAD_FOLDER)
            external_folder_path = os.path.join(external_base, relative_path)
            if os.path.exists(external_folder_path):
                shutil.rmtree(external_folder_path, ignore_errors=True)

            # 删除数据库记录
            sql = "DELETE FROM folders WHERE id = %s"
            cursor.execute(sql, (folder_id,))
            conn.commit()

        conn.close()
        logger.info(f"文件夹删除成功: 文件夹ID {folder_id}")
        return jsonify({'success': True, 'message': '文件夹删除成功'})
    except Exception as e:
        logger.error(f"删除文件夹错误: {str(e)}")
        return jsonify({'error': '文件夹删除失败'}), 500

@app.route('/folder_files/<int:folder_id>')
@login_required
@permission_required('download')
def get_folder_files(folder_id):
    """获取文件夹中的文件列表"""
    try:
        user_group = session.get('user_group', 'other')
        user_id = session.get('user_id')

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 首先检查用户是否有权限访问此文件夹
            if user_group == 'root2':
                # root2可以访问所有文件夹
                sql = "SELECT f.* FROM folders f WHERE f.id = %s"
                cursor.execute(sql, (folder_id,))
            elif user_group == 'root':
                # root只能访问自己创建的文件夹或公开文件夹，不能访问root2创建的
                sql = """
                    SELECT f.* FROM folders f 
                    WHERE f.id = %s AND (
                        f.created_by = %s OR 
                        f.is_visible_to_all = TRUE
                    ) AND f.creator_group != 'root2'
                """
                cursor.execute(sql, (folder_id, user_id))
            else:
                # 其他用户只能访问公开文件夹且创建者为competition或other
                sql = """
                    SELECT f.* FROM folders f 
                    WHERE f.id = %s AND f.is_visible_to_all = TRUE
                    AND (f.creator_group = 'competition' OR f.creator_group = 'other')
                """
                cursor.execute(sql, (folder_id,))

            folder = cursor.fetchone()

            if not folder:
                conn.close()
                return jsonify({'error': '没有权限访问此文件夹或文件夹不存在'}), 403

            # 获取文件夹中的文件
            sql = """
                SELECT 
                    stored_filename, 
                    original_filename as filename, 
                    file_size, 
                    upload_time, 
                    upload_username,
                    download_count,
                    file_category,
                    file_subcategory,
                    storage_type
                FROM file_info 
                WHERE folder_id = %s
                ORDER BY upload_time DESC
            """
            cursor.execute(sql, (folder_id,))
            files = cursor.fetchall()

            # 格式化时间
            for file in files:
                if isinstance(file['upload_time'], datetime):
                    file['upload_time'] = file['upload_time'].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    file['upload_time'] = str(file['upload_time'])

        conn.close()
        return jsonify({'files': files, 'folder': folder})
    except Exception as e:
        logger.error(f"获取文件夹文件列表错误: {str(e)}")
        return jsonify({'error': '获取文件夹文件列表失败'}), 500

# ========== 新增功能：文件重命名和子分类修改 ==========
@app.route('/rename_file/<string:stored_filename>', methods=['PUT'])
@login_required
@file_management_required
def rename_file(stored_filename):
    """文件重命名API（支持中文字符）"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        new_filename = data.get('new_filename')

        if not new_filename:
            return jsonify({'error': '新文件名不能为空'}), 400

        # 安全处理文件名，但保留中文字符
        # 使用自定义的安全文件名函数，避免过滤中文字符
        safe_new_filename = secure_filename_with_chinese(new_filename)

        if not safe_new_filename:
            return jsonify({'error': '文件名无效'}), 400

        # 从数据库获取文件信息
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT file_category, file_subcategory, storage_type FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

            if not file_info:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404

            category = file_info['file_category']
            subcategory = file_info['file_subcategory']
            storage_type = file_info['storage_type']

            # 检查新文件名是否已存在
            sql = "SELECT id FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (safe_new_filename,))
            if cursor.fetchone():
                conn.close()
                return jsonify({'error': '文件名已存在'}), 400

            # 获取文件路径
            old_paths = get_file_paths(stored_filename, category, subcategory)
            new_paths = get_file_paths(safe_new_filename, category, subcategory)

            # 移动文件到新文件名
            moved = False
            if storage_type == 'dual':
                # 移动两个位置的实体文件
                for location in ['primary', 'external']:
                    old_path = old_paths[location]
                    new_path = new_paths[location]

                    if os.path.exists(old_path):
                        shutil.move(old_path, new_path)
                        moved = True
            elif storage_type == 'external_with_link':
                # 移动外部存储的实体文件，重新创建软链接
                if os.path.exists(old_paths['external']):
                    shutil.move(old_paths['external'], new_paths['external'])
                    # 重新创建软链接
                    if os.path.exists(new_paths['primary']):
                        os.remove(new_paths['primary'])
                    os.symlink(new_paths['external'], new_paths['primary'])
                    moved = True
            elif storage_type == 'external_only':
                # 移动外部存储的实体文件
                if os.path.exists(old_paths['external']):
                    shutil.move(old_paths['external'], new_paths['external'])
                    moved = True
            elif storage_type == 'primary_only':
                # 移动主存储的实体文件
                if os.path.exists(old_paths['primary']):
                    shutil.move(old_paths['primary'], new_paths['primary'])
                    moved = True

            if moved:
                # 更新数据库记录
                sql = "UPDATE file_info SET stored_filename = %s, original_filename = %s WHERE stored_filename = %s"
                cursor.execute(sql, (safe_new_filename, new_filename, stored_filename))
                conn.commit()

                logger.info(f"文件重命名成功: {stored_filename} 改为 {safe_new_filename} (显示名: {new_filename})")
                conn.close()
                return jsonify({'success': True, 'message': '文件重命名成功'})
            else:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404

    except Exception as e:
        logger.error(f"文件重命名错误: {str(e)}")
        return jsonify({'error': '文件重命名失败'}), 500

@app.route('/update_subcategory/<string:stored_filename>', methods=['PUT'])
@login_required
@file_management_required
def update_file_subcategory(stored_filename):
    """更新文件子分类API"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        new_subcategory = data.get('subcategory')

        if new_subcategory not in app.config['SUBCATEGORIES']:
            return jsonify({'error': '无效的文件子分类'}), 400

        # 从数据库获取当前文件信息
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT file_category, file_subcategory, storage_type FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

            if not file_info:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404

            old_category = file_info['file_category']
            old_subcategory = file_info['file_subcategory']
            storage_type = file_info['storage_type']

            if old_subcategory == new_subcategory:
                conn.close()
                return jsonify({'success': True, 'message': '文件子分类未改变'})

            # 获取文件路径
            old_paths = get_file_paths(stored_filename, old_category, old_subcategory)
            new_paths = get_file_paths(stored_filename, old_category, new_subcategory)

            # 移动文件到新目录
            moved = False
            if storage_type == 'dual':
                # 移动两个位置的实体文件
                for location in ['primary', 'external']:
                    old_path = old_paths[location]
                    new_path = new_paths[location]

                    if os.path.exists(old_path):
                        shutil.move(old_path, new_path)
                        moved = True
            elif storage_type == 'external_with_link':
                # 移动外部存储的实体文件，重新创建软链接
                if os.path.exists(old_paths['external']):
                    shutil.move(old_paths['external'], new_paths['external'])
                    # 重新创建软链接
                    if os.path.exists(new_paths['primary']):
                        os.remove(new_paths['primary'])
                    os.symlink(new_paths['external'], new_paths['primary'])
                    moved = True
            elif storage_type == 'external_only':
                # 移动外部存储的实体文件
                if os.path.exists(old_paths['external']):
                    shutil.move(old_paths['external'], new_paths['external'])
                    moved = True
            elif storage_type == 'primary_only':
                # 移动主存储的实体文件
                if os.path.exists(old_paths['primary']):
                    shutil.move(old_paths['primary'], new_paths['primary'])
                    moved = True

            if moved:
                # 更新数据库记录
                sql = "UPDATE file_info SET file_subcategory = %s WHERE stored_filename = %s"
                cursor.execute(sql, (new_subcategory, stored_filename))
                conn.commit()

                logger.info(f"文件子分类更新成功: {stored_filename} 从 {old_subcategory} 改为 {new_subcategory} 分类: {old_category}")
                conn.close()
                return jsonify({'success': True, 'message': '文件子分类更新成功'})
            else:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404

    except Exception as e:
        logger.error(f"更新文件子分类错误: {str(e)}")
        return jsonify({'error': '文件子分类更新失败'}), 500

@app.route('/update_category/<string:stored_filename>', methods=['PUT'])
@login_required
@permission_required('delete')
def update_file_category(stored_filename):
    """更新文件分类API"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': '请求必须是JSON格式'}), 400

        data = request.get_json()
        new_category = data.get('category')

        if new_category not in ['everyone', 'competition']:
            return jsonify({'error': '无效的文件分类'}), 400

        # 从数据库获取当前文件信息
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT file_category, file_subcategory, storage_type FROM file_info WHERE stored_filename = %s"
            cursor.execute(sql, (stored_filename,))
            file_info = cursor.fetchone()

            if not file_info:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404

            old_category = file_info['file_category']
            subcategory = file_info['file_subcategory']
            storage_type = file_info['storage_type']

            if old_category == new_category:
                conn.close()
                return jsonify({'success': True, 'message': '文件分类未改变'})

            # 获取文件路径
            old_paths = get_file_paths(stored_filename, old_category, subcategory)
            new_paths = get_file_paths(stored_filename, new_category, subcategory)

            # 移动文件到新目录
            moved = False
            if storage_type == 'dual':
                # 移动两个位置的实体文件
                for location in ['primary', 'external']:
                    old_path = old_paths[location]
                    new_path = new_paths[location]

                    if os.path.exists(old_path):
                        shutil.move(old_path, new_path)
                        moved = True
            elif storage_type == 'external_with_link':
                # 移动外部存储的实体文件，重新创建软链接
                if os.path.exists(old_paths['external']):
                    shutil.move(old_paths['external'], new_paths['external'])
                    # 重新创建软链接
                    if os.path.exists(new_paths['primary']):
                        os.remove(new_paths['primary'])
                    os.symlink(new_paths['external'], new_paths['primary'])
                    moved = True
            elif storage_type == 'external_only':
                # 移动外部存储的实体文件
                if os.path.exists(old_paths['external']):
                    shutil.move(old_paths['external'], new_paths['external'])
                    moved = True
            elif storage_type == 'primary_only':
                # 移动主存储的实体文件
                if os.path.exists(old_paths['primary']):
                    shutil.move(old_paths['primary'], new_paths['primary'])
                    moved = True

            if moved:
                # 更新数据库记录
                sql = "UPDATE file_info SET file_category = %s WHERE stored_filename = %s"
                cursor.execute(sql, (new_category, stored_filename))
                conn.commit()

                logger.info(f"文件分类更新成功: {stored_filename} 从 {old_category} 改为 {new_category} 子分类: {subcategory}")
                conn.close()
                return jsonify({'success': True, 'message': '文件分类更新成功'})
            else:
                conn.close()
                return jsonify({'error': '文件不存在'}), 404

    except Exception as e:
        logger.error(f"更新文件分类错误: {str(e)}")
        return jsonify({'error': '文件分类更新失败'}), 500

# ========== 错误处理 ==========
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': '资源未找到'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': '服务器内部错误'}), 500

@app.errorhandler(413)
def too_large(error):
    return jsonify({'error': '文件太大'}), 413

# ========== 主程序 ==========
if __name__ == '__main__':
    logger.info("启动Flask文件上传服务器（智能存储版本+权限管理）")
    logger.info("启动Flask文件上传服务器（优化大文件下载版本）")
    logger.info(f"主上传目录: {BASE_UPLOAD_FOLDER}")
    logger.info(f"外部上传目录: {EXTERNAL_UPLOAD_FOLDER}")
    logger.info(f"双存储阈值: {app.config['DUAL_STORAGE_THRESHOLD'] / (1024*1024)} MB")
    logger.info(f"最小剩余空间: {app.config['MIN_FREE_SPACE'] / (1024*1024*1024)} GB")
    logger.info(f"用户组权限配置: {app.config['USER_GROUPS']}")
    logger.info("启动优化版文件服务器（支持10GB+大文件下载）")

    # 检查目录权限
    for folder_name, folders in [('EVERYONE_FOLDERS', app.config['EVERYONE_FOLDERS']),
                                ('COMPETITION_FOLDERS', app.config['COMPETITION_FOLDERS'])]:
        for location, folder_path in folders.items():
            if os.path.exists(folder_path):
                logger.info(f"目录 {folder_path} 存在，权限: {oct(os.stat(folder_path).st_mode)[-3:]}")
            else:
                logger.warning(f"目录 {folder_path} 不存在")

    # 测试数据库连接
    test_database_connection()

    # 初始化数据库表结构
    try:
        init_database()
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}")

    # 迁移现有文件到数据库
    migrate_existing_files()

    # 优化服务器配置
    # 在 app.config 部分添加
    app.config.update(
        MAX_CONTENT_LENGTH=100 * 1024 * 1024 * 1024,  # 100GB
        SEND_FILE_MAX_AGE_DEFAULT=0,
        TEMPLATES_AUTO_RELOAD=True,
        # 添加以下优化配置
        PREFERRED_URL_SCHEME='https',  # 如果使用HTTPS
        SONIFY_PRETTYPRINT_REGULAR=False,
        JSON_SORT_KEYS=False
    )


    port = find_available_port()
    if port is None:
        logger.error("找不到可用端口，服务器启动失败")
        exit(1)

    logger.info(f"服务器地址: http://localhost:{port}")
    if port != 5000:
        logger.warning(f"端口 5000 被占用，使用端口 {port}")

    try:
        # 尝试导入 Waitress
        from waitress import serve
        import logging as waitress_logging

        # 配置 Waitress 日志
        waitress_logger = waitress_logging.getLogger('waitress')
        waitress_logger.setLevel(waitress_logging.INFO)

        # 获取可用端口
        port = find_available_port()
        if port is None:
            logger.error("找不到可用端口")
            exit(1)

        logger.info(f"使用 Waitress 在生产模式启动服务器，端口: {port}")

        # 生产服务器配置
        serve(
            app,
            host='0.0.0.0',
            port=port,
            threads=8,
            connection_limit=1000,
            asyncore_use_poll=True,
            send_bytes=LargeFileConfig.CHUNK_SIZE,
            channel_timeout=LargeFileConfig.DOWNLOAD_TIMEOUT,
            cleanup_interval=300
        )

    except ImportError:
        logger.warning("Waitress 未安装，使用开发服务器")
        # 回退到开发服务器
        port = find_available_port()
        if port:
            app.run(
                debug=False,
                host='0.0.0.0',
                port=port,
                threaded=True,
                use_reloader=False,
                passthrough_errors=True
            )
        else:
            logger.error("找不到可用端口")