-- 创建数据库
CREATE DATABASE IF NOT EXISTS file_manager;
USE file_manager;

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    email VARCHAR(100) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 文件分类表（可选，用于更复杂的分类管理）
CREATE TABLE IF NOT EXISTS file_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 文件表（已添加file_category字段）
CREATE TABLE IF NOT EXISTS files (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(512) NOT NULL,
    file_size INT NOT NULL,
    user_id INT NOT NULL,
    file_category VARCHAR(100) DEFAULT '默认分类',
    mime_type VARCHAR(100),
    upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    -- 如果使用独立的分类表，取消下面的注释
    -- category_id INT,
    -- FOREIGN KEY (category_id) REFERENCES file_categories(id)
);

-- 创建索引
CREATE INDEX idx_files_user_id ON files(user_id);
CREATE INDEX idx_files_category ON files(file_category);
CREATE INDEX idx_users_username ON users(username);

-- 插入默认分类数据（如果使用独立分类表）
-- INSERT INTO file_categories (category_name, description) VALUES 
-- ('默认分类', '未分类的文件'),
-- ('比赛文件', '比赛相关的文件'),
-- ('文档', '各种文档文件'),
-- ('图片', '图像文件'),
-- ('视频', '视频文件'),
-- ('音频', '音频文件');

-- 插入示例用户（可选）
-- INSERT INTO users (username, password, email) VALUES 
-- ('admin', '加密的密码', 'admin@example.com');

-- 授予权限（根据实际情况调整）
-- GRANT SELECT, INSERT, UPDATE, DELETE ON file_manager.* TO 'your_username'@'localhost';