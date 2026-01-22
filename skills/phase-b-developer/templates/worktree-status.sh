#!/bin/bash
# Git Worktree 状态检查脚本
# 用途: 显示所有 worktree 的状态信息

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
GRAY='\033[0;90m'
NC='\033[0m'

# 默认配置
DEFAULT_WORKTREE_BASE=".git/worktrees"
WORKTREE_BASE="${WORKTREE_BASE:-$DEFAULT_WORKTREE_BASE}"

# 日志函数
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_dim() { echo -e "${GRAY}$1${NC}"; }

# 获取当前 worktree
get_current_worktree() {
    local git_dir="$(git rev-parse --git-dir 2>/dev/null)" || return 1
    if [ -f "$git_dir" ]; then
        local worktree_git_dir="$(cat "$git_dir")"
        local worktree_name="$(basename "$(dirname "$worktree_git_dir")")"
        echo "$worktree_name"
    else
        echo "main"
    fi
}

# 获取 worktree 分支
get_worktree_branch() {
    local worktree_path="$1"
    local head_file="$worktree_path/.git/HEAD"

    if [ -f "$head_file" ]; then
        local content="$(cat "$head_file")"
        if [[ "$content" == ref:* ]]; then
            echo "$content" | sed 's|refs/heads/||'
        else
            echo "detached@${content:0:7}"
        fi
    else
        echo "unknown"
    fi
}

# 获取 worktree 状态
get_worktree_status() {
    local worktree_path="$1"
    local git_dir="-C $worktree_path"

    if git $git_dir diff --quiet HEAD 2>/dev/null; then
        if git $git_dir diff --quiet --cached HEAD 2>/dev/null; then
            echo "clean"
        else
            echo "staged"
        fi
    else
        echo "dirty"
    fi
}

# 获取未提交变更数量
get_uncommitted_count() {
    local worktree_path="$1"
    git -C "$worktree_path" status --porcelain 2>/dev/null | wc -l | tr -d ' '
}

# 显示单个 worktree 状态
show_worktree_status() {
    local name="$1"
    local path="$2"
    local is_main="$3"
    local current_worktree="$4"

    local branch="$(get_worktree_branch "$path")"
    local status="$(get_worktree_status "$path")"
    local uncommitted="$(get_uncommitted_count "$path")"

    # 标记当前 worktree
    local marker=""
    if [ "$name" = "$current_worktree" ]; then
        marker="${GREEN}*${NC} "
    fi

    # 名称
    if [ "$is_main" = "true" ]; then
        echo -e "${marker}${BLUE}main${NC} ($path)"
    else
        echo -e "${marker}$name ($path)"
    fi

    # 分支
    echo "  branch: $branch"

    # 状态
    case "$status" in
        clean)
            echo -e "  status: ${GREEN}clean${NC}"
            ;;
        staged)
            echo -e "  status: ${YELLOW}staged${NC} ($uncommitted file(s))"
            ;;
        dirty)
            echo -e "  status: ${RED}dirty${NC} ($uncommitted file(s))"
            ;;
        *)
            echo -e "  status: $status"
            ;;
    esac

    echo ""
}

# 显示详细状态
show_detailed_status() {
    local worktree_path="$1"
    echo -e "${GRAY}─── 未提交变更 ───${NC}"
    git -C "$worktree_path" status --short 2>/dev/null || echo "无法获取状态"
}

# 主函数
main() {
    local current_worktree="$(get_current_worktree 2>/dev/null || echo "unknown")"

    echo ""
    log_info "Git Worktree 状态"
    echo "════════════════════"
    echo ""

    # 主仓库
    show_worktree_status "main" "." "true" "$current_worktree"

    # 所有 worktrees
    if [ -d "$WORKTREE_BASE" ]; then
        for worktree_dir in "$WORKTREE_BASE"/*; do
            if [ -d "$worktree_dir" ]; then
                local name="$(basename "$worktree_dir")"
                show_worktree_status "$name" "$worktree_dir" "false" "$current_worktree"
            fi
        done
    else
        log_dim "  (无 worktrees)"
    fi

    # 当前位置
    echo ""
    log_info "当前位置: $(pwd)"
    if [ "$current_worktree" != "unknown" ]; then
        if [ "$current_worktree" = "main" ]; then
            echo -e "  ${GREEN}→${NC} 主仓库"
        else
            echo -e "  ${GREEN}→${NC} worktree: $current_worktree"
        fi
    fi

    # 统计
    echo ""
    log_info "统计:"
    local total_worktrees=0
    if [ -d "$WORKTREE_BASE" ]; then
        total_worktrees=$(find "$WORKTREE_BASE" -maxdepth 1 -type d ! -name "$(basename "$WORKTREE_BASE")" | wc -l | tr -d ' ')
    fi
    echo "  主仓库: 1"
    echo "  Worktrees: $total_worktrees"
    echo "  总计: $((total_worktrees + 1))"
    echo ""
}

# 执行
main "$@"
