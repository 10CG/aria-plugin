#!/bin/bash
# Git Worktree 创建脚本
# 用途: 为功能分支创建独立的工作目录

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 默认配置
DEFAULT_WORKTREE_BASE=".git/worktrees"
BRANCH_NAME=""
WORKTREE_NAME=""

# 用法说明
usage() {
    cat << EOF
${BLUE}Git Worktree 创建脚本${NC}

用途: 为功能分支创建独立的 worktree 工作目录

用法:
    $(basename "$0") <branch-name> [worktree-name]

参数:
    branch-name      功能分支名称 (如: feature/backend/TASK-001-user-auth)
    worktree-name    worktree 目录名 (可选，默认从 branch-name 提取)

示例:
    $(basename "$0") feature/backend/TASK-001-user-auth
    $(basename "$0") feature/mobile/TASK-002-login-ui TASK-002-login

环境变量:
    WORKTREE_BASE    worktree 基础路径 (默认: .git/worktrees)
    GIT_DIR          Git 目录 (默认: .git)

EOF
    exit 1
}

# 日志函数
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 提取 worktree 名称
extract_worktree_name() {
    local branch="$1"
    # 从分支名提取最后一段作为 worktree 名称
    basename "$branch" | sed 's/feature-//;s/bugfix-//;s/hotfix-//'
}

# 验证 Git 仓库
verify_git_repo() {
    if ! git rev-parse --git-dir >/dev/null 2>&1; then
        log_error "当前目录不是 Git 仓库"
        exit 1
    fi
}

# 验证分支存在
verify_branch_exists() {
    local branch="$1"
    if ! git rev-parse --verify "$branch" >/dev/null 2>&1; then
        log_error "分支不存在: $branch"
        log_info "请先创建分支: git checkout -b $branch"
        exit 1
    fi
}

# 检查 worktree 是否已存在
check_worktree_exists() {
    local worktree_path="$1"
    if [ -d "$worktree_path" ]; then
        log_error "Worktree 目录已存在: $worktree_path"
        log_info "使用 'git worktree list' 查看现有 worktrees"
        exit 1
    fi
}

# 创建 worktree
create_worktree() {
    local branch="$1"
    local worktree_path="$2"

    log_info "创建 worktree..."
    log_info "  分支: $branch"
    log_info "  路径: $worktree_path"

    if git worktree add "$worktree_path" "$branch" 2>/dev/null; then
        log_success "Worktree 创建成功"

        # 显示 worktree 信息
        echo ""
        log_info "Worktree 信息:"
        echo "  路径: $(cd "$worktree_path" && pwd)"
        echo "  分支: $branch"
        echo ""
        log_info "切换到 worktree:"
        echo "  cd $worktree_path"
        echo ""
        log_info "完成工作后删除 worktree:"
        echo "  git worktree remove $worktree_path"
    else
        log_error "Worktree 创建失败"
        exit 1
    fi
}

# 主函数
main() {
    # 参数检查
    if [ $# -lt 1 ]; then
        usage
    fi

    BRANCH_NAME="$1"
    WORKTREE_BASE="${WORKTREE_BASE:-$DEFAULT_WORKTREE_BASE}"

    # 提取或使用指定的 worktree 名称
    if [ -n "${2:-}" ]; then
        WORKTREE_NAME="$2"
    else
        WORKTREE_NAME="$(extract_worktree_name "$BRANCH_NAME")"
    fi

    WORKTREE_PATH="$WORKTREE_BASE/$WORKTREE_NAME"

    # 验证
    verify_git_repo
    verify_branch_exists "$BRANCH_NAME"
    check_worktree_exists "$WORKTREE_PATH"

    # 创建 worktree
    create_worktree "$BRANCH_NAME" "$WORKTREE_PATH"

    # 列出所有 worktrees
    echo ""
    log_info "当前 worktrees:"
    git worktree list
}

# 执行
main "$@"
