// 全局变量
let currentEditingUserId = null;
let currentUserPermissions = [];
let currentRenamingFile = null;
let currentChangingSubcategoryFile = null;
let currentEditingFolderId = null;
let currentViewingFolderId = null;
let currentUserProfile = null;
let currentDownloadController = null; // 用于取消下载

// 验证码自动重试机制
let captchaRetryCount = 0;
const MAX_CAPTCHA_RETRIES = 3;

function fetchCaptchaWithRetry() {
	if (captchaRetryCount >= MAX_CAPTCHA_RETRIES) {
		console.error("验证码获取重试次数超过限制");
		const captchaElement = document.getElementById('captchaText');
		captchaElement.textContent = '点击刷新';
		captchaElement.style.color = '#e74c3c';
		captchaElement.style.cursor = 'pointer';
		captchaElement.onclick = function() {
			captchaRetryCount = 0;
			fetchCaptcha();
		};
		return;
	}

	captchaRetryCount++;
	fetchCaptcha();
}

// 页面加载时检查登录状态
document.addEventListener('DOMContentLoaded', function() {
	console.log("页面加载完成，初始化验证码...");
	checkLoginStatus();

	// 延迟加载验证码，确保页面完全渲染
	setTimeout(() => {
		fetchCaptcha();
	}, 500);
});

// 检查登录状态
function checkLoginStatus() {
	fetch('/check_login')
		.then(response => response.json())
		.then(data => {
			if (data.logged_in) {
				// 显示当前用户名
				document.getElementById('currentUser').textContent = `当前用户: ${data.username}`;
				// 更新用户组徽章
				updateUserGroupBadge(data.user_group);
				// 存储用户组信息到sessionStorage
				sessionStorage.setItem('userGroup', data.user_group);
				// 存储用户ID（如果后端返回）
				if (data.user_id) {
					sessionStorage.setItem('user_id', data.user_id);
				}
				// 加载用户权限信息
				loadUserPermissions();
				// 加载用户个人信息
				loadUserProfile();
				showAppSection();
			} else {
				showLoginSection();
			}
		})
		.catch(error => {
			console.error('检查登录状态失败:', error);
			showLoginSection();
		});
}

// 更新用户显示（优先显示中文别名）
function updateUserDisplay(username) {
	// 这里我们会在loadUserProfile中更新显示，因为需要中文别名
	document.getElementById('currentUser').textContent = `当前用户: ${username}`;
}

// 加载用户个人信息
function loadUserProfile() {
	return fetch('/user/profile')
		.then(response => response.json())
		.then(data => {
			if (data.username) {
				currentUserProfile = data;
				// 存储用户ID到sessionStorage
				sessionStorage.setItem('user_id', data.id || '');
				// 优先显示中文别名，如果没有则显示用户名
				const displayName = data.chinese_alias || data.username;
				document.getElementById('currentUser').textContent = `当前用户: ${displayName}`;
			}
			return data;
		})
		.catch(error => {
			console.error('获取用户信息失败:', error);
			return null;
		});
}

// 打开个人设置模态框
function openPersonalSettingsModal() {
	if (!currentUserProfile) {
		loadUserProfile().then(() => {
			showPersonalSettingsModal();
		});
	} else {
		showPersonalSettingsModal();
	}
}

// 显示个人设置模态框
function showPersonalSettingsModal() {
	// 填充表单数据
	document.getElementById('settingsUsername').value = currentUserProfile.username;
	document.getElementById('settingsChineseAlias').value = currentUserProfile.chinese_alias || '';
	document.getElementById('settingsEmail').value = currentUserProfile.email || '';
	document.getElementById('settingsPassword').value = '';
	document.getElementById('settingsConfirmPassword').value = '';

	// 显示当前权限
	const permissionsElement = document.getElementById('currentPermissions');
	const groupNames = {
		'root2': '超级管理员',
		'root': '管理员',
		'competition': '比赛用户',
		'other': '普通用户'
	};

	const permissionDescriptions = {
		'upload': '上传文件',
		'download': '下载文件',
		'delete': '删除文件',
		'user_management': '用户管理',
		'rename_files': '重命名文件',
		'change_subcategory': '更改文件分类'
	};

	let permissionsHtml =
		`<strong>用户组: </strong><span class="user-group-tag group-${currentUserProfile.user_group}">${groupNames[currentUserProfile.user_group]}</span><br><br>`;
	permissionsHtml += `<strong>权限列表:</strong><br>`;

	currentUserPermissions.forEach(permission => {
		permissionsHtml +=
			`<span class="permission-tag" style="background: #e3f2fd; color: #1976d2; margin: 2px; padding: 2px 6px; border-radius: 10px; font-size: 12px; display: inline-block;">${permissionDescriptions[permission] || permission}</span> `;
	});

	permissionsElement.innerHTML = permissionsHtml;

	document.getElementById('personalSettingsModal').style.display = 'block';
}

// 关闭个人设置模态框
function closePersonalSettingsModal() {
	document.getElementById('personalSettingsModal').style.display = 'none';
}

// 保存个人设置
function savePersonalSettings() {
	const username = document.getElementById('settingsUsername').value.trim();
	const chineseAlias = document.getElementById('settingsChineseAlias').value.trim();
	const password = document.getElementById('settingsPassword').value;
	const confirmPassword = document.getElementById('settingsConfirmPassword').value;

	if (!username) {
		showMessage('用户名不能为空', 'error');
		return;
	}

	if (username.length < 2) {
		showMessage('用户名至少需要2个字符', 'error');
		return;
	}

	if (password) {
		if (password.length < 6) {
			showMessage('密码至少需要6个字符', 'error');
			return;
		}

		if (password !== confirmPassword) {
			showMessage('两次输入的密码不一致', 'error');
			return;
		}
	}

	const updateData = {
		username: username,
		chinese_alias: chineseAlias
	};

	if (password) {
		updateData.password = password;
	}

	// 显示加载状态
	const saveBtn = document.querySelector('#personalSettingsForm button[type="submit"]');
	const originalText = saveBtn.textContent;
	saveBtn.textContent = '保存中...';
	saveBtn.disabled = true;

	fetch('/user/profile', {
			method: 'PUT',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify(updateData)
		})
		.then(response => {
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.error || '更新失败');
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				showMessage('个人信息更新成功', 'success');
				closePersonalSettingsModal();

				// 立即更新当前用户显示
				updateCurrentUserDisplay(username, chineseAlias);

				// 重新加载用户信息
				loadUserProfile();
				// 更新显示
				const currentUserGroup = sessionStorage.getItem('userGroup');
				if (currentUserGroup === 'root2' || currentUserGroup === 'root') {
					loadUserList();
				}
			} else {
				showMessage('个人信息更新失败: ' + (data.error || '未知错误'), 'error');
			}
		})
		.catch(error => {
			showMessage('个人信息更新出错: ' + error.message, 'error');
		})
		.finally(() => {
			// 恢复按钮状态
			saveBtn.textContent = originalText;
			saveBtn.disabled = false;
		});
}

// 新增函数：立即更新当前用户显示
function updateCurrentUserDisplay(username, chineseAlias) {
	const displayName = chineseAlias || username;
	document.getElementById('currentUser').textContent = `当前用户: ${displayName}`;

	// 同时更新当前用户配置文件
	if (currentUserProfile) {
		currentUserProfile.username = username;
		currentUserProfile.chinese_alias = chineseAlias;
	}
}

// 加载用户权限信息
function loadUserPermissions() {
	fetch('/user/permissions')
		.then(response => response.json())
		.then(data => {
			if (data.user_group) {
				currentUserPermissions = data.permissions || [];
				// 确保用户组信息正确存储
				sessionStorage.setItem('userGroup', data.user_group);
				updateUIByPermissions(data);
			}
		})
		.catch(error => {
			console.error('获取用户权限失败:', error);
		});
}

// 根据权限更新UI
function updateUIByPermissions(permissionData) {
	const userGroup = permissionData.user_group;
	const permissions = permissionData.permissions;
	const canManageUsers = permissionData.can_manage_users;

	// 更新用户组徽章
	updateUserGroupBadge(userGroup);

	// 显示/隐藏用户管理界面 - root2和root都可见
	if (userGroup === 'root2' || userGroup === 'root') {
		document.getElementById('userManagementSection').style.display = 'block';
		loadUserList(); // 加载用户列表
	} else {
		document.getElementById('userManagementSection').style.display = 'none';
	}

	// 显示/隐藏文件夹管理界面 - root2和root都可见
	if (userGroup === 'root2' || userGroup === 'root') {
		document.getElementById('folderManagementSection').style.display = 'block';
		loadFolders(); // 加载文件夹列表
		loadFolderOptions(); // 加载文件夹选择选项
	} else {
		document.getElementById('folderManagementSection').style.display = 'none';
		document.getElementById('folderSelectGroup').style.display = 'none';
	}

	// 显示/隐藏上传界面
	if (permissions.includes('upload')) {
		document.getElementById('uploadSection').style.display = 'block';
	} else {
		document.getElementById('uploadSection').style.display = 'none';
	}

	// 显示/隐藏文件列表（如果没有下载权限）
	if (permissions.includes('download')) {
		document.getElementById('fileListSection').style.display = 'block';
	} else {
		document.getElementById('fileListSection').style.display = 'none';
	}
}

// 更新用户组徽章
function updateUserGroupBadge(userGroup) {
	const badge = document.getElementById('userGroupBadge');
	const groupNames = {
		'root2': '超级管理员',
		'root': '管理员',
		'competition': '比赛用户',
		'other': '普通用户'
	};

	badge.textContent = groupNames[userGroup] || userGroup;
	badge.className = `user-group-tag group-${userGroup}`;
}

// 显示登录表单
function showLoginSection() {
	document.getElementById('loginSection').classList.remove('hidden');
	document.getElementById('registerSection').classList.add('hidden');
	document.getElementById('appSection').classList.add('hidden');
}

// 显示注册表单
function showRegisterSection() {
	document.getElementById('loginSection').classList.add('hidden');
	document.getElementById('registerSection').classList.remove('hidden');
	document.getElementById('appSection').classList.add('hidden');
}

// 显示应用界面
function showAppSection() {
	document.getElementById('loginSection').classList.add('hidden');
	document.getElementById('registerSection').classList.add('hidden');
	document.getElementById('appSection').classList.remove('hidden');
	fetchFiles(); // 加载文件列表
}

// 获取验证码
function fetchCaptcha() {
	console.log("开始获取验证码...");

	// 显示加载状态
	const captchaElement = document.getElementById('captchaText');
	captchaElement.textContent = '加载中...';
	captchaElement.style.color = '#666';

	fetch('/get_captcha')
		.then(response => {
			console.log("验证码响应状态:", response.status);
			if (!response.ok) {
				// 即使服务器返回错误，也尝试解析响应
				return response.json().then(data => {
					// 如果服务器提供了验证码，使用它
					if (data.captcha) {
						return data;
					}
					throw new Error(`HTTP error! status: ${response.status}`);
				}).catch(() => {
					throw new Error(`HTTP error! status: ${response.status}`);
				});
			}
			return response.json();
		})
		.then(data => {
			console.log("验证码响应数据:", data);
			if (data.captcha) {
				captchaElement.textContent = data.captcha;
				captchaElement.style.color = '#000';
				captchaElement.style.fontWeight = 'bold';
				console.log("验证码显示成功:", data.captcha);
			} else if (data.error) {
				console.error('获取验证码失败:', data.error);
				// 使用默认验证码
				captchaElement.textContent = '1234';
				captchaElement.style.color = '#000';
			} else {
				console.error('验证码响应格式错误:', data);
				// 使用默认验证码
				captchaElement.textContent = 'ABCD';
				captchaElement.style.color = '#000';
			}
		})
		.catch(error => {
			console.error('获取验证码出错:', error);
			// 使用默认验证码
			captchaElement.textContent = '1234';
			captchaElement.style.color = '#000';
		});
}

// 刷新验证码按钮 - 增强版
document.getElementById('refreshCaptcha').addEventListener('click', function() {
	console.log("手动刷新验证码");
	fetchCaptcha();
	document.getElementById('captcha').value = ''; // 清空验证码输入框

	// 添加视觉反馈
	const refreshBtn = this;
	const originalText = refreshBtn.textContent;
	refreshBtn.textContent = '刷新中...';
	refreshBtn.disabled = true;

	setTimeout(() => {
		refreshBtn.textContent = originalText;
		refreshBtn.disabled = false;
	}, 1000);
});

// 处理登录表单提交
document.getElementById('loginForm').addEventListener('submit', function(e) {
	e.preventDefault();

	const username = document.getElementById('username').value;
	const password = document.getElementById('password').value;
	const captcha = document.getElementById('captcha').value;
	const loginStatus = document.getElementById('loginStatus');

	// 清除之前的状态消息
	loginStatus.className = 'status-message hidden';

	// 验证码为空检查
	if (!captcha) {
		loginStatus.textContent = '请输入验证码';
		loginStatus.className = 'status-message error';
		loginStatus.classList.remove('hidden');
		return;
	}

	fetch('/login', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				username,
				password,
				captcha
			})
		})
		.then(response => {
			// 首先检查响应状态
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.message || `服务器错误: ${response.status}`);
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				checkLoginStatus(); // 重新检查登录状态以获取用户组信息
			} else {
				loginStatus.textContent = '登录失败: ' + (data.message || '未知错误');
				loginStatus.className = 'status-message error';
				loginStatus.classList.remove('hidden');
				// 登录失败时刷新验证码
				fetchCaptcha();
				document.getElementById('captcha').value = '';
			}
		})
		.catch(error => {
			loginStatus.textContent = '登录出错: ' + error.message;
			loginStatus.className = 'status-message error';
			loginStatus.classList.remove('hidden');
			// 出错时也刷新验证码
			fetchCaptcha();
			document.getElementById('captcha').value = '';
		});
});

// 处理注册表单提交
document.getElementById('registerForm').addEventListener('submit', function(e) {
	e.preventDefault();

	const username = document.getElementById('regUsername').value;
	const password = document.getElementById('regPassword').value;
	const email = document.getElementById('regEmail').value;
	const chineseAlias = document.getElementById('regChineseAlias').value; // 新增
	const registerStatus = document.getElementById('registerStatus');

	// 清除之前的状态消息
	registerStatus.className = 'status-message hidden';

	fetch('/register', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				username,
				password,
				email,
				chinese_alias: chineseAlias // 新增
			})
		})
		.then(response => {
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.message || `服务器错误: ${response.status}`);
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				registerStatus.textContent = '注册成功，请登录';
				registerStatus.className = 'status-message success';
				registerStatus.classList.remove('hidden');

				// 自动跳转到登录页面
				setTimeout(() => {
					document.getElementById('registerSection').classList.add('hidden');
					document.getElementById('loginSection').classList.remove('hidden');

					// 自动填充用户名
					document.getElementById('username').value = username;
					document.getElementById('password').focus();
				}, 1500);
			} else {
				registerStatus.textContent = '注册失败: ' + (data.message || '未知错误');
				registerStatus.className = 'status-message error';
				registerStatus.classList.remove('hidden');
			}
		})
		.catch(error => {
			registerStatus.textContent = '注册出错: ' + error.message;
			registerStatus.className = 'status-message error';
			registerStatus.classList.remove('hidden');
		});
});

// 绑定个人设置按钮事件
document.getElementById('personalSettingsBtn').addEventListener('click', openPersonalSettingsModal);

// 绑定个人设置表单提交事件
document.getElementById('personalSettingsForm').addEventListener('submit', function(e) {
	e.preventDefault();
	savePersonalSettings();
});

// 绑定个人设置取消按钮事件
document.getElementById('cancelPersonalSettings').addEventListener('click', closePersonalSettingsModal);

// 点击模态框外部关闭个人设置
window.addEventListener('click', function(event) {
	const modal = document.getElementById('personalSettingsModal');
	if (event.target === modal) {
		closePersonalSettingsModal();
	}
});

// 显示注册表单按钮
document.getElementById('showRegisterBtn').addEventListener('click', function() {
	showRegisterSection();
});

// 返回登录表单按钮
document.getElementById('backToLoginBtn').addEventListener('click', function() {
	showLoginSection();
});

// 处理退出登录
document.getElementById('logoutBtn').addEventListener('click', function() {
	fetch('/logout', {
			method: 'POST'
		})
		.then(response => response.json())
		.then(data => {
			if (data.success) {
				// 清除sessionStorage
				sessionStorage.removeItem('userGroup');
				showLoginSection();
			}
		})
		.catch(error => {
			console.error('退出登录失败:', error);
		});
});

// 加载用户列表（root2和root可访问）
function loadUserList() {
	console.log("开始加载用户列表...");
	fetch('/users')
		.then(response => {
			if (!response.ok) {
				if (response.status === 403) {
					console.log('没有权限访问用户管理功能');
					return;
				}
				throw new Error('获取用户列表失败');
			}
			return response.json();
		})
		.then(data => {
			console.log("获取到的用户数据:", data);
			if (data.users) {
				updateUserList(data.users);
			}
		})
		.catch(error => {
			console.error('获取用户列表失败:', error);
		});
}

// 更新用户列表显示
function updateUserList(users) {
	const userListElement = document.getElementById('userList');
	userListElement.innerHTML = '';

	if (users.length === 0) {
		const row = document.createElement('tr');
		const cell = document.createElement('td');
		cell.colSpan = 6; // 更新为6列
		cell.textContent = '暂无用户';
		cell.style.textAlign = 'center';
		cell.style.padding = '20px';
		row.appendChild(cell);
		userListElement.appendChild(row);
		return;
	}

	// 获取当前用户组 - 直接从sessionStorage获取
	const currentUserGroup = sessionStorage.getItem('userGroup') || 'other';
	const currentUserId = sessionStorage.getItem('user_id');
	console.log("当前用户组:", currentUserGroup);
	console.log("当前用户ID:", currentUserId);

	users.forEach(user => {
		const row = document.createElement('tr');

		// 用户名 - 如果不是root2用户且查看的是root2用户，则隐藏用户名
		const usernameCell = document.createElement('td');
		if (currentUserGroup !== 'root2' && user.user_group === 'root2') {
			usernameCell.textContent = '******';
		} else {
			usernameCell.textContent = user.username;
		}
		row.appendChild(usernameCell);

		// 中文别名
		const aliasCell = document.createElement('td');
		if (currentUserGroup !== 'root2' && user.user_group === 'root2') {
			aliasCell.textContent = '******';
		} else {
			aliasCell.textContent = user.chinese_alias || '未设置';
		}
		row.appendChild(aliasCell);

		// 邮箱
		const emailCell = document.createElement('td');
		if (currentUserGroup !== 'root2' && user.user_group === 'root2') {
			emailCell.textContent = '******';
		} else {
			emailCell.textContent = user.email || '未设置';
		}
		row.appendChild(emailCell);

		// 用户组
		const groupCell = document.createElement('td');
		const groupTag = document.createElement('span');
		const groupNames = {
			'root2': '超级管理员',
			'root': '管理员',
			'competition': '比赛用户',
			'other': '普通用户'
		};
		groupTag.textContent = groupNames[user.user_group] || user.user_group;
		groupTag.className = `user-group-tag group-${user.user_group}`;
		groupCell.appendChild(groupTag);
		row.appendChild(groupCell);

		// 注册时间
		const timeCell = document.createElement('td');
		timeCell.textContent = user.created_at;
		row.appendChild(timeCell);

		// 操作按钮
		const actionCell = document.createElement('td');
		const buttonContainer = document.createElement('div');
		buttonContainer.className = 'action-buttons';

		// 编辑用户组按钮 - 为root2用户显示所有按钮
		if (currentUserGroup === 'root2') {
			const editBtn = document.createElement('button');
			editBtn.textContent = '编辑用户组';
			editBtn.className = 'user-action-btn edit-group-btn';
			editBtn.addEventListener('click', () => {
				console.log("编辑用户:", user.id, user.username); // 调试信息
				openEditUserGroupModal(user.id, user.user_group);
			});
			buttonContainer.appendChild(editBtn);

			// 添加编辑中文别名按钮
			const editAliasBtn = document.createElement('button');
			editAliasBtn.textContent = '编辑别名';
			editAliasBtn.className = 'user-action-btn edit-group-btn';
			editAliasBtn.style.background = '#9c27b0';
			editAliasBtn.addEventListener('click', () => {
				openEditChineseAliasModal(user.id, user.chinese_alias || '');
			});
			buttonContainer.appendChild(editAliasBtn);
		}

		// 为root用户显示非root2用户的编辑按钮
		else if (currentUserGroup === 'root' && user.user_group !== 'root2') {
			const editBtn = document.createElement('button');
			editBtn.textContent = '编辑用户组';
			editBtn.className = 'user-action-btn edit-group-btn';
			editBtn.addEventListener('click', () => {
				console.log("编辑用户:", user.id, user.username); // 调试信息
				openEditUserGroupModal(user.id, user.user_group);
			});
			buttonContainer.appendChild(editBtn);
		}

		// 添加删除用户按钮 - 不能删除自己和root2用户
		if (currentUserGroup === 'root2' && user.id.toString() !== currentUserId && user.user_group !==
			'root2') {
			const deleteBtn = document.createElement('button');
			deleteBtn.textContent = '删除用户';
			deleteBtn.className = 'user-action-btn delete-btn';
			deleteBtn.style.background = '#e74c3c';
			deleteBtn.addEventListener('click', () => {
				deleteUser(user.id, user.username);
			});
			buttonContainer.appendChild(deleteBtn);
		}

		actionCell.appendChild(buttonContainer);
		row.appendChild(actionCell);
		userListElement.appendChild(row);
	});
}

// 在 deleteUser 函数中更新错误处理部分
function deleteUser(userId, username) {
	if (!confirm(`确定要删除用户 "${username}" 吗？此操作不可撤销！`)) {
		return;
	}

	// 显示确认对话框，要求输入用户名确认
	const confirmUsername = prompt(`请输入要删除的用户名 "${username}" 以确认删除操作：`);
	if (confirmUsername !== username) {
		showMessage('用户名不匹配，删除操作已取消', 'error');
		return;
	}

	fetch(`/users/${userId}`, {
			method: 'DELETE',
			headers: {
				'Content-Type': 'application/json',
			}
		})
		.then(response => {
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(JSON.stringify(errorData));
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				showMessage('用户删除成功', 'success');
				loadUserList(); // 刷新用户列表
			} else {
				showMessage('用户删除失败: ' + (data.error || '未知错误'), 'error');
			}
		})
		.catch(error => {
			try {
				const errorData = JSON.parse(error.message);
				if (errorData.details) {
					showMessage(
						`无法删除用户: ${errorData.error} (文件: ${errorData.details.file_count || 0}, 文件夹: ${errorData.details.folder_count || 0}, 下载记录: ${errorData.details.download_count || 0})`,
						'error'
					);
				} else {
					showMessage('用户删除出错: ' + errorData.error, 'error');
				}
			} catch {
				showMessage('用户删除出错: ' + error.message, 'error');
			}
		});
}

// 添加编辑中文别名模态框功能
function openEditChineseAliasModal(userId, currentAlias) {
	currentEditingUserId = userId;
	const inputElement = document.getElementById('chineseAliasInput');
	inputElement.value = currentAlias;
	document.getElementById('editChineseAliasModal').style.display = 'block';
}

function closeEditChineseAliasModal() {
	document.getElementById('editChineseAliasModal').style.display = 'none';
	currentEditingUserId = null;
}

function saveChineseAlias() {
	if (!currentEditingUserId) return;

	const newAlias = document.getElementById('chineseAliasInput').value;

	fetch(`/users/${currentEditingUserId}/chinese_alias`, {
			method: 'PUT',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				chinese_alias: newAlias
			})
		})
		.then(response => {
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.error || '更新失败');
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				showMessage('中文别名更新成功', 'success');
				closeEditChineseAliasModal();
				loadUserList(); // 刷新用户列表

				// 如果修改的是当前用户，立即更新显示
				const currentUserId = sessionStorage.getItem('user_id');
				if (currentEditingUserId.toString() === currentUserId) {
					updateCurrentUserDisplay(currentUserProfile.username, newAlias);
					// 重新加载用户信息确保数据同步
					loadUserProfile();
				}
			} else {
				showMessage('中文别名更新失败: ' + (data.error || '未知错误'), 'error');
			}
		})
		.catch(error => {
			showMessage('中文别名更新出错: ' + error.message, 'error');
		});
}

// 打开编辑用户组模态框
function openEditUserGroupModal(userId, currentGroup) {
	currentEditingUserId = userId;
	const selectElement = document.getElementById('userGroupSelect');

	// 获取当前用户组
	const currentUserGroup = sessionStorage.getItem('userGroup') || 'other';

	// 设置当前值
	selectElement.value = currentGroup;

	// 如果是root用户，不能选择root2组
	if (currentUserGroup === 'root') {
		const root2Option = selectElement.querySelector('option[value="root2"]');
		if (root2Option) {
			root2Option.disabled = true;
		}
	}

	document.getElementById('editUserGroupModal').style.display = 'block';
}

// 关闭编辑用户组模态框
function closeEditUserGroupModal() {
	document.getElementById('editUserGroupModal').style.display = 'none';
	currentEditingUserId = null;

	// 重置所有选项的disabled状态
	const selectElement = document.getElementById('userGroupSelect');
	const options = selectElement.querySelectorAll('option');
	options.forEach(option => {
		option.disabled = false;
	});
}

// 保存用户组
function saveUserGroup() {
	if (!currentEditingUserId) return;

	const newGroup = document.getElementById('userGroupSelect').value;

	fetch(`/users/${currentEditingUserId}`, {
			method: 'PUT',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				user_group: newGroup
			})
		})
		.then(response => {
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.error || '更新失败');
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				showMessage('用户组更新成功', 'success');
				closeEditUserGroupModal();
				loadUserList(); // 刷新用户列表
			} else {
				showMessage('用户组更新失败: ' + (data.error || '未知错误'), 'error');
			}
		})
		.catch(error => {
			showMessage('用户组更新出错: ' + error.message, 'error');
		});
}

// 打开重命名文件模态框
function openRenameFileModal(storedFilename, currentFilename) {
	currentRenamingFile = storedFilename;
	document.getElementById('newFilename').value = currentFilename;
	document.getElementById('renameFileModal').style.display = 'block';
}

// 关闭重命名文件模态框
function closeRenameFileModal() {
	document.getElementById('renameFileModal').style.display = 'none';
	currentRenamingFile = null;
	document.getElementById('newFilename').value = '';
}

// 保存文件重命名
function saveRenameFile() {
	if (!currentRenamingFile) return;

	const newFilename = document.getElementById('newFilename').value.trim();

	if (!newFilename) {
		showMessage('新文件名不能为空', 'error');
		return;
	}

	fetch(`/rename_file/${currentRenamingFile}`, {
			method: 'PUT',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				new_filename: newFilename
			})
		})
		.then(response => {
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.error || '重命名失败');
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				showMessage('文件重命名成功', 'success');
				closeRenameFileModal();
				// 刷新文件列表
				if (currentViewingFolderId) {
					loadFolderFiles(currentViewingFolderId);
				} else {
					const categoryFilter = document.getElementById('categoryFilter').value;
					const subcategoryFilter = document.getElementById('subcategoryFilter').value;
					fetchFiles(categoryFilter, subcategoryFilter);
				}
			} else {
				showMessage('文件重命名失败: ' + (data.error || '未知错误'), 'error');
			}
		})
		.catch(error => {
			showMessage('文件重命名出错: ' + error.message, 'error');
		});
}

// 打开更改子分类模态框
function openChangeSubcategoryModal(storedFilename, currentSubcategory) {
	currentChangingSubcategoryFile = storedFilename;
	document.getElementById('newSubcategory').value = currentSubcategory;
	document.getElementById('changeSubcategoryModal').style.display = 'block';
}

// 关闭更改子分类模态框
function closeChangeSubcategoryModal() {
	document.getElementById('changeSubcategoryModal').style.display = 'none';
	currentChangingSubcategoryFile = null;
}

// 保存子分类更改
function saveChangeSubcategory() {
	if (!currentChangingSubcategoryFile) return;

	const newSubcategory = document.getElementById('newSubcategory').value;

	fetch(`/update_subcategory/${currentChangingSubcategoryFile}`, {
			method: 'PUT',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				subcategory: newSubcategory
			})
		})
		.then(response => {
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.error || '子分类更新失败');
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				showMessage('文件子分类更新成功', 'success');
				closeChangeSubcategoryModal();
				// 刷新文件列表
				if (currentViewingFolderId) {
					loadFolderFiles(currentViewingFolderId);
				} else {
					const categoryFilter = document.getElementById('categoryFilter').value;
					const subcategoryFilter = document.getElementById('subcategoryFilter').value;
					fetchFiles(categoryFilter, subcategoryFilter);
				}
			} else {
				showMessage('文件子分类更新失败: ' + (data.error || '未知错误'), 'error');
			}
		})
		.catch(error => {
			showMessage('文件子分类更新出错: ' + error.message, 'error');
		});
}

// 绑定模态框事件
document.getElementById('cancelEditUserGroup').addEventListener('click', closeEditUserGroupModal);
document.getElementById('saveUserGroup').addEventListener('click', saveUserGroup);

document.getElementById('cancelRenameFile').addEventListener('click', closeRenameFileModal);
document.getElementById('saveRenameFile').addEventListener('click', saveRenameFile);

document.getElementById('cancelChangeSubcategory').addEventListener('click', closeChangeSubcategoryModal);
document.getElementById('saveChangeSubcategory').addEventListener('click', saveChangeSubcategory);

// 点击模态框外部关闭
window.addEventListener('click', function(event) {
	const modals = ['editUserGroupModal', 'renameFileModal', 'changeSubcategoryModal',
		'createFolderModal', 'editFolderPermissionsModal'
	];
	modals.forEach(modalId => {
		const modal = document.getElementById(modalId);
		if (event.target === modal) {
			if (modalId === 'editUserGroupModal') closeEditUserGroupModal();
			if (modalId === 'renameFileModal') closeRenameFileModal();
			if (modalId === 'changeSubcategoryModal') closeChangeSubcategoryModal();
			if (modalId === 'createFolderModal') closeCreateFolderModal();
			if (modalId === 'editFolderPermissionsModal') closeEditFolderPermissionsModal();
		}
	});
});

// 修改fetchFiles函数支持子分类筛选
function fetchFiles(category = '', subcategory = '') {
	let url = '/files?';
	const params = new URLSearchParams();

	if (category) params.append('category', category);
	if (subcategory) params.append('subcategory', subcategory);

	url += params.toString();

	fetch(url)
		.then(response => {
			if (!response.ok) {
				throw new Error('获取文件列表失败');
			}
			return response.json();
		})
		.then(data => {
			if (data.files) {
				updateFileList(data.files);
			} else if (data.error) {
				showMessage('获取文件列表失败: ' + data.error, 'error');
			}
		})
		.catch(error => {
			console.error('获取文件列表失败:', error);
			showMessage('获取文件列表失败', 'error');
		});
}

// 分类筛选事件
document.getElementById('categoryFilter').addEventListener('change', function() {
	const subcategory = document.getElementById('subcategoryFilter').value;
	fetchFiles(this.value, subcategory);
});

// 子分类筛选事件
document.getElementById('subcategoryFilter').addEventListener('change', function() {
	const category = document.getElementById('categoryFilter').value;
	fetchFiles(category, this.value);
});

// 更新文件列表显示
function updateFileList(files) {
	const fileListElement = document.getElementById('fileList');
	fileListElement.innerHTML = '';

	if (files.length === 0) {
		const row = document.createElement('tr');
		const cell = document.createElement('td');
		cell.colSpan = 8; // 更新为8列
		cell.textContent = '暂无文件';
		cell.style.textAlign = 'center';
		cell.style.padding = '20px';
		row.appendChild(cell);
		fileListElement.appendChild(row);
		return;
	}

	files.forEach(file => {
		const row = document.createElement('tr');

		// 文件名
		const nameCell = document.createElement('td');
		nameCell.textContent = file.filename;
		nameCell.title = file.filename;
		row.appendChild(nameCell);

		// 文件大小
		const sizeCell = document.createElement('td');
		sizeCell.textContent = formatFileSize(file.file_size);
		sizeCell.style.textAlign = 'right';
		row.appendChild(sizeCell);

		// 上传时间
		const timeCell = document.createElement('td');
		timeCell.textContent = file.upload_time;
		row.appendChild(timeCell);

		// 上传者
		const uploaderCell = document.createElement('td');
		uploaderCell.textContent = file.upload_username || '未知';
		row.appendChild(uploaderCell);

		// 文件分类
		const categoryCell = document.createElement('td');
		const categoryTag = document.createElement('span');
		categoryTag.textContent = file.file_category === 'everyone' ? '公用文件' : '比赛文件';
		categoryTag.className = `category-tag category-${file.file_category}`;
		categoryCell.appendChild(categoryTag);
		row.appendChild(categoryCell);

		// 文件子分类
		const subcategoryCell = document.createElement('td');
		const subcategoryMapping = {
			'mirror': '镜像文件',
			'image': '图片文件',
			'document': '文档文件',
			'video': '视频文件',
			'other': '其他文件'
		};
		subcategoryCell.textContent = subcategoryMapping[file.file_subcategory] || file.file_subcategory;
		row.appendChild(subcategoryCell);

		// 下载次数
		const downloadCountCell = document.createElement('td');
		downloadCountCell.textContent = file.download_count || 0;
		downloadCountCell.style.textAlign = 'center';
		row.appendChild(downloadCountCell);

		// 操作按钮 - 重新排版
		const actionCell = document.createElement('td');
		const buttonContainer = document.createElement('div');
		buttonContainer.className = 'action-buttons';

		// 第一行按钮：常用操作
		const firstRow = document.createElement('div');
		firstRow.className = 'action-row';

		// 下载按钮
		if (currentUserPermissions.includes('download')) {
			const downloadBtn = document.createElement('button');
			downloadBtn.textContent = '下载';
			downloadBtn.className = 'action-btn download-btn';
			downloadBtn.addEventListener('click', () => downloadFile(file.stored_filename, file.filename, file
				.file_size));
			firstRow.appendChild(downloadBtn);
		}

		// 重命名按钮（需要rename_files权限）
		if (currentUserPermissions.includes('rename_files')) {
			const renameBtn = document.createElement('button');
			renameBtn.textContent = '重命名';
			renameBtn.className = 'action-btn rename-btn';
			renameBtn.addEventListener('click', () => openRenameFileModal(file.stored_filename, file
				.filename));
			firstRow.appendChild(renameBtn);
		}

		// 更改子分类按钮（需要change_subcategory权限）
		if (currentUserPermissions.includes('change_subcategory')) {
			const changeSubcategoryBtn = document.createElement('button');
			changeSubcategoryBtn.textContent = '改分类';
			changeSubcategoryBtn.className = 'action-btn change-subcategory-btn';
			changeSubcategoryBtn.addEventListener('click', () => openChangeSubcategoryModal(file
				.stored_filename, file.file_subcategory));
			firstRow.appendChild(changeSubcategoryBtn);
		}

		// 第二行按钮：管理操作
		const secondRow = document.createElement('div');
		secondRow.className = 'action-row';

		// 分类切换按钮（需要delete权限）
		if (currentUserPermissions.includes('delete')) {
			const toggleCategoryBtn = document.createElement('button');
			toggleCategoryBtn.textContent = file.file_category === 'everyone' ? '设为比赛' : '设为公用';
			toggleCategoryBtn.className = 'action-btn toggle-category-btn';
			toggleCategoryBtn.addEventListener('click', () => toggleFileCategory(file.stored_filename,
				file
				.file_category));
			secondRow.appendChild(toggleCategoryBtn);
		}

		// 删除按钮（需要delete权限）
		if (currentUserPermissions.includes('delete')) {
			const deleteBtn = document.createElement('button');
			deleteBtn.textContent = '删除';
			deleteBtn.className = 'action-btn delete-btn';
			deleteBtn.addEventListener('click', () => deleteFile(file.stored_filename));
			secondRow.appendChild(deleteBtn);
		}

		// 将两行按钮添加到按钮容器
		buttonContainer.appendChild(firstRow);
		buttonContainer.appendChild(secondRow);
		actionCell.appendChild(buttonContainer);
		row.appendChild(actionCell);
		fileListElement.appendChild(row);
	});
}

// 格式化文件大小
function formatFileSize(bytes) {
	if (bytes === 0) return '0 Bytes';
	const k = 1024;
	const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
	const i = Math.floor(Math.log(bytes) / Math.log(k));
	return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 显示消息
function showMessage(message, type) {
	const statusElement = document.getElementById('statusMessage');
	statusElement.textContent = message;
	statusElement.className = 'status-message ' + type;
	statusElement.classList.remove('hidden');

	// 5秒后自动隐藏
	setTimeout(() => {
		statusElement.classList.add('hidden');
	}, 5000);
}

// 绑定文件夹模态框事件
document.getElementById('cancelCreateFolder').addEventListener('click', closeCreateFolderModal);
document.getElementById('cancelEditFolderPermissions').addEventListener('click',
	closeEditFolderPermissionsModal);

// 绑定编辑中文别名模态框事件
document.getElementById('cancelEditChineseAlias').addEventListener('click', closeEditChineseAliasModal);
document.getElementById('saveChineseAlias').addEventListener('click', saveChineseAlias);

// 点击模态框外部关闭编辑中文别名
window.addEventListener('click', function(event) {
	const modal = document.getElementById('editChineseAliasModal');
	if (event.target === modal) {
		closeEditChineseAliasModal();
	}
});

// 切换文件分类
function toggleFileCategory(storedFilename, currentCategory) {
	const newCategory = currentCategory === 'everyone' ? 'competition' : 'everyone';

	if (!confirm(`确定要将文件分类改为${newCategory === 'everyone' ? '公用文件' : '比赛文件'}吗？`)) {
		return;
	}

	fetch(`/update_category/${storedFilename}`, {
			method: 'PUT',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				category: newCategory
			})
		})
		.then(response => {
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.error || '分类更新失败');
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				showMessage('文件分类更新成功', 'success');
				// 刷新文件列表
				if (currentViewingFolderId) {
					loadFolderFiles(currentViewingFolderId);
				} else {
					const categoryFilter = document.getElementById('categoryFilter').value;
					const subcategoryFilter = document.getElementById('subcategoryFilter').value;
					fetchFiles(categoryFilter, subcategoryFilter);
				}
			} else {
				showMessage('文件分类更新失败: ' + (data.error || '未知错误'), 'error');
			}
		})
		.catch(error => {
			showMessage('文件分类更新出错: ' + error.message, 'error');
		});
}

// 处理文件上传
document.getElementById('uploadForm').addEventListener('submit', function(e) {
	e.preventDefault();

	const fileInput = document.getElementById('fileInput');
	const files = fileInput.files;
	const progressBar = document.getElementById('progressBar');
	const progress = document.getElementById('progress');
	const useChunkedUpload = document.getElementById('chunkedUpload').checked;
	const fileCategory = document.getElementById('fileCategory').value;
	const folderId = document.getElementById('folderSelect').value;

	if (files.length === 0) {
		showMessage('请选择要上传的文件', 'error');
		return;
	}

	// 显示进度条
	progressBar.style.display = 'block';
	progress.style.width = '0%';
	progress.textContent = '0%';

	// 根据文件大小决定使用普通上传还是分块上传
	Array.from(files).forEach((file, index) => {
		if (useChunkedUpload && file.size > 100 * 1024 * 1024) { // 大于100MB使用分块上传
			uploadFileInChunks(file, progressBar, progress, files.length, index, fileCategory,
				folderId);
		} else {
			uploadFileDirectly(file, progressBar, progress, files.length, index, fileCategory,
				folderId);
		}
	});
});

// 直接上传文件（适用于小文件）
function uploadFileDirectly(file, progressBar, progressElement, totalFiles, fileIndex, category, folderId) {
	const formData = new FormData();
	formData.append('file', file);
	formData.append('category', category);
	formData.append('subcategory', document.getElementById('fileSubcategory').value);
	if (folderId) {
		formData.append('folder_id', folderId);
	}

	const xhr = new XMLHttpRequest();

	// 上传进度事件
	xhr.upload.addEventListener('progress', function(e) {
		if (e.lengthComputable) {
			const fileProgress = (e.loaded / e.total) * 100;
			const totalProgress = ((fileIndex * 100) + fileProgress) / totalFiles;
			progressElement.style.width = totalProgress + '%';
			progressElement.textContent = Math.round(totalProgress) + '%';
		}
	});

	// 请求完成
	xhr.addEventListener('load', function() {
		if (xhr.status === 200) {
			try {
				const response = JSON.parse(xhr.responseText);
				if (response.success) {
					showMessage('文件上传成功', 'success');
					document.getElementById('fileInput').value = '';

					// 刷新文件列表
					if (currentViewingFolderId) {
						loadFolderFiles(currentViewingFolderId);
					} else {
						const categoryFilter = document.getElementById('categoryFilter').value;
						const subcategoryFilter = document.getElementById('subcategoryFilter').value;
						fetchFiles(categoryFilter, subcategoryFilter);
					}
				} else {
					showMessage('文件上传失败: ' + (response.error || '未知错误'), 'error');
				}
			} catch (e) {
				showMessage('文件上传响应解析失败', 'error');
			}
		} else {
			if (xhr.status === 401) {
				showMessage('会话已过期，请重新登录', 'error');
				showLoginSection();
			} else if (xhr.status === 403) {
				showMessage('权限不足：没有上传权限', 'error');
			} else {
				try {
					const errorData = JSON.parse(xhr.responseText);
					showMessage('文件上传失败: ' + (errorData.error || xhr.responseText), 'error');
				} catch (e) {
					showMessage('文件上传失败: ' + xhr.responseText, 'error');
				}
			}
		}

		// 所有文件上传完成后隐藏进度条
		if (fileIndex === totalFiles - 1) {
			setTimeout(() => {
				progressBar.style.display = 'none';
			}, 1000);
		}
	});

	// 请求错误
	xhr.addEventListener('error', function() {
		showMessage('文件上传出错: 网络错误或服务器无响应', 'error');
		if (fileIndex === totalFiles - 1) {
			progressBar.style.display = 'none';
		}
	});

	xhr.open('POST', '/upload', true);
	xhr.send(formData);
}

// 分块上传文件（适用于大文件）
function uploadFileInChunks(file, progressBar, progressElement, totalFiles, fileIndex, category, folderId) {
	const CHUNK_SIZE = 100 * 1024 * 1024; // 100MB分块
	const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
	const identifier = Math.random().toString(36).substring(2) + Date.now().toString(36);
	let uploadedChunks = 0;

	// 上传每个分块
	for (let chunkNumber = 1; chunkNumber <= totalChunks; chunkNumber++) {
		const start = (chunkNumber - 1) * CHUNK_SIZE;
		const end = Math.min(start + CHUNK_SIZE, file.size);
		const chunk = file.slice(start, end);

		const formData = new FormData();
		formData.append('chunk', chunk);
		formData.append('chunkNumber', chunkNumber);
		formData.append('totalChunks', totalChunks);
		formData.append('filename', file.name);
		formData.append('identifier', identifier);
		formData.append('category', category);
		formData.append('subcategory', document.getElementById('fileSubcategory').value);
		if (folderId) {
			formData.append('folder_id', folderId);
		}

		const xhr = new XMLHttpRequest();

		xhr.addEventListener('load', function() {
			uploadedChunks++;

			if (xhr.status === 200) {
				const chunkProgress = (uploadedChunks / totalChunks) * 100;
				const totalProgress = ((fileIndex * 100) + chunkProgress) / totalFiles;
				progressElement.style.width = totalProgress + '%';
				progressElement.textContent = Math.round(totalProgress) + '%';

				if (uploadedChunks === totalChunks) {
					// 所有分块上传完成，合并文件
					mergeChunks(file.name, identifier, totalChunks, progressBar, totalFiles, fileIndex,
						category, folderId);
				}
			} else if (xhr.status === 403) {
				showMessage('权限不足：没有上传权限', 'error');
			} else {
				try {
					const errorData = JSON.parse(xhr.responseText);
					showMessage('分块上传失败: ' + (errorData.error || xhr.responseText), 'error');
				} catch (e) {
					showMessage('分块上传失败: ' + xhr.responseText, 'error');
				}
			}
		});

		xhr.addEventListener('error', function() {
			showMessage('分块上传出错', 'error');
		});

		xhr.open('POST', '/upload_chunk', true);
		xhr.send(formData);
	}
}

// 合并分块
function mergeChunks(filename, identifier, totalChunks, progressBar, totalFiles, fileIndex, category, folderId) {
	const formData = new FormData();
	formData.append('filename', filename);
	formData.append('identifier', identifier);
	formData.append('totalChunks', totalChunks);
	formData.append('category', category);
	formData.append('subcategory', document.getElementById('fileSubcategory').value);
	if (folderId) {
		formData.append('folder_id', folderId);
	}

	fetch('/merge_chunks', {
			method: 'POST',
			body: formData
		})
		.then(response => {
			if (!response.ok) {
				if (response.status === 403) {
					throw new Error('权限不足：没有上传权限');
				}
				return response.json().then(errorData => {
					throw new Error(errorData.error || '合并失败');
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				showMessage('文件上传成功: ' + filename, 'success');
				document.getElementById('fileInput').value = '';

				// 刷新文件列表
				if (currentViewingFolderId) {
					loadFolderFiles(currentViewingFolderId);
				} else {
					const categoryFilter = document.getElementById('categoryFilter').value;
					const subcategoryFilter = document.getElementById('subcategoryFilter').value;
					fetchFiles(categoryFilter, subcategoryFilter);
				}
			} else {
				showMessage('文件合并失败: ' + (data.error || '未知错误'), 'error');
			}

			// 所有文件上传完成后隐藏进度条
			if (fileIndex === totalFiles - 1) {
				setTimeout(() => {
					progressBar.style.display = 'none';
				}, 1000);
			}
		})
		.catch(error => {
			showMessage('文件合并出错: ' + error.message, 'error');
			if (fileIndex === totalFiles - 1) {
				progressBar.style.display = 'none';
			}
		});
}

// ========== 文件下载功能 ==========

// 更新下载按钮的点击事件
function downloadFile(storedFilename) {
    // 使用新的统一下载端点
    window.open(`/download/${storedFilename}`, '_blank');
}

// ========== 大文件下载函数 (100MB - 10GB) ==========
function downloadLargeFileWithProgress(storedFilename, originalFilename, fileSize) {
    console.log(`[LARGE_FILE] 开始下载大文件: ${originalFilename}, 大小: ${formatFileSize(fileSize)}`);
    
    // 显示下载进度界面
    showDownloadProgressWithBar(originalFilename, fileSize);
    updateDebugInfo(`开始下载大文件 (${formatFileSize(fileSize)})`);
    
    const MAX_RETRIES = 3;
    let retryCount = 0;
    let currentChunkStart = 0;
    
    function attemptDownload() {
        updateDebugInfo(`下载尝试 ${retryCount + 1}/${MAX_RETRIES}`);
        
        const xhr = new XMLHttpRequest();
        currentDownloadController = xhr;
        
        // 重置下载状态
        window.downloadStartTime = Date.now();
        let lastLoaded = 0;
        let lastTime = window.downloadStartTime;
        
        // 设置超时时间 - 对于大文件设置更长超时
        const timeoutDuration = 30 * 60 * 1000; // 30分钟超时
        let timeoutTimer = setTimeout(() => {
            updateDebugInfo('下载超时，正在重试...');
            xhr.abort();
            handleRetry();
        }, timeoutDuration);
        
        xhr.open('GET', `/download_large/${storedFilename}`, true);
        xhr.responseType = 'blob';
        
        // 进度事件
        xhr.addEventListener('progress', function(event) {
            // 清除超时计时器，因为有进度
            clearTimeout(timeoutTimer);
            timeoutTimer = setTimeout(() => {
                updateDebugInfo('传输停滞，正在重试...');
                xhr.abort();
                handleRetry();
            }, 60000); // 60秒无活动则超时
            
            if (event.lengthComputable && event.total > 0) {
                const loaded = event.loaded;
                const total = event.total;
                const percent = (loaded / total * 100).toFixed(1);
                
                updateDownloadProgress(loaded, total);
                
                // 计算速度
                const currentTime = Date.now();
                const timeDiff = (currentTime - lastTime) / 1000;
                
                if (timeDiff >= 1) {
                    const loadedDiff = loaded - lastLoaded;
                    const speed = loadedDiff / timeDiff;
                    
                    updateSpeedInfo(speed, loaded, total);
                    lastLoaded = loaded;
                    lastTime = currentTime;
                }
                
                updateDebugInfo(`下载中: ${percent}% - ${formatFileSize(loaded)}/${formatFileSize(total)}`);
            }
        });
        
        // 加载完成
        xhr.addEventListener('load', function() {
            clearTimeout(timeoutTimer);
            
            if (xhr.status === 200) {
                const blob = xhr.response;
                if (blob && blob.size > 0) {
                    updateDebugInfo('下载完成，正在创建文件...');
                    
                    const url = window.URL.createObjectURL(blob);
                    setTimeout(() => {
                        triggerDownload(url, originalFilename);
                        updateDebugInfo('下载完成！');
                        
                        setTimeout(() => {
                            window.URL.revokeObjectURL(url);
                            hideDownloadProgress();
                            showMessage('文件下载完成', 'success');
                            refreshFileListAfterDownload();
                        }, 2000);
                    }, 100);
                } else {
                    updateDebugInfo('错误: 下载的文件为空');
                    showMessage('下载的文件为空', 'error');
                    hideDownloadProgress();
                }
            } else {
                updateDebugInfo(`服务器错误: ${xhr.status} - ${xhr.statusText}`);
                handleRetry();
            }
        });
        
        // 错误处理
        xhr.addEventListener('error', function() {
            clearTimeout(timeoutTimer);
            updateDebugInfo('网络错误，正在重试...');
            handleRetry();
        });
        
        xhr.addEventListener('abort', function() {
            clearTimeout(timeoutTimer);
            if (retryCount < MAX_RETRIES) {
                updateDebugInfo('下载被中止，正在重试...');
            }
        });
        
        // 发送请求
        updateDebugInfo('开始传输数据...');
        xhr.send();
        
        function handleRetry() {
            retryCount++;
            if (retryCount < MAX_RETRIES) {
                updateDebugInfo(`等待 3 秒后重试 (${retryCount}/${MAX_RETRIES})`);
                setTimeout(attemptDownload, 3000);
            } else {
                updateDebugInfo('下载失败: 超过最大重试次数');
                showMessage('下载失败: 网络不稳定，请稍后重试', 'error');
                hideDownloadProgress();
            }
        }
    }
    
    // 开始下载尝试
    attemptDownload();
}

// ========== 超大文件下载函数 (10GB+) ==========
function downloadHugeFileWithProgress(storedFilename, originalFilename, fileSize) {
    console.log(`[HUGE_FILE] 开始下载超大文件: ${originalFilename}, 大小: ${formatFileSize(fileSize)}`);
    
    // 显示超大文件专用下载界面
    showHugeFileDownloadProgress(originalFilename, fileSize);
    updateHugeDebugInfo(`开始下载超大文件 (${formatFileSize(fileSize)})`);
    
    const CHUNK_SIZE = 32 * 1024 * 1024; // 32MB 分块
    const totalChunks = Math.ceil(fileSize / CHUNK_SIZE);
    let downloadedChunks = 0;
    let isPaused = false;
    let currentChunk = 0;
    
    // 恢复下载状态
    const resumeKey = `resume_${storedFilename}`;
    const resumeData = localStorage.getItem(resumeKey);
    if (resumeData) {
        const resume = JSON.parse(resumeData);
        currentChunk = resume.currentChunk || 0;
        downloadedChunks = resume.downloadedChunks || 0;
        updateHugeDebugInfo(`恢复下载: 已下载 ${downloadedChunks}/${totalChunks} 分块`);
    }
    
    // 下载单个分块
    function downloadChunk(chunkIndex) {
        if (isPaused || chunkIndex >= totalChunks) return;
        
        const start = chunkIndex * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE - 1, fileSize - 1);
        
        updateHugeDebugInfo(`下载分块 ${chunkIndex + 1}/${totalChunks}`);
        
        const xhr = new XMLHttpRequest();
        currentDownloadController = xhr;
        
        xhr.open('GET', `/download_chunk/${storedFilename}`, true);
        xhr.setRequestHeader('Range', `bytes=${start}-${end}`);
        xhr.responseType = 'blob';
        
        xhr.addEventListener('load', function() {
            if (xhr.status === 200 || xhr.status === 206) {
                const blob = xhr.response;
                saveChunkToStorage(chunkIndex, blob).then(() => {
                    downloadedChunks++;
                    currentChunk = chunkIndex + 1;
                    
                    // 更新进度
                    const loaded = downloadedChunks * CHUNK_SIZE;
                    updateHugeDownloadProgress(loaded, fileSize);
                    
                    // 保存恢复点
                    localStorage.setItem(resumeKey, JSON.stringify({
                        currentChunk: currentChunk,
                        downloadedChunks: downloadedChunks
                    }));
                    
                    // 继续下载下一个分块或完成
                    if (currentChunk < totalChunks && !isPaused) {
                        downloadChunk(currentChunk);
                    } else if (downloadedChunks === totalChunks) {
                        updateHugeDebugInfo('所有分块下载完成，开始合并...');
                        mergeAllChunks();
                    }
                }).catch(error => {
                    updateHugeDebugInfo(`分块保存失败: ${error.message}`);
                    setTimeout(() => downloadChunk(chunkIndex), 3000);
                });
            } else {
                updateHugeDebugInfo(`分块下载失败: ${xhr.status}`);
                setTimeout(() => downloadChunk(chunkIndex), 3000);
            }
        });
        
        xhr.addEventListener('error', function() {
            updateHugeDebugInfo('分块下载网络错误');
            setTimeout(() => downloadChunk(chunkIndex), 3000);
        });
        
        xhr.send();
    }
    
    // 保存分块到本地存储
    function saveChunkToStorage(chunkIndex, blob) {
        return new Promise((resolve, reject) => {
            try {
                const reader = new FileReader();
                reader.onload = function() {
                    const chunkKey = `chunk_${storedFilename}_${chunkIndex}`;
                    localStorage.setItem(chunkKey, reader.result);
                    resolve();
                };
                reader.onerror = reject;
                reader.readAsDataURL(blob);
            } catch (error) {
                reject(error);
            }
        });
    }
    
    // 合并所有分块
    function mergeAllChunks() {
        updateHugeDebugInfo('开始合并所有分块...');
        
        try {
            const chunks = [];
            let totalSize = 0;
            
            // 收集所有分块
            for (let i = 0; i < totalChunks; i++) {
                const chunkKey = `chunk_${storedFilename}_${i}`;
                const chunkData = localStorage.getItem(chunkKey);
                if (!chunkData) {
                    throw new Error(`分块 ${i} 数据丢失`);
                }
                
                // 从DataURL提取二进制数据
                const binaryString = atob(chunkData.split(',')[1]);
                const bytes = new Uint8Array(binaryString.length);
                for (let j = 0; j < binaryString.length; j++) {
                    bytes[j] = binaryString.charCodeAt(j);
                }
                
                chunks.push(bytes);
                totalSize += bytes.length;
            }
            
            // 合并所有分块
            const mergedArray = new Uint8Array(totalSize);
            let offset = 0;
            chunks.forEach(chunk => {
                mergedArray.set(chunk, offset);
                offset += chunk.length;
            });
            
            const finalBlob = new Blob([mergedArray], {
                type: 'application/octet-stream'
            });
            const url = URL.createObjectURL(finalBlob);
            
            // 触发下载
            triggerDownload(url, originalFilename);
            
            // 清理
            cleanupChunks();
            localStorage.removeItem(resumeKey);
            
            updateHugeDebugInfo('文件合并完成！');
            setTimeout(() => {
                hideHugeDownloadProgress();
                showMessage('超大文件下载完成！', 'success');
                refreshFileListAfterDownload();
            }, 2000);
            
        } catch (error) {
            updateHugeDebugInfo(`合并失败: ${error.message}`);
            showMessage('文件合并失败，请重新下载', 'error');
        }
    }
    
    // 清理分块数据
    function cleanupChunks() {
        for (let i = 0; i < totalChunks; i++) {
            const chunkKey = `chunk_${storedFilename}_${i}`;
            localStorage.removeItem(chunkKey);
        }
    }
    
    // 暂停下载
    function pauseDownload() {
        isPaused = true;
        if (currentDownloadController) {
            currentDownloadController.abort();
            currentDownloadController = null;
        }
        updateHugeDebugInfo('下载已暂停');
    }
    
    // 恢复下载
    function resumeDownload() {
        if (isPaused) {
            isPaused = false;
            updateHugeDebugInfo('恢复下载');
            downloadChunk(currentChunk);
        }
    }
    
    // 取消下载
    function cancelDownload() {
        pauseDownload();
        cleanupChunks();
        localStorage.removeItem(resumeKey);
        hideHugeDownloadProgress();
        showMessage('下载已取消', 'info');
    }
    
    // 暴露控制函数到全局
    window.pauseHugeDownload = pauseDownload;
    window.resumeHugeDownload = resumeDownload;
    window.cancelHugeDownload = cancelDownload;
    
    // 开始下载
    downloadChunk(currentChunk);
}

// ========== 通用下载辅助函数 ==========

// 更新大文件下载进度
function updateDownloadProgress(loaded, total) {
	let progressPercent = 0;
	let displayText = '0%';

	if (total > 0) {
		progressPercent = (loaded / total) * 100;
		displayText = `${formatFileSize(loaded)} / ${formatFileSize(total)} (${progressPercent.toFixed(1)}%)`;
	} else {
		// 总大小未知，只显示已下载量
		displayText = `${formatFileSize(loaded)} / 计算中...`;
	}

	const progressBar = document.getElementById('downloadProgressBar');
	const progressText = document.getElementById('downloadProgressText');

	if (progressBar) {
		progressBar.style.width = `${progressPercent}%`;
		// 添加颜色变化
		if (progressPercent < 30) {
			progressBar.style.background = 'linear-gradient(90deg, #e74c3c, #e67e22)';
		} else if (progressPercent < 70) {
			progressBar.style.background = 'linear-gradient(90deg, #e67e22, #f1c40f)';
		} else {
			progressBar.style.background = 'linear-gradient(90deg, #27ae60, #2ecc71)';
		}
	}

	if (progressText) {
		progressText.textContent = displayText;
	}

	console.log(`[DEBUG] 进度更新: ${displayText}`);
}

// 更新超大文件下载进度
function updateHugeDownloadProgress(loaded, total) {
	let progressPercent = 0;
	let displayText = '0%';

	if (total > 0) {
		progressPercent = (loaded / total) * 100;
		displayText = `${formatFileSize(loaded)} / ${formatFileSize(total)} (${progressPercent.toFixed(2)}%)`;
	} else {
		displayText = `${formatFileSize(loaded)} / 计算中...`;
	}

	const progressBar = document.getElementById('hugeDownloadProgressBar');
	const progressText = document.getElementById('hugeDownloadProgressText');

	if (progressBar) {
		progressBar.style.width = `${progressPercent}%`;
		// 超大文件专用颜色
		if (progressPercent < 10) {
			progressBar.style.background = 'linear-gradient(90deg, #e74c3c, #e67e22)';
		} else if (progressPercent < 30) {
			progressBar.style.background = 'linear-gradient(90deg, #e67e22, #f39c12)';
		} else if (progressPercent < 60) {
			progressBar.style.background = 'linear-gradient(90deg, #f39c12, #f1c40f)';
		} else if (progressPercent < 90) {
			progressBar.style.background = 'linear-gradient(90deg, #f1c40f, #2ecc71)';
		} else {
			progressBar.style.background = 'linear-gradient(90deg, #2ecc71, #27ae60)';
		}
	}

	if (progressText) {
		progressText.textContent = displayText;
	}
}

// 更新大文件速度信息
function updateSpeedInfo(speed, loaded, total) {
    const speedElement = document.getElementById('downloadSpeedText');
    const timeElement = document.getElementById('downloadTimeText');

    if (speedElement) {
        speedElement.textContent = `速度: ${formatFileSize(speed)}/s`;
    }

    if (timeElement && speed > 0) {
        const remaining = (total - loaded) / speed;
        timeElement.textContent = `剩余: ${formatTime(remaining)}`;
    }
}

// 更新超大文件速度信息
function updateHugeSpeedInfo(speed, loaded, total) {
    const speedElement = document.getElementById('hugeDownloadSpeedText');
    const timeElement = document.getElementById('hugeDownloadTimeText');
    const etaElement = document.getElementById('hugeDownloadETA');

    if (speedElement) {
        speedElement.textContent = `平均速度: ${formatFileSize(speed)}/s`;
    }

    if (timeElement && speed > 0) {
        const remaining = (total - loaded) / speed;
        timeElement.textContent = `预计剩余: ${formatTime(remaining)}`;
    }

    if (etaElement && speed > 0) {
        const remaining = (total - loaded) / speed;
        const eta = new Date(Date.now() + remaining * 1000);
        etaElement.textContent = `预计完成: ${eta.toLocaleTimeString()}`;
    }
}

// 更新大文件调试信息
function updateDebugInfo(message) {
    const debugElement = document.getElementById('debugStatus');
    if (debugElement) {
        const timestamp = new Date().toLocaleTimeString();
        const newMessage = `${timestamp} - ${message}`;

        // 保留历史记录（最多5条）
        const currentText = debugElement.textContent;
        const lines = currentText.split('\n').filter(line => line.trim());
        lines.push(newMessage);
        if (lines.length > 5) {
            lines.shift();
        }

        debugElement.textContent = lines.join('\n');
    }
    console.log(`[DEBUG] ${message}`);
}

// 更新超大文件调试信息
function updateHugeDebugInfo(message) {
    const debugElement = document.getElementById('hugeDebugStatus');
    if (debugElement) {
        const timestamp = new Date().toLocaleTimeString();
        const newMessage = `${timestamp} - ${message}`;

        // 保留历史记录（最多10条）
        const currentText = debugElement.textContent;
        const lines = currentText.split('\n').filter(line => line.trim());
        lines.push(newMessage);
        if (lines.length > 10) {
            lines.shift();
        }

        debugElement.textContent = lines.join('\n');
    }
    console.log(`[HUGE_DEBUG] ${message}`);
}

// 显示大文件下载进度界面
function showDownloadProgressWithBar(filename, totalSize) {
	// 移除可能存在的旧进度条
	hideDownloadProgress();

	// 记录下载开始时间
	window.downloadStartTime = Date.now();

	const progressDiv = document.createElement('div');
	progressDiv.id = 'large-file-progress';
	progressDiv.innerHTML = `
        <div class="download-progress-container" style="
            background: white;
            padding: 20px;
            border: 2px solid #007cba;
            border-radius: 8px;
            text-align: center;
            min-width: 500px;
            max-width: 90vw;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        ">
            <h4 style="margin: 0 0 15px 0; color: #007cba;">
                📥 大文件下载中...
            </h4>
            
            <div style="text-align: left; margin-bottom: 15px; padding: 10px; background: #f8f9fa; border-radius: 4px;">
                <div style="font-size: 14px; font-weight: bold; margin-bottom: 5px;">📄 文件信息</div>
                <div style="font-size: 12px; color: #666;">
                    <div><strong>文件名:</strong> ${filename}</div>
                    <div><strong>总大小:</strong> ${formatFileSize(totalSize)}</div>
                    <div><strong>开始时间:</strong> ${new Date().toLocaleTimeString()}</div>
                </div>
            </div>
            
            <div class="progress-container" style="margin: 15px 0;">
                <div class="progress-bar" style="
                    width: 100%;
                    height: 25px;
                    background: #e9ecef;
                    border-radius: 12px;
                    overflow: hidden;
                    position: relative;
                    border: 1px solid #dee2e6;
                ">
                    <div id="downloadProgressBar" class="progress-fill" style="
                        width: 0%;
                        height: 100%;
                        background: linear-gradient(90deg, #007cba, #00a8ff);
                        transition: width 0.5s ease;
                        border-radius: 12px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                    ">
                        <div id="downloadProgressText" style="
                            color: white;
                            font-size: 12px;
                            font-weight: bold;
                            text-shadow: 1px 1px 2px rgba(0,0,0,0.5);
                        ">0%</div>
                    </div>
                </div>
            </div>
            
            <div class="download-info" style="
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 10px;
                margin: 15px 0;
                font-size: 13px;
            ">
                <div style="text-align: left;">
                    <strong>📊 实时状态</strong>
                </div>
                <div style="text-align: right;">
                    <strong>⏱️ 预计时间</strong>
                </div>
                <div id="downloadSpeedText" style="text-align: left;">
                    速度: 计算中...
                </div>
                <div id="downloadTimeText" style="text-align: right;">
                    剩余: 计算中...
                </div>
            </div>
            
            <div class="debug-info" style="
                margin: 15px 0;
                padding: 10px;
                background: #f1f3f4;
                border-radius: 4px;
                font-size: 11px;
                color: #5f6368;
                text-align: left;
                max-height: 80px;
                overflow-y: auto;
                font-family: 'Consolas', 'Monaco', monospace;
                border: 1px solid #dadce0;
            ">
                <div style="font-weight: bold; margin-bottom: 5px; color: #007cba;">🔍 下载日志:</div>
                <div id="debugStatus" style="white-space: pre-wrap; line-height: 1.4;">初始化下载组件...</div>
            </div>
            
            <button onclick="cancelDownload()" style="
                margin-top: 10px;
                padding: 10px 24px;
                background: #dc3545;
                color: white;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 14px;
                font-weight: bold;
                transition: all 0.3s;
                box-shadow: 0 2px 4px rgba(0,0,0,0.2);
            " onmouseover="this.style.background='#c82333'; this.style.transform='translateY(-1px)'" 
               onmouseout="this.style.background='#dc3545'; this.style.transform='translateY(0)'">
                ❌ 取消下载
            </button>
        </div>
    `;

	progressDiv.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        z-index: 10000;
    `;

	document.body.appendChild(progressDiv);

	// 初始调试信息
	updateDebugInfo(`开始下载: ${filename}`);
	updateDebugInfo(`文件大小: ${formatFileSize(totalSize)}`);
	updateDebugInfo('等待服务器响应...');
}

// 显示超大文件下载进度界面
function showHugeFileDownloadProgress(filename, totalSize) {
	// 移除可能存在的旧进度条
	hideHugeDownloadProgress();

	// 记录下载开始时间
	window.downloadStartTime = Date.now();

	const progressDiv = document.createElement('div');
	progressDiv.id = 'huge-file-progress';
	progressDiv.innerHTML = `
        <div class="huge-download-progress-container" style="
            background: white;
            padding: 25px;
            border: 3px solid #8e44ad;
            border-radius: 12px;
            text-align: center;
            min-width: 600px;
            max-width: 95vw;
            box-shadow: 0 6px 25px rgba(0,0,0,0.3);
        ">
            <h4 style="margin: 0 0 20px 0; color: #8e44ad; font-size: 18px;">
                🚀 超大文件下载中 (10GB+)...
            </h4>
            
            <div style="text-align: left; margin-bottom: 20px; padding: 15px; background: #f8f9fa; border-radius: 6px;">
                <div style="font-size: 15px; font-weight: bold; margin-bottom: 8px; color: #8e44ad;">📦 文件信息</div>
                <div style="font-size: 13px; color: #666;">
                    <div><strong>文件名:</strong> ${filename}</div>
                    <div><strong>总大小:</strong> ${formatFileSize(totalSize)}</div>
                    <div><strong>开始时间:</strong> ${new Date().toLocaleTimeString()}</div>
                    <div><strong>下载类型:</strong> 超大文件优化模式</div>
                </div>
            </div>
            
            <div class="progress-container" style="margin: 20px 0;">
                <div class="progress-bar" style="
                    width: 100%;
                    height: 30px;
                    background: #e9ecef;
                    border-radius: 15px;
                    overflow: hidden;
                    position: relative;
                    border: 2px solid #dee2e6;
                ">
                    <div id="hugeDownloadProgressBar" class="progress-fill" style="
                        width: 0%;
                        height: 100%;
                        background: linear-gradient(90deg, #8e44ad, #9b59b6);
                        transition: width 0.8s ease;
                        border-radius: 15px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                    ">
                        <div id="hugeDownloadProgressText" style="
                            color: white;
                            font-size: 13px;
                            font-weight: bold;
                            text-shadow: 1px 1px 3px rgba(0,0,0,0.5);
                        ">0%</div>
                    </div>
                </div>
            </div>
            
            <div class="download-info" style="
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 15px;
                margin: 20px 0;
                font-size: 14px;
            ">
                <div style="text-align: left;">
                    <strong>📊 传输状态</strong>
                </div>
                <div style="text-align: right;">
                    <strong>⏱️ 时间预估</strong>
                </div>
                <div id="hugeDownloadSpeedText" style="text-align: left;">
                    平均速度: 计算中...
                </div>
                <div id="hugeDownloadTimeText" style="text-align: right;">
                    预计剩余: 计算中...
                </div>
                <div style="text-align: left; color: #666; font-size: 12px;">
                    优化模式: 32MB块传输
                </div>
                <div id="hugeDownloadETA" style="text-align: right; color: #666; font-size: 12px;">
                    预计完成: 计算中...
                </div>
            </div>
            
            <div class="debug-info" style="
                margin: 20px 0;
                padding: 12px;
                background: #f1f3f4;
                border-radius: 6px;
                font-size: 11px;
                color: #5f6368;
                text-align: left;
                max-height: 120px;
                overflow-y: auto;
                font-family: 'Consolas', 'Monaco', monospace;
                border: 1px solid #dadce0;
            ">
                <div style="font-weight: bold; margin-bottom: 6px; color: #8e44ad;">🔍 超大文件传输日志:</div>
                <div id="hugeDebugStatus" style="white-space: pre-wrap; line-height: 1.4; font-size: 10px;">初始化超大文件下载组件...</div>
            </div>
            
            <div style="display: flex; gap: 10px; justify-content: center;">
                <button onclick="pauseResumeHugeDownload()" id="pauseResumeBtn" style="
                    padding: 10px 20px;
                    background: #3498db;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 14px;
                    font-weight: bold;
                    transition: all 0.3s;
                ">⏸️ 暂停</button>
                
                <button onclick="cancelHugeDownload()" style="
                    padding: 10px 20px;
                    background: #e74c3c;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 14px;
                    font-weight: bold;
                    transition: all 0.3s;
                ">❌ 取消下载</button>
            </div>
            
            <div style="margin-top: 15px; padding: 10px; background: #fff3cd; border-radius: 4px; border: 1px solid #ffeaa7;">
                <div style="font-size: 12px; color: #856404;">
                    💡 <strong>提示:</strong> 超大文件下载可能需要较长时间，请保持网络稳定，不要关闭此窗口。
                </div>
            </div>
        </div>
    `;

	progressDiv.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        z-index: 10001;
    `;

	document.body.appendChild(progressDiv);

	// 初始调试信息
	updateHugeDebugInfo(`开始下载超大文件: ${filename}`);
	updateHugeDebugInfo(`文件大小: ${formatFileSize(totalSize)}`);
	updateHugeDebugInfo('使用优化传输模式 (32MB块)');
	updateHugeDebugInfo('等待服务器响应...');
}

// 隐藏大文件下载进度
function hideDownloadProgress() {
	const progressDiv = document.getElementById('large-file-progress');
	if (progressDiv) {
		document.body.removeChild(progressDiv);
	}
	window.downloadStartTime = null;
	currentDownloadController = null;
}

// 隐藏超大文件下载进度
function hideHugeDownloadProgress() {
	const progressDiv = document.getElementById('huge-file-progress');
	if (progressDiv) {
		document.body.removeChild(progressDiv);
	}
	window.downloadStartTime = null;
	currentDownloadController = null;
}

// 暂停/恢复超大文件下载
function pauseResumeHugeDownload() {
	const btn = document.getElementById('pauseResumeBtn');
	if (btn.textContent.includes('暂停')) {
		btn.textContent = '▶️ 继续';
		btn.style.background = '#27ae60';
		window.pauseHugeDownload();
	} else {
		btn.textContent = '⏸️ 暂停';
		btn.style.background = '#3498db';
		window.resumeHugeDownload();
	}
}

// 取消大文件下载
function cancelDownload() {
	console.log('取消大文件下载');
	if (currentDownloadController) {
		currentDownloadController.abort();
		currentDownloadController = null;
	}
	hideDownloadProgress();
	showMessage('下载已取消', 'info');
}

// 取消超大文件下载
function cancelHugeDownload() {
	console.log('取消超大文件下载');
	window.cancelHugeDownload();
}

// 触发文件下载
function triggerDownload(url, filename) {
	const a = document.createElement('a');
	a.style.display = 'none';
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	setTimeout(() => {
		window.URL.revokeObjectURL(url);
		document.body.removeChild(a);
	}, 100);
}

// 格式化时间
function formatTime(seconds) {
	if (seconds < 60) {
		return `${Math.ceil(seconds)}秒`;
	} else if (seconds < 3600) {
		return `${Math.floor(seconds / 60)}分${Math.ceil(seconds % 60)}秒`;
	} else {
		const hours = Math.floor(seconds / 3600);
		const minutes = Math.floor((seconds % 3600) / 60);
		return `${hours}时${minutes}分`;
	}
}

// 小文件下载优化
function downloadSmallFile(storedFilename, originalFilename) {
	// 显示简单的下载提示
	showSimpleDownloadPrompt();

	// 使用fetch API先触发下载记录，然后再打开下载链接
	fetch('/download/' + storedFilename)
		.then(response => {
			if (response.status === 403) {
				showMessage('权限不足：没有下载权限', 'error');
				return;
			}
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.error || '下载失败');
				});
			}
			return response.blob();
		})
		.then(blob => {
			if (blob) {
				const url = window.URL.createObjectURL(blob);
				triggerDownload(url, originalFilename);
				hideSimpleDownloadPrompt();

				// 下载完成后刷新文件列表
				refreshFileListAfterDownload();
			}
		})
		.catch(error => {
			hideSimpleDownloadPrompt();
			if (error.message !== '权限不足：没有下载权限') {
				showMessage('下载出错: ' + error.message, 'error');
			}
		});
}

// 显示简单下载提示
function showSimpleDownloadPrompt() {
	const promptDiv = document.createElement('div');
	promptDiv.id = 'simple-download-prompt';
	promptDiv.innerHTML = `
        <div style="
            background: white;
            padding: 15px;
            border: 2px solid #28a745;
            border-radius: 8px;
            text-align: center;
            min-width: 250px;
        ">
            <p style="margin: 0; color: #28a745;">文件下载中...</p>
            <p style="margin: 5px 0 0 0; font-size: 12px; color: #666;">请查看浏览器下载管理器</p>
        </div>
    `;
	promptDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 10000;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    `;

	document.body.appendChild(promptDiv);

	// 3秒后自动隐藏
	setTimeout(hideSimpleDownloadPrompt, 3000);
}

function hideSimpleDownloadPrompt() {
	const promptDiv = document.getElementById('simple-download-prompt');
	if (promptDiv) {
		document.body.removeChild(promptDiv);
	}
}

// 刷新文件列表（下载完成后）
function refreshFileListAfterDownload() {
	setTimeout(() => {
		if (currentViewingFolderId) {
			loadFolderFiles(currentViewingFolderId);
		} else {
			const categoryFilter = document.getElementById('categoryFilter').value;
			const subcategoryFilter = document.getElementById('subcategoryFilter').value;
			fetchFiles(categoryFilter, subcategoryFilter);
		}
	}, 1000);
}

// 删除文件
function deleteFile(storedFilename) {
	if (!confirm('确定要删除此文件吗？')) {
		return;
	}

	fetch('/delete/' + storedFilename, {
			method: 'DELETE'
		})
		.then(response => {
			if (response.status === 403) {
				showMessage('权限不足：没有删除权限', 'error');
				return;
			}
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.error || '删除失败');
				});
			}
			return response.json();
		})
		.then(data => {
			if (data && data.success) {
				showMessage('文件删除成功', 'success');
				// 刷新文件列表
				if (currentViewingFolderId) {
					loadFolderFiles(currentViewingFolderId);
				} else {
					const categoryFilter = document.getElementById('categoryFilter').value;
					const subcategoryFilter = document.getElementById('subcategoryFilter').value;
					fetchFiles(categoryFilter, subcategoryFilter);
				}
			}
		})
		.catch(error => {
			if (error.message !== '权限不足：没有删除权限') {
				showMessage('文件删除出错: ' + error.message, 'error');
			}
		});
}

// ========== 文件夹管理功能 ==========

// 加载文件夹列表
function loadFolders() {
	fetch('/folders')
		.then(response => {
			if (!response.ok) {
				if (response.status === 403) {
					console.log('没有权限访问文件夹管理功能');
					return;
				}
				throw new Error('获取文件夹列表失败');
			}
			return response.json();
		})
		.then(data => {
			if (data.folders) {
				updateFolderList(data.folders);
			}
		})
		.catch(error => {
			console.error('获取文件夹列表失败:', error);
		});
}

// 更新文件夹列表显示
function updateFolderList(folders) {
	const folderListElement = document.getElementById('folderList');
	folderListElement.innerHTML = '';

	if (folders.length === 0) {
		const row = document.createElement('tr');
		const cell = document.createElement('td');
		cell.colSpan = 6;
		cell.textContent = '暂无文件夹';
		cell.style.textAlign = 'center';
		cell.style.padding = '20px';
		row.appendChild(cell);
		folderListElement.appendChild(row);
		return;
	}

	const currentUserGroup = sessionStorage.getItem('userGroup') || 'other';
	const currentUserId = sessionStorage.getItem('user_id');

	folders.forEach(folder => {
		const row = document.createElement('tr');

		// 文件夹名称
		const nameCell = document.createElement('td');
		nameCell.textContent = folder.name;
		nameCell.title = folder.name;
		row.appendChild(nameCell);

		// 创建者
		const creatorCell = document.createElement('td');
		creatorCell.textContent = folder.creator_name || folder.created_username;
		row.appendChild(creatorCell);

		// 创建时间
		const timeCell = document.createElement('td');
		timeCell.textContent = folder.created_at;
		row.appendChild(timeCell);

		// 权限设置
		const permissionCell = document.createElement('td');
		const allowedGroups = JSON.parse(folder.allowed_groups || '[]');

		allowedGroups.forEach(group => {
			const permissionTag = document.createElement('span');
			const groupNames = {
				'root2': '超级管理员',
				'root': '管理员',
				'competition': '比赛用户',
				'other': '普通用户'
			};
			permissionTag.textContent = groupNames[group] || group;
			permissionTag.className = `permission-tag permission-${group}`;
			permissionCell.appendChild(permissionTag);
		});

		if (allowedGroups.length === 0) {
			permissionCell.textContent = '无';
		}
		row.appendChild(permissionCell);

		// 是否公开
		const publicCell = document.createElement('td');
		publicCell.textContent = folder.is_visible_to_all ? '是' : '否';
		row.appendChild(publicCell);

		// 操作按钮
		const actionCell = document.createElement('td');
		const buttonContainer = document.createElement('div');
		buttonContainer.className = 'action-buttons';

		// 查看文件夹内容按钮
		const viewBtn = document.createElement('button');
		viewBtn.textContent = '查看';
		viewBtn.className = 'folder-action-btn view-folder-btn';
		viewBtn.addEventListener('click', () => viewFolderFiles(folder.id, folder.name));
		buttonContainer.appendChild(viewBtn);

		// 编辑权限按钮（仅root2可以编辑权限）
		if (currentUserGroup === 'root2') {
			const editBtn = document.createElement('button');
			editBtn.textContent = '编辑权限';
			editBtn.className = 'folder-action-btn edit-folder-btn';
			editBtn.addEventListener('click', () => openEditFolderPermissionsModal(folder.id, folder
				.allowed_groups, folder.is_visible_to_all));
			buttonContainer.appendChild(editBtn);
		}

		// 删除文件夹按钮（创建者或root2可以删除）
		if (folder.created_by == currentUserId || currentUserGroup === 'root2') {
			const deleteBtn = document.createElement('button');
			deleteBtn.textContent = '删除';
			deleteBtn.className = 'folder-action-btn delete-folder-btn';
			deleteBtn.addEventListener('click', () => deleteFolder(folder.id));
			buttonContainer.appendChild(deleteBtn);
		}

		actionCell.appendChild(buttonContainer);
		row.appendChild(actionCell);
		folderListElement.appendChild(row);
	});
}

// 加载文件夹选择选项
function loadFolderOptions() {
	fetch('/folders')
		.then(response => {
			if (!response.ok) {
				return;
			}
			return response.json();
		})
		.then(data => {
			if (data.folders) {
				updateFolderOptions(data.folders);
			}
		})
		.catch(error => {
			console.error('获取文件夹选项失败:', error);
		});
}

// 更新文件夹选择选项
function updateFolderOptions(folders) {
	const folderSelect = document.getElementById('folderSelect');
	// 保留第一个选项（无）
	while (folderSelect.options.length > 1) {
		folderSelect.remove(1);
	}

	folders.forEach(folder => {
		const option = document.createElement('option');
		option.value = folder.id;
		option.textContent = folder.name;
		folderSelect.appendChild(option);
	});
}

// 查看文件夹内容
function viewFolderFiles(folderId, folderName) {
	currentViewingFolderId = folderId;
	document.getElementById('folderFilesTitle').textContent = `文件夹: ${folderName}`;
	document.getElementById('fileListSection').style.display = 'none';
	document.getElementById('folderFileListSection').style.display = 'block';
	loadFolderFiles(folderId);
}

// 加载文件夹文件
function loadFolderFiles(folderId) {
	fetch(`/folder_files/${folderId}`)
		.then(response => {
			if (!response.ok) {
				if (response.status === 403) {
					showMessage('没有权限访问此文件夹', 'error');
					return;
				}
				throw new Error('获取文件夹文件列表失败');
			}
			return response.json();
		})
		.then(data => {
			if (data.files) {
				updateFolderFileList(data.files);
			} else if (data.error) {
				showMessage('获取文件夹文件列表失败: ' + data.error, 'error');
			}
		})
		.catch(error => {
			console.error('获取文件夹文件列表失败:', error);
			showMessage('获取文件夹文件列表失败', 'error');
		});
}

// 更新文件夹文件列表显示
function updateFolderFileList(files) {
	const folderFileListElement = document.getElementById('folderFileList');
	folderFileListElement.innerHTML = '';

	if (files.length === 0) {
		const row = document.createElement('tr');
		const cell = document.createElement('td');
		cell.colSpan = 8;
		cell.textContent = '文件夹为空';
		cell.style.textAlign = 'center';
		cell.style.padding = '20px';
		row.appendChild(cell);
		folderFileListElement.appendChild(row);
		return;
	}

	files.forEach(file => {
		const row = document.createElement('tr');

		// 文件名
		const nameCell = document.createElement('td');
		nameCell.textContent = file.filename;
		nameCell.title = file.filename;
		row.appendChild(nameCell);

		// 文件大小
		const sizeCell = document.createElement('td');
		sizeCell.textContent = formatFileSize(file.file_size);
		sizeCell.style.textAlign = 'right';
		row.appendChild(sizeCell);

		// 上传时间
		const timeCell = document.createElement('td');
		timeCell.textContent = file.upload_time;
		row.appendChild(timeCell);

		// 上传者
		const uploaderCell = document.createElement('td');
		uploaderCell.textContent = file.upload_username || '未知';
		row.appendChild(uploaderCell);

		// 文件分类
		const categoryCell = document.createElement('td');
		const categoryTag = document.createElement('span');
		categoryTag.textContent = file.file_category === 'everyone' ? '公用文件' : '比赛文件';
		categoryTag.className = `category-tag category-${file.file_category}`;
		categoryCell.appendChild(categoryTag);
		row.appendChild(categoryCell);

		// 文件子分类
		const subcategoryCell = document.createElement('td');
		const subcategoryMapping = {
			'mirror': '镜像文件',
			'image': '图片文件',
			'document': '文档文件',
			'video': '视频文件',
			'other': '其他文件'
		};
		subcategoryCell.textContent = subcategoryMapping[file.file_subcategory] || file.file_subcategory;
		row.appendChild(subcategoryCell);

		// 下载次数
		const downloadCountCell = document.createElement('td');
		downloadCountCell.textContent = file.download_count || 0;
		downloadCountCell.style.textAlign = 'center';
		row.appendChild(downloadCountCell);

		// 操作按钮
		const actionCell = document.createElement('td');
		const buttonContainer = document.createElement('div');
		buttonContainer.className = 'action-buttons';

		// 第一行按钮：常用操作
		const firstRow = document.createElement('div');
		firstRow.className = 'action-row';

		// 下载按钮
		if (currentUserPermissions.includes('download')) {
			const downloadBtn = document.createElement('button');
			downloadBtn.textContent = '下载';
			downloadBtn.className = 'action-btn download-btn';
			downloadBtn.addEventListener('click', () => downloadFile(file.stored_filename, file.filename, file
				.file_size));
			firstRow.appendChild(downloadBtn);
		}

		// 重命名按钮（需要rename_files权限）
		if (currentUserPermissions.includes('rename_files')) {
			const renameBtn = document.createElement('button');
			renameBtn.textContent = '重命名';
			renameBtn.className = 'action-btn rename-btn';
			renameBtn.addEventListener('click', () => openRenameFileModal(file.stored_filename, file
				.filename));
			firstRow.appendChild(renameBtn);
		}

		// 更改子分类按钮（需要change_subcategory权限）
		if (currentUserPermissions.includes('change_subcategory')) {
			const changeSubcategoryBtn = document.createElement('button');
			changeSubcategoryBtn.textContent = '改分类';
			changeSubcategoryBtn.className = 'action-btn change-subcategory-btn';
			changeSubcategoryBtn.addEventListener('click', () => openChangeSubcategoryModal(file
				.stored_filename, file.file_subcategory));
			firstRow.appendChild(changeSubcategoryBtn);
		}

		// 第二行按钮：管理操作
		const secondRow = document.createElement('div');
		secondRow.className = 'action-row';

		// 分类切换按钮（需要delete权限）
		if (currentUserPermissions.includes('delete')) {
			const toggleCategoryBtn = document.createElement('button');
			toggleCategoryBtn.textContent = file.file_category === 'everyone' ? '设为比赛' : '设为公用';
			toggleCategoryBtn.className = 'action-btn toggle-category-btn';
			toggleCategoryBtn.addEventListener('click', () => toggleFileCategory(file.stored_filename,
				file
				.file_category));
			secondRow.appendChild(toggleCategoryBtn);
		}

		// 删除按钮（需要delete权限）
		if (currentUserPermissions.includes('delete')) {
			const deleteBtn = document.createElement('button');
			deleteBtn.textContent = '删除';
			deleteBtn.className = 'action-btn delete-btn';
			deleteBtn.addEventListener('click', () => deleteFile(file.stored_filename));
			secondRow.appendChild(deleteBtn);
		}

		// 将两行按钮添加到按钮容器
		buttonContainer.appendChild(firstRow);
		buttonContainer.appendChild(secondRow);
		actionCell.appendChild(buttonContainer);
		row.appendChild(actionCell);
		folderFileListElement.appendChild(row);
	});
}

// 返回所有文件列表
document.getElementById('backToAllFiles').addEventListener('click', function() {
	currentViewingFolderId = null;
	document.getElementById('folderFileListSection').style.display = 'none';
	document.getElementById('fileListSection').style.display = 'block';
	fetchFiles();
});

// 打开创建文件夹模态框
document.getElementById('createFolderBtn').addEventListener('click', function() {
	document.getElementById('createFolderModal').style.display = 'block';
});

// 关闭创建文件夹模态框
function closeCreateFolderModal() {
	document.getElementById('createFolderModal').style.display = 'none';
	document.getElementById('folderName').value = '';
	document.getElementById('permissionRoot2').checked = false;
	document.getElementById('permissionRoot').checked = true;
	document.getElementById('permissionCompetition').checked = false;
	document.getElementById('permissionOther').checked = false;
	document.getElementById('isVisibleToAll').checked = false;
}

// 保存创建文件夹
document.getElementById('saveCreateFolder').addEventListener('click', function() {
	const folderName = document.getElementById('folderName').value.trim();

	if (!folderName) {
		showMessage('文件夹名称不能为空', 'error');
		return;
	}

	const allowedGroups = [];
	if (document.getElementById('permissionRoot2').checked) allowedGroups.push('root2');
	if (document.getElementById('permissionRoot').checked) allowedGroups.push('root');
	if (document.getElementById('permissionCompetition').checked) allowedGroups.push('competition');
	if (document.getElementById('permissionOther').checked) allowedGroups.push('other');

	const isVisibleToAll = document.getElementById('isVisibleToAll').checked;

	fetch('/folders', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				name: folderName,
				allowed_groups: allowedGroups,
				is_visible_to_all: isVisibleToAll
			})
		})
		.then(response => {
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.error || '创建失败');
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				showMessage('文件夹创建成功', 'success');
				closeCreateFolderModal();
				loadFolders(); // 刷新文件夹列表
				loadFolderOptions(); // 刷新文件夹选择选项
			} else {
				showMessage('文件夹创建失败: ' + (data.error || '未知错误'), 'error');
			}
		})
		.catch(error => {
			showMessage('文件夹创建出错: ' + error.message, 'error');
		});
});

// 打开编辑文件夹权限模态框
function openEditFolderPermissionsModal(folderId, allowedGroups, isVisibleToAll) {
	currentEditingFolderId = folderId;

	// 解析权限组
	const groups = JSON.parse(allowedGroups || '[]');

	// 设置复选框状态
	document.getElementById('editPermissionRoot2').checked = groups.includes('root2');
	document.getElementById('editPermissionRoot').checked = groups.includes('root');
	document.getElementById('editPermissionCompetition').checked = groups.includes('competition');
	document.getElementById('editPermissionOther').checked = groups.includes('other');
	document.getElementById('editIsVisibleToAll').checked = isVisibleToAll;

	document.getElementById('editFolderPermissionsModal').style.display = 'block';
}

// 关闭编辑文件夹权限模态框
function closeEditFolderPermissionsModal() {
	document.getElementById('editFolderPermissionsModal').style.display = 'none';
	currentEditingFolderId = null;
}

// 保存编辑文件夹权限
document.getElementById('saveEditFolderPermissions').addEventListener('click', function() {
	if (!currentEditingFolderId) return;

	const allowedGroups = [];
	if (document.getElementById('editPermissionRoot2').checked) allowedGroups.push('root2');
	if (document.getElementById('editPermissionRoot').checked) allowedGroups.push('root');
	if (document.getElementById('editPermissionCompetition').checked) allowedGroups.push('competition');
	if (document.getElementById('editPermissionOther').checked) allowedGroups.push('other');

	const isVisibleToAll = document.getElementById('editIsVisibleToAll').checked;

	fetch(`/folders/${currentEditingFolderId}`, {
			method: 'PUT',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				allowed_groups: allowedGroups,
				is_visible_to_all: isVisibleToAll
			})
		})
		.then(response => {
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.error || '权限更新失败');
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				showMessage('文件夹权限更新成功', 'success');
				closeEditFolderPermissionsModal();
				loadFolders(); // 刷新文件夹列表
				loadFolderOptions(); // 刷新文件夹选择选项
			} else {
				showMessage('文件夹权限更新失败: ' + (data.error || '未知错误'), 'error');
			}
		})
		.catch(error => {
			showMessage('文件夹权限更新出错: ' + error.message, 'error');
		});
});

// 删除文件夹
function deleteFolder(folderId) {
	if (!confirm('确定要删除此文件夹吗？文件夹必须为空才能删除。')) {
		return;
	}

	fetch(`/folders/${folderId}`, {
			method: 'DELETE'
		})
		.then(response => {
			if (!response.ok) {
				return response.json().then(errorData => {
					throw new Error(errorData.error || '删除失败');
				});
			}
			return response.json();
		})
		.then(data => {
			if (data.success) {
				showMessage('文件夹删除成功', 'success');
				loadFolders(); // 刷新文件夹列表
				loadFolderOptions(); // 刷新文件夹选择选项

				// 如果当前正在查看被删除的文件夹，返回所有文件列表
				if (currentViewingFolderId === folderId) {
					currentViewingFolderId = null;
					document.getElementById('folderFileListSection').style.display = 'none';
					document.getElementById('fileListSection').style.display = 'block';
				}
			} else {
				showMessage('文件夹删除失败: ' + (data.error || '未知错误'), 'error');
			}
		})
		.catch(error => {
			showMessage('文件夹删除出错: ' + error.message, 'error');
		});
}
