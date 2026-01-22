#!/bin/bash
# Git Worktree 路径切换脚本
# 用途: 在不同的 worktree 之间切换

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 默认配置
DEFAULT_WORKTREE_BASE=".git/worktrees"
WORKTREE_NAME=""
WORKTREE_BASE="${WORKTREE_BASE:-$DEFAULT_WORKTREE_BASE}"

# 用法说明
usage() {
    cat << EOF
${BLUE}Git Worktree 路径切换脚本${NC}

用途: 在不同的 worktree 工作目录之间切换

用法:
    $(basename "$0") <worktree-name>
    $(basename "$0") --list
    $(basename "$0") --current

参数:
    worktree-name    worktree 目录名称

选项:
    --list           列出所有可用 worktrees
    --current        显示当前 worktree

示例:
    $(basename "$0") TASK-001-user-auth
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

# 获取当前 worktree
get_current_worktree() {
    local git_dir="$(git rev-parse --git-dir 2>/dev/null)" || return 1
    local current_dir="$(pwd)"

    # 如果 .git 是文件，说明在 worktree 中
    if [ -f "$git_dir" ]; then
        # 读取 worktree 名称
        local worktree_git_dir="$(cat "$git_dir")"
        local worktree_name="$(basename "$(dirname "$worktree_git_dir")")"
        echo "$worktree_name"
    else
        echo "main"
    fi
}

# 列出所有 worktrees
list_worktrees() {
    log_info "可用的 worktrees:"
    echo ""

    local current_worktree="$(get_current_worktree)"

    # 主仓库
    if [ "$current_worktree" = "main" ]; then
        echo "  * $(basename "$(pwd)") (main) ← 当前"
    else
        echo "    $(basename "$(pwd)") (main)"
    fi

    # 列出所有 worktrees
    if [ -d "$WORKTREE_BASE" ]; then
        for worktree_dir in "$WORKTREE_BASE"/*; do
            if [ -d "$worktree_dir" ]; then
                local worktree_name="$(basename "$worktree_dir")"
                if [ "$worktree_name" = "$current_worktree" ]; then
                    echo "  * $worktree_name ← 当前"
                else
                    echo "    $worktree_name"
                fi

                # 显示分支信息
                if [ -f "$worktree_dir/.git" ]; then
                    local branch_file="$worktree_dir/.git"
                    if [ -f "$branch_file" ]; then
                        local head_file="$(dirname "$(cat "$branch_file")")/HEAD"
                        if [ -f "$head_file" ]; then
                            local branch="$(grep -o 'refs/heads/.*' "$head_file" 2>/dev/null | sed 's|refs/heads/||' || echo 'unknown')"
                            echo "      branch: $branch"
                        fi
                    fi
                fi
            fi
        done
    fi

    echo ""
    log_info "切换到 worktree: $(basename "$0") <name>"
}

# 切换到 worktree
switch_to_worktree() {
    local target_name="$1"
    local target_path="$WORKTREE_BASE/$target_name"

    # 验证 worktree 存在
    if [ ! -d "$target_path" ]; then
        log_error "Worktree 不存在: $target_name"
        log_info "使用 --list 查看可用 worktrees"
        exit 1
    fi

    # 获取绝对路径
    local absolute_path="$(cd "$target_path" && pwd)"

    log_info "切换到 worktree: $target_name"
    echo ""
    log_success "新工作目录: $absolute_path"
    echo ""
    log_info "执行以下命令切换:"
    echo "  cd $absolute_path"
    echo ""
    log_info "或添加到 shell 快捷方式:"
    echo "  alias goto$target_name='cd $absolute_path'"
}

# 主函数
main() {
    # 参数检查
    if [ $# -lt 1 ]; then
        usage
    fi

    case "$1" in
        --list)
            list_worktrees
            exit 0
            ;;
        --current)
            local current="$(get_current_worktree)"
            log_success "当前 worktree: $current"
            exit 0
            ;;
        -*)
            log_error "未知选项: $1"
            usage
            ;;
        *)
            WORKTREE_NAME="$1"
            switch_to_worktree "$WORKTREE_NAME"
            ;;
    esac
}

# 执行
main "$@"
