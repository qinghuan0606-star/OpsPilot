# Linux 网络配置与连通性排查

> 来源类型：self_written（自写整理）
> 来源说明：依据 `ip(8)`、`ss(8)`、`nmcli(1)`、`resolvectl(1)`、`sysctl(8)` 的公开 man page 语义整理
> 来源链接：https://man7.org/linux/man-pages/man8/ip.8.html
> 适用系统：Linux 通用；`nmcli` 需 NetworkManager 已安装并接管网络
> 适用版本：iproute2 5.x+、NetworkManager 1.30+
> 更新日期：2026-11-17
> 核实状态：通用命令语义已核实；两发行版默认是否由 NetworkManager 接管**未逐版本核实**，以现场 `systemctl status NetworkManager` 为准

## 技术概念

- **地址与路由分离**：`ip addr` 看接口地址，`ip route` 看转发路径；有地址但无默认路由，仍然出不去。
- **监听与防火墙分离**：`ss -lntp` 证明进程在监听，不代表外部可达；还要看 firewalld/nftables 与云安全组。
- **DNS 解析链**：`/etc/resolv.conf` → `resolvectl`/nsswitch → 应用缓存；解析失败与网络不通是两类问题。
- **接口命名**：现代发行版多用可预测命名（`ens33`、`enp0s3`），不要硬编码 `eth0`。

## 使用场景

- 新机器上线后无法访问外网/内网。
- 服务端口已监听但客户端连接超时。
- 修改 IP 后配置未持久化，重启即失效。
- DNS 解析异常导致 `yum/dnf`、容器拉取失败。

## 操作步骤

1. `ip addr`、`ip route` 确认地址与默认路由。
2. `ss -lntp` 确认目标端口由预期进程监听，且绑定地址不是仅 `127.0.0.1`。
3. `ping` 网关、`ping` 外部 IP（区分二层/三层/出网）。
4. `getent hosts` 与 `dig` 对比，判断 DNS 问题。
5. 检查 firewalld / nftables / SELinux 端口策略。
6. 持久化配置：NetworkManager 用 `nmcli`，避免只改运行时。

## 命令示例

```bash
# 地址、链路、路由
ip -br addr
ip route show default
ip neigh show

# 端口监听（-p 需要 root 才显示进程）
ss -lntp | grep -E ':80|:443|:22'

# 连通性分层测试
ping -c 3 <网关IP>
ping -c 3 <外部IP>
curl -vk --max-time 5 https://<目标域名>/health

# DNS
getent hosts <域名>
resolvectl status 2>/dev/null || cat /etc/resolv.conf

# NetworkManager 持久化示例（不要照抄地址）
nmcli connection show
nmcli con mod "<连接名>" ipv4.addresses 192.0.2.10/24 ipv4.gateway 192.0.2.1 ipv4.dns "192.0.2.53" ipv4.method manual
nmcli con up "<连接名>"

# 防火墙放行（firewalld；nftables 环境按实际规则集操作）
firewall-cmd --permanent --add-port=8080/tcp
firewall-cmd --reload
```

## 预期输出及其含义（示意，非本机实测）

```text
$ ip -br addr
lo     UNKNOWN  127.0.0.1/8
ens33  UP       192.0.2.10/24

$ ip route show default
default via 192.0.2.1 dev ens33 proto static metric 100
```

- 接口 `UP` 且拿到地址，说明链路与 DHCP/静态配置基本正常。
- 没有 `default via` 行，说明只有同网段可达，跨网段必然失败。

```text
$ ss -lntp | grep :8080
LISTEN 0 128 127.0.0.1:8080 0.0.0.0:* users:(("java",pid=1234,fd=56))
```

- 绑定 `127.0.0.1` 表示只监听本机回环，远端访问一定失败；应改为 `0.0.0.0` 或指定内网地址（同时评估暴露面）。

## 常见错误

| 现象 | 常见原因 |
|---|---|
| 本机 `curl 127.0.0.1:端口` 通，外部不通 | 进程绑定回环地址；或防火墙/安全组未放行 |
| 改完地址立即断连 | 远程改网络未加回滚定时任务，或默认路由被覆盖 |
| `Could not resolve host` | `/etc/resolv.conf` 被 NetworkManager 覆盖、DNS 不可达 |
| 重启后配置丢失 | 只用了 `ip addr add`，没有写持久化配置 |
| 容器内不通、宿主机通 | 容器网络命名空间、iptables/nftables 转发或 `ip_forward` 关闭 |

## 排查思路

从下往上：链路（`ip link`）→ 地址（`ip addr`）→ 路由（`ip route`）→ 监听（`ss`）→ 本机策略（防火墙/SELinux）→ 外部策略（安全组/交换机 ACL）→ DNS。每层先用最小命令证实或排除，不要一上来改配置。

## 安全注意事项

- 远程改网络前先设置自动回滚（例如 `sleep 300 && nmcli con up <旧配置>` 的后台任务），避免失联。
- 不要把管理端口直接暴露到公网；放行规则应限定来源网段。
- 禁止为排查方便长期关闭防火墙/SELinux；应使用精确放行并留痕。
- 示例中的 IP 为文档专用地址段（192.0.2.0/24），不得直接套用到生产。

## 未核实与版本差异

- openEuler 与麒麟 V10 默认使用 NetworkManager 还是 network-scripts/ifcfg 配置，本文未逐版本核实。
- `firewall-cmd` 在两发行版上的默认 zone 与默认策略可能不同，需现场 `firewall-cmd --list-all` 确认。
- 麒麟 V10 部分版本可能默认启用 `nftables` 后端或保留 iptables 兼容层，未核实。
