#!/bin/bash
# Git Worktree 清理脚本
# 用途: 安全删除已完成的工作目录

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 默认配置
DEFAULT_WORKTREE_BASE=".git/worktrees"
WORKTREE_PATH=""
FORCE=false

# 用法说明
usage() {
    cat << EOF
${BLUE}Git Worktree 清理脚本${NC}

用途: 安全删除已完成的工作目录

用法:
    $(basename "$0") <worktree-path>|<worktree-name>
    $(basename "$0") --force <worktree-path>|<worktree-name>
    $(basename "$0") --list
    $(basename "$0") --prune

参数:
    worktree-path   worktree 完整路径或名称

选项:
    --force         跳过确认直接删除
    --list          列出所有 worktrees
    --prune         清理过期的 worktree 记录

示例:
    $(basename "$0") TASK-001-user-auth
    $(basename "$0") .git/worktrees/TASK-001-user-auth
    $(basename "$0") --force TASK-001-user-auth
    $(basename "$0") --list

环境变量:
    WORKTREE_BASE    worktree 基础路径 (默认: .git/worktrees)

EOF
    exit 1
}

# 日志函数
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 列出所有 worktrees
list_worktrees() {
    log_info "当前 worktrees:"
    echo ""
    git worktree list
    echo ""
    log_info "详细状态:"
    git worktree list --porcelain
}

# 清理过期的 worktree 记录
prune_worktrees() {
    log_info "清理过期的 worktree 记录..."
    git worktree prune
    log_success "清理完成"
}

# 验证 worktree 路径
resolve_worktree_path() {
    local input="$1"
    local worktree_base="${WORKTREE_BASE:-$DEFAULT_WORKTREE_BASE}"

    # 如果是完整路径，直接使用
    if [[ "$input" == /* ]] || [[ "$input" == .* ]]; then
        echo "$input"
    else
        # 否则视为 worktree 名称，拼接基础路径
        echo "$worktree_base/$input"
    fi
}

# 验证 worktree 存在
verify_worktree_exists() {
    local path="$1"

    if [ ! -d "$path" ]; then
        log_error "Worktree 目录不存在: $path"
        log_info "使用 --list 查看可用 worktrees"
        exit 1
    fi

    # 检查是否是有效的 worktree
    local git_dir="$path/.git"
    if [ ! -e "$git_dir" ]; then
        log_error "不是有效的 worktree: $path"
        exit 1
    fi
}

# 检查 worktree 是否有未提交的变更
check_uncommitted_changes() {
    local path="$1"

    if [ -n "$(git -C "$path" status --porcelain 2>/dev/null)" ]; then
        log_warn "Worktree 有未提交的变更:"
        git -C "$path" status --short
        echo ""
        log_warn "建议先提交或 stash 变更"
        return 1
    fi
    return 0
}

# 删除 worktree
remove_worktree() {
    local path="$1"

    log_info "准备删除 worktree: $path"
    echo ""

    # 检查未提交变更
    if ! check_uncommitted_changes "$path"; then
        if [ "$FORCE" = false ]; then
            read -p "仍要删除? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_info "取消操作"
                exit 0
            fi
        fi
    fi

    # 最终确认
    if [ "$FORCE" = false ]; then
        read -p "确认删除 worktree '$path'? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "取消操作"
            exit 0
        fi
    fi

    # 删除 worktree
    log_info "删除 worktree..."
    if git worktree remove "$path" 2>/dev/null; then
        log_success "Worktree 已删除"
    else
        # 如果 git worktree remove 失败，尝试手动删除
        log_warn "git worktree remove 失败，尝试手动删除..."
        rm -rf "$path"
        git worktree prune
        log_success "Worktree 已手动删除并清理"
    fi

    # 列出剩余 worktrees
    echo ""
    log_info "剩余 worktrees:"
    git worktree list
}

# 主函数
main() {
    # 参数检查
    if [ $# -lt 1 ]; then
        usage
    fi

    # 解析参数
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --list)
                list_worktrees
                exit 0
                ;;
            --prune)
                prune_worktrees
                exit 0
                ;;
            --force)
                FORCE=true
                shift
                ;;
            -*)
                log_error "未知选项: $1"
                usage
                ;;
            *)
                WORKTREE_PATH="$1"
                shift
                ;;
        esac
    done

    # 如果没有指定 worktree 路径，显示帮助
    if [ -z "$WORKTREE_PATH" ]; then
        usage
    fi

    # 解析路径
    WORKTREE_PATH="$(resolve_worktree_path "$WORKTREE_PATH")"

    # 验证
    verify_worktree_exists "$WORKTREE_PATH"

    # 删除
    remove_worktree "$WORKTREE_PATH"
}

# 执行
main "$@"
