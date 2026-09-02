#!/usr/bin/env bash
# Sub-Store 交互式订阅管理脚本（快照模式，节点自动刷新由 sub-store-refresh 定时任务负责）
# 部署前必须把下方 <PREFIX> / <PUBLIC_BASE> / <SERVER_IP> 替换为实际部署值
set -euo pipefail

API='http://127.0.0.1:3000/<PREFIX>/api/proxy/parse'
FILE_API='http://127.0.0.1:3000/<PREFIX>/api'
PREFIX='<PREFIX>'
PUBLIC_BASE='<PUBLIC_BASE>'
SERVER_IP='<SERVER_IP>'

command -v curl >/dev/null || { echo '缺少 curl。' >&2; exit 1; }
command -v python3 >/dev/null || { echo '缺少 python3。' >&2; exit 1; }

choose() {
    local prompt=$1 default=$2 max=$3 value
    while true; do
        read -r -p "$prompt [$default]: " value
        value=${value:-$default}
        if [[ $value =~ ^[0-9]+$ ]] && (( value >= 1 && value <= max )); then
            REPLY=$value
            return
        fi
        echo "请输入 1-${max}。" >&2
    done
}

pick_index() {
    local prompt=$1 default=$2 max=$3 value
    while true; do
        read -r -p "$prompt [$default]: " value
        value=${value:-$default}
        if [[ $value =~ ^[0-9]+$ ]] && (( value >= 0 && value <= max )); then
            REPLY=$value
            return
        fi
        echo "请输入 0-${max}。" >&2
    done
}

check_service() {
    local status
    status=$(curl -sS -o /dev/null -w '%{http_code}' "$FILE_API/utils/env" || true)
    if [[ $status != 2* ]]; then
        echo "无法连接 Sub-Store 后端 ($FILE_API/utils/env HTTP $status)。" >&2
        return 1
    fi
}

# ---------------------------------------------------------------------------
# 快照模式（托管文件）
# ---------------------------------------------------------------------------

do_list() {
    local names
    names=$(curl -fsS "$FILE_API/files" | python3 -c "
import json, sys
data = json.load(sys.stdin).get('data', [])
if not data:
    print('')
    sys.exit(0)
for f in data:
    print(f['name'])
" 2>/dev/null)

    if [[ -z $names ]]; then
        echo '没有已发布的订阅。'
        return
    fi

    echo
    echo '已发布的订阅：'
    echo
    while IFS= read -r name; do
        [[ -n $name ]] || continue
        echo "  [$name]"
        echo "    $PUBLIC_BASE/$PREFIX/share/file/$name"
        echo
    done <<< "$names"
}

do_delete() {
    local names
    names=$(curl -fsS "$FILE_API/files" | python3 -c "
import json, sys
data = json.load(sys.stdin).get('data', [])
if not data:
    print('')
    sys.exit(0)
for i, f in enumerate(data, 1):
    print(f'{i}\t{f[\"name\"]}')
" 2>/dev/null)

    if [[ -z $names ]]; then
        echo '没有已发布的订阅。'
        return
    fi

    echo
    echo '已发布的订阅：'
    echo
    while IFS=$'\t' read -r num name; do
        echo "  $num. $name"
    done <<< "$names"
    echo
    echo "  0. 取消"
    echo

    local total
    total=$(echo "$names" | wc -l | tr -d ' ')
    pick_index '请选择要删除的序号' 0 "$total"
    [[ $REPLY == 0 ]] && { echo '已取消。'; return; }

    DEL_NAME=$(echo "$names" | sed -n "${REPLY}p" | cut -f2)
    echo "确认删除: $DEL_NAME (y/N)"
    read -r CONFIRM
    [[ $CONFIRM == [yY] ]] || { echo '已取消。'; return; }

    local encoded
    encoded=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$DEL_NAME', safe=''))")
    local result
    result=$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE "$FILE_API/file/$encoded")
    if [[ $result == 2* ]]; then
        echo "已删除: $DEL_NAME"
    else
        echo "删除失败 (HTTP $result)"
    fi
}

do_convert() {
    echo 'Sub-Store 订阅转换'
    echo
    read -r -p '订阅 URL、本地文件路径或单个节点链接: ' SOURCE
    [[ -n $SOURCE ]] || { echo '输入不能为空。' >&2; return; }

    echo
    echo '使用客户端:'
    echo '  1. Clash Verge / Clash Meta / Mihomo'
    echo '  2. Shadowrocket'
    echo '  3. 其他格式'
    choose '请选择' 1 3
    CLIENT=$REPLY

    MODE=2
    if [[ $CLIENT == 1 ]]; then
        echo
        echo '输出模式:'
        echo '  1. 完整 Mihomo 配置（节点 + 策略组 + Loyalsoldier 规则）'
        echo '  2. 仅转换 Mihomo 节点'
        choose '请选择' 1 2
        MODE=$REPLY
    elif [[ $CLIENT == 2 ]]; then
        TARGET=Shadowrocket
    fi

    if [[ $MODE == 2 ]]; then
        TARGETS=(mihomo sing-box Surge Loon QX Shadowrocket Stash V2Ray URI JSON)
        if [[ $CLIENT == 1 ]]; then
            TARGET=mihomo
        elif [[ $CLIENT == 3 ]]; then
            echo
            echo '目标格式:'
            for i in "${!TARGETS[@]}"; do
                printf '  %d. %s\n' "$((i + 1))" "${TARGETS[$i]}"
            done
            choose '请选择' 1 "${#TARGETS[@]}"
            TARGET=${TARGETS[$((REPLY - 1))]}
        fi
        POLICY_MODE=none
        RULE_SOURCE=none
        CUSTOM_RULES=
        CUSTOM_POLICIES=
        FALLBACK=
    else
        TARGET=mihomo
        echo
        echo '规则策略:'
        echo '  1. 白名单模式（推荐，未匹配流量走代理）'
        echo '  2. 黑名单模式（仅命中规则的流量走代理）'
        echo '  3. 自定义规则集和策略'
        choose '请选择' 1 3
        case $REPLY in
            1) POLICY_MODE=whitelist ;;
            2) POLICY_MODE=blacklist ;;
            3) POLICY_MODE=custom ;;
        esac

        echo
        echo '规则下载源:'
        echo '  1. GitHub Raw，经 PROXY 下载（推荐）'
        echo '  2. jsDelivr，经 PROXY 下载'
        echo '  3. jsDelivr，直连下载'
        choose '请选择' 1 3
        case $REPLY in
            1) RULE_SOURCE=github-proxy ;;
            2) RULE_SOURCE=jsdelivr-proxy ;;
            3) RULE_SOURCE=jsdelivr ;;
        esac

        CUSTOM_RULES=
        CUSTOM_POLICIES=
        FALLBACK=
        if [[ $POLICY_MODE == custom ]]; then
            echo
            cat <<'RULES'
可选规则集:
  1. applications  常见软件
  2. private       私有域名
  3. reject        广告拦截
  4. icloud        iCloud
  5. apple         Apple
  6. google        Google
  7. proxy         代理域名
  8. direct        直连域名
  9. gfw           GFWList
 10. tld-not-cn    非中国大陆顶级域名
 11. lancidr       局域网及保留 IP
 12. cncidr        中国大陆 IP
 13. telegramcidr  Telegram IP
RULES
            read -r -p '输入编号，逗号分隔 [1,2,3,7,8,11,12,13]: ' CUSTOM_RULES
            CUSTOM_RULES=${CUSTOM_RULES:-1,2,3,7,8,11,12,13}
            CUSTOM_RULES=${CUSTOM_RULES//，/,}
            declare -A RULE_NAMES=(
                [1]=applications [2]=private [3]=reject [4]=icloud [5]=apple
                [6]=google [7]=proxy [8]=direct [9]=gfw [10]=tld-not-cn
                [11]=lancidr [12]=cncidr [13]=telegramcidr
            )
            declare -A RULE_DEFAULTS=(
                [1]=DIRECT [2]=DIRECT [3]=REJECT [4]=DIRECT [5]=DIRECT
                [6]=PROXY [7]=PROXY [8]=DIRECT [9]=PROXY [10]=PROXY
                [11]=DIRECT [12]=DIRECT [13]=PROXY
            )
            echo
            echo '为每个规则集选择策略：1=PROXY，2=DIRECT，3=REJECT'
            IFS=',' read -ra SELECTED_IDS <<< "$CUSTOM_RULES"
            for raw_id in "${SELECTED_IDS[@]}"; do
                id=${raw_id//[[:space:]]/}
                [[ -n ${RULE_NAMES[$id]:-} ]] || {
                    echo "未知规则编号: $id" >&2
                    return 1
                }
                case ${RULE_DEFAULTS[$id]} in
                    PROXY) default_choice=1 ;;
                    DIRECT) default_choice=2 ;;
                    REJECT) default_choice=3 ;;
                esac
                choose "${RULE_NAMES[$id]}" "$default_choice" 3
                case $REPLY in
                    1) policy=PROXY ;;
                    2) policy=DIRECT ;;
                    3) policy=REJECT ;;
                esac
                CUSTOM_POLICIES+="${CUSTOM_POLICIES:+,}$id=$policy"
            done
            echo
            echo '未匹配流量:'
            echo '  1. PROXY'
            echo '  2. DIRECT'
            choose '请选择' 1 2
            [[ $REPLY == 1 ]] && FALLBACK=PROXY || FALLBACK=DIRECT
        fi
    fi

    echo
    echo '交付方式:'
    echo '  1. 发布为可导入的订阅 URL（推荐）'
    echo '  2. 保存为服务器本地文件'
    echo '  3. 直接打印到终端'
    choose '请选择' 1 3
    DELIVERY=$REPLY
    OUTPUT=
    PUBLISH_NAME=
    if [[ $DELIVERY == 1 ]]; then
        case $CLIENT in
            1) DEFAULT_NAME=clash-verge ;;
            2) DEFAULT_NAME=shadowrocket ;;
            *) DEFAULT_NAME=converted-subscription ;;
        esac
        read -r -p "订阅名称 [$DEFAULT_NAME]: " PUBLISH_NAME
        PUBLISH_NAME=${PUBLISH_NAME:-$DEFAULT_NAME}
        [[ $PUBLISH_NAME =~ ^[A-Za-z0-9._-]+$ ]] || {
            echo '订阅名称只能包含字母、数字、点、下划线和短横线。' >&2
            return 1
        }
    elif [[ $DELIVERY == 2 ]]; then
        [[ $MODE == 1 ]] && DEFAULT_OUTPUT=/root/mihomo.yaml ||
            DEFAULT_OUTPUT=/root/converted.yaml
        read -r -p "输出文件 [$DEFAULT_OUTPUT]: " OUTPUT
        OUTPUT=${OUTPUT:-$DEFAULT_OUTPUT}
    fi

    export API FILE_API PREFIX PUBLIC_BASE SERVER_IP SOURCE TARGET OUTPUT PUBLISH_NAME
    export POLICY_MODE RULE_SOURCE CUSTOM_RULES CUSTOM_POLICIES FALLBACK

    python3 - <<'PY'
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

api = os.environ["API"]
file_api = os.environ["FILE_API"]
prefix = os.environ["PREFIX"]
public_base = os.environ["PUBLIC_BASE"].rstrip("/")
source = os.environ["SOURCE"]
target = os.environ["TARGET"]
output = os.environ.get("OUTPUT", "")
publish_name = os.environ.get("PUBLISH_NAME", "")
policy_mode = os.environ["POLICY_MODE"]
rule_source = os.environ["RULE_SOURCE"]

providers = {
    1: ("applications", "classical", "DIRECT"),
    2: ("private", "domain", "DIRECT"),
    3: ("reject", "domain", "REJECT"),
    4: ("icloud", "domain", "DIRECT"),
    5: ("apple", "domain", "DIRECT"),
    6: ("google", "domain", "PROXY"),
    7: ("proxy", "domain", "PROXY"),
    8: ("direct", "domain", "DIRECT"),
    9: ("gfw", "domain", "PROXY"),
    10: ("tld-not-cn", "domain", "PROXY"),
    11: ("lancidr", "ipcidr", "DIRECT"),
    12: ("cncidr", "ipcidr", "DIRECT"),
    13: ("telegramcidr", "ipcidr", "PROXY"),
}


def read_source(value):
    path = pathlib.Path(value).expanduser()
    if path.is_file():
        return path.read_text(encoding="utf-8")
    if value.startswith(("http://", "https://")):
        request = urllib.request.Request(
            value, headers={"User-Agent": "Sub-Store/2.24.7"}
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.read().decode("utf-8", errors="replace")
    return value


def convert(content, client):
    request = urllib.request.Request(
        api,
        data=json.dumps({"data": content, "client": client}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
    if payload.get("status") != "success":
        raise RuntimeError(json.dumps(payload, ensure_ascii=False))
    return payload["data"]["par_res"]


def api_request(url, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        try:
            error_payload = json.loads(detail)
        except json.JSONDecodeError:
            error_payload = None
        error_code = (
            error_payload.get("error", {}).get("code")
            if isinstance(error_payload, dict)
            else None
        )
        if error.code == 404 or error_code == "FILE_NOT_FOUND":
            return None
        raise RuntimeError(f"发布失败: HTTP {error.code} {detail}") from error


def publish(content):
    encoded_name = urllib.parse.quote(publish_name, safe="")
    payload = {
        "name": publish_name,
        "displayName": publish_name,
        "source": "local",
        "content": content,
        "process": [],
    }
    existing = api_request(f"{file_api}/wholeFile/{encoded_name}")
    if existing and existing.get("status") == "success":
        response = api_request(
            f"{file_api}/file/{encoded_name}", method="PATCH", body=payload
        )
    else:
        response = api_request(f"{file_api}/files", method="POST", body=payload)
    if not response or response.get("status") != "success":
        raise RuntimeError(
            "发布失败: " + json.dumps(response, ensure_ascii=False)
        )
    share_path = f"/{prefix}/share/file/{encoded_name}"
    print()
    print("订阅链接：")
    print(f"  {public_base}{share_path}")


def yaml_string(value):
    return json.dumps(value, ensure_ascii=False)


def parse_mihomo_proxies(text):
    result = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- {"):
            result.append(json.loads(stripped[2:]))
    if not result:
        raise RuntimeError("转换结果中没有可用的 Mihomo 节点")
    return result


def selected_rules():
    if policy_mode == "whitelist":
        return [
            providers[i] for i in (1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 13)
        ], "PROXY"
    if policy_mode == "blacklist":
        return [providers[i] for i in (1, 2, 3, 10, 9, 13)], "DIRECT"

    policy_overrides = {}
    for item in os.environ.get("CUSTOM_POLICIES", "").split(","):
        if not item:
            continue
        key, policy = item.split("=", 1)
        policy_overrides[int(key)] = policy

    selected = []
    seen = set()
    for raw in os.environ["CUSTOM_RULES"].replace("，", ",").split(","):
        raw = raw.strip()
        if not raw:
            continue
        index = int(raw)
        if index not in providers:
            raise ValueError(f"未知规则编号: {index}")
        if index not in seen:
            name, behavior, default_policy = providers[index]
            selected.append(
                (name, behavior, policy_overrides.get(index, default_policy))
            )
            seen.add(index)
    if not selected:
        raise ValueError("至少选择一个规则集")
    return selected, os.environ["FALLBACK"]


def build_profile(proxy_text):
    proxies = parse_mihomo_proxies(proxy_text)
    names = []
    seen = set()
    for proxy in proxies:
        name = str(proxy.get("name", "")).strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)

    selected, fallback = selected_rules()
    provider_proxy = (
        "PROXY" if rule_source in ("github-proxy", "jsdelivr-proxy") else None
    )
    if rule_source in ("jsdelivr", "jsdelivr-proxy"):
        base = "https://cdn.jsdelivr.net/gh/Loyalsoldier/clash-rules@release/"
    else:
        base = (
            "https://raw.githubusercontent.com/"
            "Loyalsoldier/clash-rules/release/"
        )

    lines = [
        "mixed-port: 7890",
        "allow-lan: false",
        "mode: rule",
        "log-level: info",
        "ipv6: true",
        "",
        "proxies:",
    ]
    lines.extend(
        "  - " + json.dumps(proxy, ensure_ascii=False) for proxy in proxies
    )
    lines.extend(
        [
            "",
            "proxy-groups:",
            "  - name: PROXY",
            "    type: select",
            "    proxies:",
            "      - AUTO",
            "      - DIRECT",
        ]
    )
    lines.extend("      - " + yaml_string(name) for name in names)
    lines.extend(
        [
            "  - name: AUTO",
            "    type: url-test",
            "    url: https://www.gstatic.com/generate_204",
            "    interval: 300",
            "    tolerance: 50",
            "    proxies:",
        ]
    )
    lines.extend("      - " + yaml_string(name) for name in names)
    lines.extend(["", "rule-providers:"])
    for name, behavior, _policy in selected:
        lines.extend(
            [
                f"  {name}:",
                "    type: http",
                f"    behavior: {behavior}",
                f"    url: {yaml_string(base + name + '.txt')}",
                f"    path: ./ruleset/{name}.yaml",
                "    interval: 86400",
            ]
        )
        if provider_proxy:
            lines.append(f"    proxy: {provider_proxy}")
    lines.extend(["", "rules:"])
    for name, _behavior, policy in selected:
        lines.append(f"  - RULE-SET,{name},{policy}")
    lines.append(f"  - MATCH,{fallback}")
    return "\n".join(lines) + "\n", len(proxies), len(selected)


try:
    converted = convert(read_source(source), target)
    if policy_mode == "none":
        result = (
            json.dumps(converted, ensure_ascii=False, indent=2)
            if isinstance(converted, (dict, list))
            else str(converted)
        )
        if publish_name:
            publish(result)
        elif output:
            pathlib.Path(output).expanduser().write_text(
                result, encoding="utf-8"
            )
            print(f"已写入: {output}")
        else:
            print(result)
    else:
        result, proxy_count, rule_count = build_profile(str(converted))
        if publish_name:
            publish(result)
        elif output:
            destination = pathlib.Path(output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(result, encoding="utf-8")
            print(f"已生成: {destination}")
        else:
            print(result)
        print(f"节点数量: {proxy_count}")
        print(f"规则集数量: {rule_count}")
        print(f"策略模式: {policy_mode}")
except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
    print(f"转换失败: {error}", file=sys.stderr)
    sys.exit(1)
PY
}

# ---------------------------------------------------------------------------
# 主菜单
# ---------------------------------------------------------------------------

check_service || exit 1

echo 'Sub-Store 订阅管理'
echo
echo '  快照模式（完整配置，节点自动刷新见 sub-store-refresh 定时任务）'
echo '    1. 新增订阅（转换并发布）'
echo '    2. 查看已发布订阅'
echo '    3. 修改订阅（重新转换并覆盖）'
echo '    4. 删除订阅'
echo '    0. 退出'
echo
pick_index '请选择' 0 4
ACTION=$REPLY

case $ACTION in
    1) do_convert ;;
    2) do_list ;;
    3) do_convert ;;
    4) do_delete ;;
    0) exit 0 ;;
    *) echo '无效选择。' >&2 ;;
esac
